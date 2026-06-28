"""
skills — Kali writes, tests, and saves her own Python tools.

The Hermes "self-improving skills" idea, fitted to Kali's existing safety
model instead of bolted on beside it.  The flow mirrors propose_edit exactly:

  1. The model calls skill_write(name, code, test, description, capabilities).
     This SAVES NOTHING.  It returns a proposal payload the host renders as a
     card.  No code runs, no file is written.
  2. The operator clicks Apply.  THAT click is the approval.  The host calls
     extman.commit_skill(...), which:
        a. ast-parses the code (reject syntax errors),
        b. runs a static screen (advisory — flags risky imports/calls; this
           is NOT a security boundary, the sandbox is),
        c. runs the skill's own test in the sandbox.  No passing test => no
           save.  A skill that can't prove it works does not get kept.
        d. writes name/, code, manifest (with a content hash), registers it.
  3. From then on the skill is exposed as the tool skill_run{name,args}, and
     every invocation goes back through the sandbox.  There is no path by
     which skill code executes in Kali's own interpreter.

Curation (Hermes' curator, shrunk): skills unused past a threshold are
ARCHIVED, never deleted.  Archive is one move from restored.

Layout:
    <skills_dir>/<name>/skill.py
                       /manifest.json
                       /test.py
    <skills_dir>/.archive/<name>/...
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import sandbox


_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")

# Advisory static screen.  Presence of these is surfaced to the operator on
# the card; it does NOT block (the sandbox is the boundary).  The point is to
# make a "this skill shells out / opens sockets / loads ctypes" obvious before
# Apply, not to pretend we can statically prove safety.
_RISKY = {
    "os.system", "subprocess", "socket", "ctypes", "cffi", "pty",
    "multiprocessing", "shutil.rmtree", "os.remove", "os.unlink",
    "eval", "exec", "compile", "__import__", "open(",
    "requests", "urllib", "httpx", "ftplib", "paramiko",
}

# Capabilities a skill may declare.  Default-deny: the host grants only what
# the operator approved, and the sandbox enforces the big one (net).
VALID_CAPS = {"net", "fs_write", "long_running"}

ARCHIVE_AFTER_DAYS = 45


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class SkillStore:
    def __init__(self, skills_dir: Path):
        self.dir = Path(skills_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / ".archive").mkdir(exist_ok=True)

    # ── discovery ──────────────────────────────────────────────────────
    def list_skills(self) -> List[Dict[str, Any]]:
        out = []
        for d in sorted(self.dir.iterdir()):
            if not d.is_dir() or d.name.startswith("."):
                continue
            m = d / "manifest.json"
            if m.exists():
                try:
                    out.append(json.loads(m.read_text()))
                except Exception:
                    continue
        return out

    def prompt_block(self) -> str:
        skills = self.list_skills()
        head = (
            "SKILLS: you can author your own Python tools and save them for "
            "reuse.  To create one, call skill_write with: name (snake_case), "
            "a description, the code (a function `run(args: dict) -> dict` that "
            "RETURNS a dict — do NOT print; the runner serialises whatever you "
            "return), a test (asserts that exercise run()),"
            " and any capabilities it needs (subset of net/fs_write/"
            "long_running; default none).  The skill runs in an isolated "
            "sandbox with the PYTHON STANDARD LIBRARY ONLY — no third-party "
            "packages (no requests, numpy, etc.); use urllib for net if the "
            "skill has the net capability.  skill_write only PROPOSES — the "
            "operator approves it, it is sandbox-tested, and only saved if the "
            "test passes.  Run a saved skill with skill_run{name,args}.  List "
            "them with skill_list.  Write a skill when a task is repeatable; "
            "don't write one for a one-off.")
        if not skills:
            return head + "\n  (no skills saved yet.)"
        lines = [head, "  Saved skills you can skill_run:"]
        for s in skills:
            caps = ",".join(s.get("capabilities", [])) or "none"
            lines.append(f"   - {s['name']}: {s.get('description','')} "
                         f"(caps: {caps})")
        return "\n".join(lines)

    # ── propose (no write) ─────────────────────────────────────────────
    def tool_propose(self, name: str, code: str, test: str,
                     description: str, capabilities: List[str]) -> str:
        problems = self._prevalidate(name, code, capabilities)
        risky = sorted({r for r in _RISKY if r in code})
        sb = sandbox.capabilities_report()
        payload = {
            "proposal": "skill",
            "name": name,
            "description": description,
            "capabilities": capabilities,
            "static_flags": risky,
            "sandbox_tier": sb["tier"],
            "blocking_problems": problems,
            "note": ("This is a PROPOSAL. Nothing is saved. On Apply the code "
                     "is ast-checked, statically screened, and its test is run "
                     "in the sandbox; it is saved only if the test passes."),
        }
        # The host turns this into a propose_edit-style card.  We hand back
        # the full code/test too so the card can show them and the Apply
        # handler can pass them to commit_skill.
        payload["_code"] = code
        payload["_test"] = test
        return json.dumps(payload, indent=2)

    def _prevalidate(self, name: str, code: str,
                     capabilities: List[str]) -> List[str]:
        problems: List[str] = []
        if not _NAME_RE.match(name or ""):
            problems.append("name must be snake_case, 2-41 chars, [a-z0-9_].")
        bad_caps = set(capabilities or []) - VALID_CAPS
        if bad_caps:
            problems.append(f"unknown capabilities: {sorted(bad_caps)}")
        try:
            tree = ast.parse(code or "")
        except SyntaxError as e:
            problems.append(f"syntax error line {e.lineno}: {e.msg}")
            return problems
        has_run = any(isinstance(n, ast.FunctionDef) and n.name == "run"
                      for n in tree.body)
        if not has_run:
            problems.append("code must define a top-level `def run(args): ...`")
        return problems

    # ── commit (after operator Apply) ──────────────────────────────────
    def commit(self, name: str, code: str, test: str, description: str,
               capabilities: List[str]) -> Dict[str, Any]:
        problems = self._prevalidate(name, code, capabilities)
        if problems:
            return {"ok": False, "stage": "validate", "problems": problems}

        # Stage the skill in a temp build dir, test it there, only then
        # promote.  A failing test never touches the live skills dir.
        build = self.dir / f".build-{name}-{int(time.time())}"
        build.mkdir(parents=True, exist_ok=True)
        try:
            runner = self._make_test_runner(code, test)
            (build / "runner.py").write_text(runner)
            allow_net = "net" in (capabilities or [])
            res = sandbox.run_python(str(build / "runner.py"),
                                     args_json="{}",
                                     timeout=30,
                                     allow_net=allow_net)
            if not res["ok"]:
                return {"ok": False, "stage": "test",
                        "sandbox": res,
                        "reason": ("test failed / errored / timed out in the "
                                   "sandbox; skill not saved.")}
            # promote
            dst = self.dir / name
            if dst.exists():
                shutil.rmtree(dst)
            dst.mkdir(parents=True)
            (dst / "skill.py").write_text(code)
            (dst / "test.py").write_text(test)
            manifest = {
                "name": name,
                "description": description,
                "capabilities": list(capabilities or []),
                "created": time.time(),
                "last_used": 0.0,
                "uses": 0,
                "version": 1,
                "hash": _hash(code),
                "sandbox_tier_at_save": res.get("tier"),
            }
            (dst / "manifest.json").write_text(json.dumps(manifest, indent=2))
            return {"ok": True, "name": name, "test": res,
                    "tier": res.get("tier")}
        finally:
            shutil.rmtree(build, ignore_errors=True)

    @staticmethod
    def _make_test_runner(code: str, test: str) -> str:
        # The skill code defines run(); the test asserts against it.  We
        # concatenate into one file the sandbox executes.  A clean exit (rc 0)
        # means every assertion held.
        return (code
                + "\n\n# ---- test ----\n"
                + test
                + "\n\nprint('SKILL_TEST_OK')\n")

    # ── run a saved skill (always sandboxed) ───────────────────────────
    def run_skill(self, name: str, args: Dict[str, Any],
                  timeout: int = 20) -> Dict[str, Any]:
        d = self.dir / name
        man_path = d / "manifest.json"
        if not man_path.exists():
            return {"ok": False, "error": f"no skill named {name!r}"}
        manifest = json.loads(man_path.read_text())
        # Tamper check: refuse to run code whose hash drifted from the manifest
        # (caught a manual edit / corruption — re-commit to re-bless it).
        code = (d / "skill.py").read_text()
        if _hash(code) != manifest.get("hash"):
            return {"ok": False, "error": ("skill code hash mismatch — it was "
                                           "modified after save. Re-create it "
                                           "to re-validate.")}
        allow_net = "net" in manifest.get("capabilities", [])
        # Wrap: call run(args) and print its JSON.  Use underscore-prefixed
        # names so we never collide with a global the skill itself defined, and
        # turn a run() exception into a structured result the model can read
        # instead of a bare traceback on stderr with a non-zero exit.
        invoker = (
            code
            + "\n\nimport json as _json, sys as _sys\n"
            + "_args = _json.loads(_sys.argv[1]) if len(_sys.argv) > 1 else {}\n"
            + "try:\n"
            + "    _result = run(_args)\n"
            + "except Exception as _e:\n"
            + "    _result = {'error': type(_e).__name__ + ': ' + str(_e)}\n"
            + "if _result is None:\n"
            + "    _result = {}\n"
            + "print(_json.dumps(_result, default=str))\n")
        build = self.dir / f".run-{name}-{int(time.time()*1000)}"
        build.mkdir(parents=True, exist_ok=True)
        try:
            (build / "invoke.py").write_text(invoker)
            res = sandbox.run_python(str(build / "invoke.py"),
                                     args_json=json.dumps(args or {}),
                                     timeout=timeout,
                                     allow_net=allow_net)
            if res["ok"]:
                manifest["uses"] = manifest.get("uses", 0) + 1
                manifest["last_used"] = time.time()
                man_path.write_text(json.dumps(manifest, indent=2))
            return res
        finally:
            shutil.rmtree(build, ignore_errors=True)

    # ── curator (archive stale, never delete) ──────────────────────────
    def curate(self) -> Dict[str, Any]:
        now = time.time()
        archived = []
        for s in self.list_skills():
            last = s.get("last_used") or s.get("created", now)
            age_days = (now - last) / 86400.0
            if age_days > ARCHIVE_AFTER_DAYS and s.get("uses", 0) == 0:
                src = self.dir / s["name"]
                dst = self.dir / ".archive" / s["name"]
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.move(str(src), str(dst))
                archived.append(s["name"])
        return {"archived": archived}

    # ── tool surface ───────────────────────────────────────────────────
    def tool_list(self) -> str:
        skills = self.list_skills()
        if not skills:
            return "no saved skills."
        return json.dumps([{k: s.get(k) for k in
                            ("name", "description", "capabilities",
                             "uses", "version")} for s in skills], indent=2)

    def tool_run(self, name: str, args: Dict[str, Any],
                 timeout: int = 20) -> str:
        res = self.run_skill(name, args, timeout=timeout)
        return json.dumps(res, indent=2)
