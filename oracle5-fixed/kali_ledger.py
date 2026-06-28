"""
kali_ledger.py — an append-only, integrity-checkable evidence ledger for every
command Kali runs.

The difference between a chat transcript and a defensible pentest deliverable is
*evidence*: a tamper-evident record of exactly what ran, when, with what result,
and proof the output wasn't edited after the fact.  This module is that record.

For each executed command it appends one JSON line to
``~/.config/kali/evidence/<engagement>.jsonl`` capturing the timestamp,
engagement, monotonically increasing step number, the command and the model's
stated reason, the working directory and user, the exit code, the wall-clock
duration, and — critically — the SHA-256 of stdout and stderr.  The full output
is written to a side artifact file whose hash is recorded, so the ledger line
stays small while the evidence stays complete and verifiable: ``verify()``
re-hashes every artifact and reports any mismatch, which catches after-the-fact
tampering with the captured output.

Design rules:
  • Pure stdlib (json, os, time, hashlib, pathlib, threading) — GTK-free and
    trivially unit-testable offline.
  • FAIL-SAFE: a ledger write must never break command execution.  Every public
    entry point swallows its own errors and returns a sentinel rather than
    raising into the caller's run loop.
  • Append-only: events are never rewritten in place, so the file itself is the
    audit trail.
  • Thread-safe: a lock guards the append, since commands run on a worker
    thread.

Nothing here decides whether a command may run — that's the safety floor's job
(kali_safety).  The ledger only records what already happened.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_LOCK = threading.RLock()

# Only allow tame engagement names so they're safe as filenames.
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_DEFAULT_ENGAGEMENT = "default"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_name(name: Optional[str]) -> str:
    name = (name or "").strip() or _DEFAULT_ENGAGEMENT
    name = _SAFE_NAME_RE.sub("-", name).strip("-.") or _DEFAULT_ENGAGEMENT
    return name[:64]


class EvidenceLedger:
    """Append-only evidence store for a tree of engagements.

    ``base_dir`` defaults to ~/.config/kali/evidence.  One ``.jsonl`` file and
    one ``<engagement>.artifacts/`` directory exist per engagement.
    """

    def __init__(self, base_dir: Optional[Path] = None,
                 engagement: Optional[str] = None):
        if base_dir is None:
            base_dir = Path(os.path.expanduser("~")) / ".config" / "kali" / "evidence"
        self.base_dir = Path(base_dir)
        self._engagement = _safe_name(engagement)
        try:
            self.base_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass  # fail-safe: recording will no-op if the dir can't be made

    # ── engagement selection ──────────────────────────────────────────
    @property
    def engagement(self) -> str:
        return self._engagement

    def set_engagement(self, name: str) -> str:
        """Switch the active engagement (creates it lazily on first write)."""
        with _LOCK:
            self._engagement = _safe_name(name)
        return self._engagement

    def list_engagements(self) -> List[str]:
        try:
            return sorted(p.stem for p in self.base_dir.glob("*.jsonl"))
        except Exception:
            return []

    def _ledger_path(self, engagement: Optional[str] = None) -> Path:
        return self.base_dir / f"{_safe_name(engagement or self._engagement)}.jsonl"

    def _artifact_dir(self, engagement: Optional[str] = None) -> Path:
        return self.base_dir / f"{_safe_name(engagement or self._engagement)}.artifacts"

    def _next_step(self, engagement: str) -> int:
        """One-based step counter — number of lines already in the ledger + 1."""
        path = self._ledger_path(engagement)
        if not path.exists():
            return 1
        try:
            with open(path, "r", encoding="utf-8") as f:
                return sum(1 for _ in f) + 1
        except Exception:
            return 1

    # ── recording ─────────────────────────────────────────────────────
    def record(self, command: str, reason: str, result: Dict[str, Any],
               kind: str = "command") -> Optional[Dict[str, Any]]:
        """Append one evidence event for an executed command.

        ``result`` is the dict returned by tool_run_command:
        {ok, rc, stdout, stderr, error, ...}.  Returns the event dict that was
        written (handy for tests / display), or None if recording failed — and
        a None return must be treated as "carry on", never as an error.
        """
        try:
            with _LOCK:
                engagement = self._engagement
                step = self._next_step(engagement)
                ts = time.time()

                stdout = result.get("stdout") or ""
                stderr = result.get("stderr") or ""
                so_b = stdout.encode("utf-8", "replace")
                se_b = stderr.encode("utf-8", "replace")

                artifact_rel = None
                if so_b or se_b:
                    artifact_rel = self._write_artifact(
                        engagement, step, command, so_b, se_b)

                event = {
                    "ts": round(ts, 3),
                    "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts)),
                    "engagement": engagement,
                    "step": step,
                    "kind": kind,
                    "command": command,
                    "reason": reason or "",
                    "cwd": _safe_cwd(),
                    "user": _safe_user(),
                    "ok": bool(result.get("ok", False)),
                    "rc": result.get("rc"),
                    "error": result.get("error"),
                    "duration_ms": result.get("duration_ms"),
                    "stdout_bytes": len(so_b),
                    "stderr_bytes": len(se_b),
                    "stdout_sha256": _sha256(so_b) if so_b else None,
                    "stderr_sha256": _sha256(se_b) if se_b else None,
                    "artifact": artifact_rel,
                }
                line = json.dumps(event, ensure_ascii=False)
                with open(self._ledger_path(engagement), "a",
                          encoding="utf-8") as f:
                    f.write(line + "\n")
                return event
        except Exception:
            return None  # fail-safe — never break the run loop

    def _write_artifact(self, engagement: str, step: int, command: str,
                        so_b: bytes, se_b: bytes) -> Optional[str]:
        try:
            adir = self._artifact_dir(engagement)
            adir.mkdir(parents=True, exist_ok=True)
            fname = f"step-{step:04d}.txt"
            blob = (b"# command: " + command.encode("utf-8", "replace") + b"\n"
                    b"# --- stdout ---\n" + so_b +
                    b"\n# --- stderr ---\n" + se_b + b"\n")
            (adir / fname).write_bytes(blob)
            return f"{adir.name}/{fname}"
        except Exception:
            return None

    # ── review / export ───────────────────────────────────────────────
    def read_events(self, engagement: Optional[str] = None,
                    limit: Optional[int] = None) -> List[Dict[str, Any]]:
        path = self._ledger_path(engagement)
        if not path.exists():
            return []
        events: List[Dict[str, Any]] = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                for ln in f:
                    ln = ln.strip()
                    if not ln:
                        continue
                    try:
                        events.append(json.loads(ln))
                    except Exception:
                        continue  # skip a corrupted line, keep the rest
        except Exception:
            return events
        if limit is not None and limit >= 0:
            return events[-limit:]
        return events

    def summary(self, engagement: Optional[str] = None) -> Dict[str, Any]:
        events = self.read_events(engagement)
        ok = sum(1 for e in events if e.get("ok"))
        failed = len(events) - ok
        return {
            "engagement": _safe_name(engagement or self._engagement),
            "steps": len(events),
            "ok": ok,
            "failed": failed,
            "first_ts": events[0].get("ts") if events else None,
            "last_ts": events[-1].get("ts") if events else None,
        }

    def verify(self, engagement: Optional[str] = None) -> Dict[str, Any]:
        """Re-hash every artifact and confirm it matches the recorded SHA-256.

        This is the tamper-evidence: if a captured output file was edited after
        the fact, its hash no longer matches the ledger line and it shows up
        here as a mismatch.
        """
        events = self.read_events(engagement)
        checked = matched = 0
        problems: List[Dict[str, Any]] = []
        for e in events:
            rel = e.get("artifact")
            if not rel:
                continue
            checked += 1
            apath = self.base_dir / rel
            if not apath.exists():
                problems.append({"step": e.get("step"), "issue": "artifact missing"})
                continue
            try:
                blob = apath.read_bytes()
            except Exception:
                problems.append({"step": e.get("step"), "issue": "artifact unreadable"})
                continue
            # The artifact embeds stdout between the two markers; re-derive and
            # hash exactly what was hashed at record time.
            so = _extract_section(blob, b"# --- stdout ---\n", b"\n# --- stderr ---\n")
            se = _extract_section(blob, b"\n# --- stderr ---\n", None)
            so_ok = (e.get("stdout_sha256") in (None, _sha256(so)) if so or e.get("stdout_sha256") else True)
            se_ok = (e.get("stderr_sha256") in (None, _sha256(se)) if se or e.get("stderr_sha256") else True)
            if so_ok and se_ok:
                matched += 1
            else:
                problems.append({"step": e.get("step"), "issue": "hash mismatch"})
        return {
            "engagement": _safe_name(engagement or self._engagement),
            "artifacts_checked": checked,
            "artifacts_matched": matched,
            "intact": len(problems) == 0,
            "problems": problems,
        }

    def export_markdown(self, engagement: Optional[str] = None) -> str:
        """A human-readable evidence report for the engagement."""
        eng = _safe_name(engagement or self._engagement)
        events = self.read_events(engagement)
        if not events:
            return f"# Evidence — {eng}\n\n_No recorded commands yet._\n"
        s = self.summary(engagement)
        out = [f"# Evidence ledger — {eng}", ""]
        out.append(f"- Steps: **{s['steps']}**  (ok {s['ok']} · failed {s['failed']})")
        if s["first_ts"] and s["last_ts"]:
            span = max(0, int(s["last_ts"] - s["first_ts"]))
            out.append(f"- Window: {events[0].get('iso','?')} → "
                       f"{events[-1].get('iso','?')}  ({span}s)")
        v = self.verify(engagement)
        out.append(f"- Integrity: {'✅ all artifacts intact' if v['intact'] else '⚠ ' + str(len(v['problems'])) + ' problem(s)'}")
        out.append("")
        out.append("| # | time (UTC) | rc | command | reason |")
        out.append("|---|---|---|---|---|")
        for e in events:
            rc = e.get("rc")
            rc_s = "—" if rc is None else str(rc)
            cmd = (e.get("command") or "").replace("|", "\\|")[:90]
            rsn = (e.get("reason") or "").replace("|", "\\|")[:60]
            out.append(f"| {e.get('step')} | {e.get('iso','?')} | {rc_s} | `{cmd}` | {rsn} |")
        return "\n".join(out) + "\n"


def _extract_section(blob: bytes, start: bytes, end: Optional[bytes]) -> bytes:
    i = blob.find(start)
    if i < 0:
        return b""
    i += len(start)
    if end is None:
        j = len(blob)
        # trim the single trailing newline added at write time
        seg = blob[i:j]
        return seg[:-1] if seg.endswith(b"\n") else seg
    j = blob.find(end, i)
    if j < 0:
        j = len(blob)
    return blob[i:j]


def _safe_cwd() -> str:
    try:
        return os.getcwd()
    except Exception:
        return "?"


def _safe_user() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return os.environ.get("USER", "?")
