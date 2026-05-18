#!/usr/bin/env python3
"""
oracle_core — non-UI logic for Oracle

Responsibilities:
    · Ollama lifecycle (start / stop / health / model list)
    · Streaming chat API
    · SQLite chat history
    · Tool execution (file read, shell exec, system info)
    · Security audit (ares-derived, read-only, parallel)
    · Local network scan (nmap if present, ss-only fallback)
    · Offline status detection

No GTK imports here. GTK code lives in oracle.py.
"""

from __future__ import annotations

import os
import re
import sys
import json
import time
import shutil
import socket
import sqlite3
import urllib.request
import urllib.error
import subprocess
import threading
import concurrent.futures
import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Any, Callable, Iterator

# ═════════════════════════════════════════════════════════════════════
# PATHS & CONSTANTS
# ═════════════════════════════════════════════════════════════════════

HOME              = Path.home()
DATA_DIR          = HOME / ".local" / "share" / "oracle"
CONFIG_DIR        = HOME / ".config" / "oracle"
CHATS_DB          = DATA_DIR / "chats.db"
SETTINGS_JSON     = CONFIG_DIR / "settings.json"
LOG_FILE          = DATA_DIR / "oracle.log"

DATA_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

OLLAMA_HOST       = "http://127.0.0.1:11434"
OLLAMA_BIN        = shutil.which("ollama") or "/usr/local/bin/ollama"
HTTP_TIMEOUT_S    = 600     # streams can be long on a phone
HEALTH_TIMEOUT_S  = 1.5

# Sensitive paths — these require explicit operator confirmation
# even in agent mode.  Path *prefixes*.
SENSITIVE_PATHS = (
    "/etc/shadow", "/etc/gshadow", "/etc/sudoers",
    "/root/.ssh", str(HOME / ".ssh"),
    str(HOME / ".gnupg"),
    str(HOME / ".aws"), str(HOME / ".config" / "gh"),
    str(HOME / ".password-store"),
    "/proc/kcore", "/proc/kmem",
)


# ═════════════════════════════════════════════════════════════════════
# LOG
# ═════════════════════════════════════════════════════════════════════

def log(msg: str) -> None:
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now().isoformat(timespec='seconds')}] {msg}\n")
    except Exception:
        pass


# ═════════════════════════════════════════════════════════════════════
# SETTINGS
# ═════════════════════════════════════════════════════════════════════

DEFAULT_SETTINGS = {
    "default_model": "",                # picked from installed list on first run
    "temperature": 0.7,
    "top_p": 0.9,
    "num_ctx": 4096,                    # OP6 RAM-friendly
    "system_prompt": "",                # empty = use built-in default
    "auto_start_ollama": True,
    "stop_ollama_on_quit": False,
    "agent_mode_default": False,
    "confirm_all_commands": True,       # if false, only confirm risky ones
    "theme": "mocha",                   # mocha | latte
    "wrap_messages": True,
    "show_token_count": False,
}


def load_settings() -> Dict[str, Any]:
    if SETTINGS_JSON.exists():
        try:
            with open(SETTINGS_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
            merged = dict(DEFAULT_SETTINGS)
            merged.update(data)
            return merged
        except Exception:
            pass
    return dict(DEFAULT_SETTINGS)


def save_settings(settings: Dict[str, Any]) -> None:
    try:
        with open(SETTINGS_JSON, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
    except Exception as e:
        log(f"save_settings error: {e}")


# ═════════════════════════════════════════════════════════════════════
# OLLAMA LIFECYCLE
# ═════════════════════════════════════════════════════════════════════

class OllamaManager:
    """Manages the local ollama serve process and HTTP API access."""

    def __init__(self):
        self._proc: Optional[subprocess.Popen] = None
        self._started_by_us = False

    # ── lifecycle ───────────────────────────────────────────────

    def is_running(self) -> bool:
        try:
            req = urllib.request.Request(f"{OLLAMA_HOST}/api/version")
            with urllib.request.urlopen(req, timeout=HEALTH_TIMEOUT_S) as r:
                return r.status == 200
        except Exception:
            return False

    def start_serve(self) -> bool:
        """Start `ollama serve` if not already running.  Returns success."""
        if self.is_running():
            return True
        if not shutil.which("ollama"):
            log("ollama binary not found in PATH")
            return False
        try:
            # Detach from our process group so the user can quit the UI
            # without killing Ollama, if they want.  We track _proc anyway
            # in case they configure stop_ollama_on_quit=True.
            self._proc = subprocess.Popen(
                ["ollama", "serve"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            self._started_by_us = True
            log(f"started ollama serve, pid={self._proc.pid}")
            # Wait up to 5s for it to come up
            for _ in range(20):
                time.sleep(0.25)
                if self.is_running():
                    return True
            log("ollama serve did not become healthy in 5s")
            return False
        except Exception as e:
            log(f"start_serve error: {e}")
            return False

    def stop_serve(self) -> None:
        """Stop ollama serve if we started it.  Safe to call multiple times."""
        if not self._started_by_us or self._proc is None:
            return
        try:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=4)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            log("stopped ollama serve")
        except Exception as e:
            log(f"stop_serve error: {e}")
        finally:
            self._proc = None
            self._started_by_us = False

    # ── model registry ──────────────────────────────────────────

    def list_models(self) -> List[Dict[str, Any]]:
        """Return list of locally installed models."""
        try:
            req = urllib.request.Request(f"{OLLAMA_HOST}/api/tags")
            with urllib.request.urlopen(req, timeout=5) as r:
                data = json.loads(r.read())
            models = data.get("models", [])
            return sorted(models, key=lambda m: m.get("name", ""))
        except Exception as e:
            log(f"list_models error: {e}")
            return []

    def version(self) -> Optional[str]:
        try:
            req = urllib.request.Request(f"{OLLAMA_HOST}/api/version")
            with urllib.request.urlopen(req, timeout=HEALTH_TIMEOUT_S) as r:
                return json.loads(r.read()).get("version")
        except Exception:
            return None

    def pull_model(self, name: str, on_progress: Callable[[str], None]) -> bool:
        """Pull a model, streaming progress lines to callback."""
        try:
            payload = json.dumps({"name": name}).encode("utf-8")
            req = urllib.request.Request(
                f"{OLLAMA_HOST}/api/pull",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as r:
                for line in r:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                    except Exception:
                        continue
                    status = msg.get("status", "")
                    if "completed" in msg and "total" in msg:
                        pct = int(100 * msg["completed"] / max(msg["total"], 1))
                        on_progress(f"{status} {pct}%")
                    else:
                        on_progress(status)
            return True
        except Exception as e:
            log(f"pull_model error: {e}")
            on_progress(f"error: {e}")
            return False

    # ── streaming chat ──────────────────────────────────────────

    def stream_chat(
        self,
        model: str,
        messages: List[Dict[str, str]],
        on_token: Callable[[str], None],
        on_done: Callable[[Dict[str, Any]], None],
        on_error: Callable[[str], None],
        options: Optional[Dict[str, Any]] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> None:
        """Stream tokens from ollama /api/chat.  Blocking; run in a thread."""
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
        }
        if options:
            payload["options"] = options

        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                f"{OLLAMA_HOST}/api/chat",
                data=data,
                headers={"Content-Type": "application/json"},
            )
            full_text_parts: List[str] = []
            final_meta: Dict[str, Any] = {}
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as r:
                for line in r:
                    if cancel_event and cancel_event.is_set():
                        on_done({"cancelled": True, "text": "".join(full_text_parts)})
                        return
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except Exception:
                        continue
                    msg = chunk.get("message", {})
                    tok = msg.get("content", "")
                    if tok:
                        full_text_parts.append(tok)
                        on_token(tok)
                    if chunk.get("done"):
                        final_meta = {
                            "text": "".join(full_text_parts),
                            "total_duration": chunk.get("total_duration"),
                            "eval_count": chunk.get("eval_count"),
                            "prompt_eval_count": chunk.get("prompt_eval_count"),
                            "cancelled": False,
                        }
                        break
            on_done(final_meta)
        except urllib.error.URLError as e:
            on_error(f"connection error: {e.reason}")
        except Exception as e:
            on_error(f"{type(e).__name__}: {e}")


# ═════════════════════════════════════════════════════════════════════
# CHAT DATABASE
# ═════════════════════════════════════════════════════════════════════

CHAT_DDL = """
CREATE TABLE IF NOT EXISTS chats (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    model       TEXT,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL,
    pinned      INTEGER NOT NULL DEFAULT 0,
    agent_mode  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     INTEGER NOT NULL,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    ts          REAL NOT NULL,
    meta        TEXT,
    FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, ts);
"""


@dataclass
class Chat:
    id: int
    title: str
    model: str
    created_at: float
    updated_at: float
    pinned: int = 0
    agent_mode: int = 0


@dataclass
class Message:
    id: int
    chat_id: int
    role: str          # 'user' | 'assistant' | 'system' | 'tool'
    content: str
    ts: float
    meta: Dict[str, Any] = field(default_factory=dict)


class ChatStore:
    def __init__(self, path: Path = CHATS_DB):
        self.path = path
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(CHAT_DDL)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, check_same_thread=False)
        c.execute("PRAGMA foreign_keys=ON")
        return c

    # ── chats ───────────────────────────────────────────────────

    def create_chat(self, title: str, model: str, agent_mode: bool = False) -> int:
        now = time.time()
        with self._lock, self._conn() as c:
            cur = c.execute(
                "INSERT INTO chats (title, model, created_at, updated_at, agent_mode) "
                "VALUES (?, ?, ?, ?, ?)",
                (title, model, now, now, 1 if agent_mode else 0),
            )
            return cur.lastrowid

    def list_chats(self, limit: int = 200) -> List[Chat]:
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT id, title, model, created_at, updated_at, pinned, agent_mode "
                "FROM chats ORDER BY pinned DESC, updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [Chat(*r) for r in rows]

    def get_chat(self, chat_id: int) -> Optional[Chat]:
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT id, title, model, created_at, updated_at, pinned, agent_mode "
                "FROM chats WHERE id=?",
                (chat_id,),
            ).fetchone()
        return Chat(*row) if row else None

    def rename_chat(self, chat_id: int, title: str) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                "UPDATE chats SET title=?, updated_at=? WHERE id=?",
                (title, time.time(), chat_id),
            )

    def set_pinned(self, chat_id: int, pinned: bool) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE chats SET pinned=? WHERE id=?",
                      (1 if pinned else 0, chat_id))

    def set_agent_mode(self, chat_id: int, agent: bool) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE chats SET agent_mode=? WHERE id=?",
                      (1 if agent else 0, chat_id))

    def delete_chat(self, chat_id: int) -> None:
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM chats WHERE id=?", (chat_id,))

    def touch(self, chat_id: int) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE chats SET updated_at=? WHERE id=?",
                      (time.time(), chat_id))

    # ── messages ────────────────────────────────────────────────

    def add_message(
        self,
        chat_id: int,
        role: str,
        content: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> int:
        meta_s = json.dumps(meta) if meta else None
        with self._lock, self._conn() as c:
            cur = c.execute(
                "INSERT INTO messages (chat_id, role, content, ts, meta) "
                "VALUES (?, ?, ?, ?, ?)",
                (chat_id, role, content, time.time(), meta_s),
            )
            c.execute("UPDATE chats SET updated_at=? WHERE id=?",
                      (time.time(), chat_id))
            return cur.lastrowid

    def list_messages(self, chat_id: int) -> List[Message]:
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT id, chat_id, role, content, ts, meta "
                "FROM messages WHERE chat_id=? ORDER BY ts ASC, id ASC",
                (chat_id,),
            ).fetchall()
        out = []
        for r in rows:
            meta = json.loads(r[5]) if r[5] else {}
            out.append(Message(r[0], r[1], r[2], r[3], r[4], meta))
        return out

    def update_message(self, msg_id: int, content: str) -> None:
        """Used to overwrite the final assistant message after streaming completes."""
        with self._lock, self._conn() as c:
            c.execute("UPDATE messages SET content=? WHERE id=?", (content, msg_id))

    def search(self, query: str, limit: int = 50) -> List[Tuple[Chat, Message]]:
        """Substring search across messages.  Returns (chat, message) hits."""
        q = f"%{query.lower()}%"
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT m.id, m.chat_id, m.role, m.content, m.ts, m.meta, "
                "       c.title, c.model, c.created_at, c.updated_at, "
                "       c.pinned, c.agent_mode "
                "FROM messages m JOIN chats c ON c.id=m.chat_id "
                "WHERE LOWER(m.content) LIKE ? "
                "ORDER BY m.ts DESC LIMIT ?",
                (q, limit),
            ).fetchall()
        out = []
        for r in rows:
            meta = json.loads(r[5]) if r[5] else {}
            msg = Message(r[0], r[1], r[2], r[3], r[4], meta)
            chat = Chat(r[1], r[6], r[7], r[8], r[9], r[10], r[11])
            out.append((chat, msg))
        return out


# ═════════════════════════════════════════════════════════════════════
# TOOLS — file access, command exec, system info, network info
# ═════════════════════════════════════════════════════════════════════

def is_sensitive_path(path: str) -> bool:
    rp = os.path.realpath(os.path.expanduser(path))
    for p in SENSITIVE_PATHS:
        rp_norm = rp.rstrip("/")
        sp_norm = p.rstrip("/")
        if rp_norm == sp_norm or rp_norm.startswith(sp_norm + "/"):
            return True
    return False


def tool_read_file(path: str, max_bytes: int = 80_000) -> Dict[str, Any]:
    try:
        rp = os.path.expanduser(path)
        if not os.path.exists(rp):
            return {"ok": False, "error": f"no such file: {path}"}
        if os.path.isdir(rp):
            return {"ok": False, "error": f"is a directory: {path}"}
        size = os.path.getsize(rp)
        with open(rp, "rb") as f:
            raw = f.read(max_bytes)
        try:
            text = raw.decode("utf-8")
            kind = "text"
        except UnicodeDecodeError:
            text = raw[:1024].hex()
            kind = "binary (hex preview)"
        truncated = size > max_bytes
        return {
            "ok": True,
            "path": rp,
            "size": size,
            "kind": kind,
            "truncated": truncated,
            "content": text,
        }
    except PermissionError:
        return {"ok": False, "error": f"permission denied: {path}"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def tool_list_dir(path: str = ".") -> Dict[str, Any]:
    try:
        rp = os.path.expanduser(path)
        if not os.path.isdir(rp):
            return {"ok": False, "error": f"not a directory: {path}"}
        entries = []
        for name in sorted(os.listdir(rp)):
            full = os.path.join(rp, name)
            try:
                st = os.stat(full, follow_symlinks=False)
                is_dir = os.path.isdir(full)
                entries.append({
                    "name": name + ("/" if is_dir else ""),
                    "size": st.st_size,
                    "is_dir": is_dir,
                })
            except Exception:
                entries.append({"name": name, "size": -1, "is_dir": False})
        return {"ok": True, "path": rp, "entries": entries}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def tool_run_command(
    command: str,
    timeout: int = 30,
    cwd: Optional[str] = None,
) -> Dict[str, Any]:
    """Run a shell command.  Caller MUST have asked operator y/n already."""
    try:
        p = subprocess.run(
            command,
            shell=True,
            cwd=cwd or os.path.expanduser("~"),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            text=True,
            errors="replace",
        )
        out = (p.stdout or "")[:80_000]
        err = (p.stderr or "")[:20_000]
        return {
            "ok": True,
            "command": command,
            "rc": p.returncode,
            "stdout": out,
            "stderr": err,
            "truncated_stdout": len(p.stdout or "") > 80_000,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "command": command, "error": f"timeout after {timeout}s"}
    except Exception as e:
        return {"ok": False, "command": command,
                "error": f"{type(e).__name__}: {e}"}


def tool_system_info() -> Dict[str, Any]:
    """Quick read-only system snapshot."""
    info: Dict[str, Any] = {}
    try:
        info["hostname"] = socket.gethostname()
    except Exception:
        pass

    try:
        info["uname"] = " ".join(os.uname())
    except Exception:
        pass

    # /etc/os-release
    try:
        rel = {}
        with open("/etc/os-release") as f:
            for line in f:
                if "=" in line:
                    k, v = line.strip().split("=", 1)
                    rel[k] = v.strip('"')
        info["os"] = rel.get("PRETTY_NAME", "unknown")
    except Exception:
        pass

    # uptime
    try:
        with open("/proc/uptime") as f:
            up = float(f.read().split()[0])
        info["uptime_sec"] = int(up)
    except Exception:
        pass

    # memory
    try:
        meminfo = {}
        with open("/proc/meminfo") as f:
            for line in f:
                if ":" in line:
                    k, v = line.split(":", 1)
                    meminfo[k.strip()] = v.strip()
        info["mem_total"]     = meminfo.get("MemTotal")
        info["mem_available"] = meminfo.get("MemAvailable")
    except Exception:
        pass

    # load
    try:
        with open("/proc/loadavg") as f:
            info["load"] = f.read().strip()
    except Exception:
        pass

    # IP addresses (no exec)
    try:
        addrs = []
        for fam, _, _, _, sa in socket.getaddrinfo(
                socket.gethostname(), None):
            if fam == socket.AF_INET and sa[0] not in addrs:
                addrs.append(sa[0])
        info["local_ips"] = addrs
    except Exception:
        pass

    return info


# ═════════════════════════════════════════════════════════════════════
# SECURITY AUDIT — derived from ares.py, read-only, parallel
# ═════════════════════════════════════════════════════════════════════

SEVERITY_WEIGHTS = {
    "info": 0, "low": 1, "medium": 3, "high": 8, "critical": 20,
}


@dataclass
class Finding:
    check_id: str
    title: str
    severity: str           # info | low | medium | high | critical
    evidence: str
    fix_hint: str = ""
    raw: str = ""

    def __post_init__(self):
        if self.severity not in SEVERITY_WEIGHTS:
            self.severity = "info"
        if self.raw and len(self.raw) > 1500:
            self.raw = self.raw[:1500]


def _ro(argv: List[str], timeout: int = 12) -> Tuple[int, str, str]:
    try:
        env = {
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
            "HOME": os.path.expanduser("~"),
        }
        p = subprocess.run(
            argv, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout, env=env, text=True, errors="replace",
        )
        return (p.returncode, p.stdout or "", p.stderr or "")
    except subprocess.TimeoutExpired:
        return (124, "", "timeout")
    except FileNotFoundError:
        return (127, "", "not found")
    except Exception as e:
        return (1, "", f"err: {type(e).__name__}")


def _have(c: str) -> bool:
    return shutil.which(c) is not None


def _read(path: str, max_bytes: int = 100_000) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(max_bytes)
    except Exception:
        return None


# ── individual checks (subset of ares.py — fastest & most useful) ──

def check_firewall() -> List[Finding]:
    fs: List[Finding] = []
    fw_active = False
    if _have("ufw"):
        rc, out, _ = _ro(["ufw", "status"])
        if rc == 0 and out:
            if re.search(r'status:\s*active', out, re.I):
                fw_active = True
                fs.append(Finding("FW-001", "UFW firewall is active",
                                  "info", "ufw status: active", raw=out))
            elif re.search(r'status:\s*inactive', out, re.I):
                fs.append(Finding("FW-002", "UFW firewall is INACTIVE",
                                  "high", "ufw installed but not enabled",
                                  fix_hint="sudo ufw default deny incoming "
                                           "&& sudo ufw allow ssh "
                                           "&& sudo ufw enable",
                                  raw=out))
    if not fw_active and _have("iptables"):
        rc, out, _ = _ro(["iptables", "-S"])
        if rc == 0 and out:
            lines = [l for l in out.splitlines() if l.strip()]
            has_rules = any(
                re.search(r'-P\s+\w+\s+(DROP|REJECT)', l)
                or re.search(r'-A\s+\w+.*-j\s+(DROP|REJECT)', l)
                for l in lines)
            if has_rules:
                fw_active = True
                fs.append(Finding("FW-003", "iptables rules present",
                                  "info",
                                  f"{len(lines)} rule(s) configured",
                                  raw=out[:1200]))
    if not fw_active and _have("nft"):
        rc, out, _ = _ro(["nft", "list", "ruleset"])
        if rc == 0 and out.strip():
            fw_active = True
            fs.append(Finding("FW-005", "nftables rules present",
                              "info", "nftables ruleset loaded",
                              raw=out[:1200]))
    if not fw_active:
        fs.append(Finding("FW-006", "No firewall detected", "high",
                          "ufw / iptables / nft all report no active rules",
                          fix_hint="sudo apt install ufw && "
                                   "sudo ufw default deny incoming && "
                                   "sudo ufw allow ssh && sudo ufw enable"))
    return fs


def check_listening_ports() -> List[Finding]:
    fs: List[Finding] = []
    if not _have("ss"):
        return fs
    rc, out, _ = _ro(["ss", "-tlnH"])
    if rc != 0:
        return fs
    risky = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        local = parts[3]
        m = re.search(r':(\d+)$', local)
        if not m:
            continue
        port = int(m.group(1))
        # Listening on 0.0.0.0 or :: (any interface)
        if local.startswith(("0.0.0.0", "*", "[::]", "::")):
            risky.append((port, local))
    if risky:
        details = "\n".join(f"  :{p} on {a}" for p, a in risky[:15])
        sev = "high" if any(p in (21, 23, 2049, 5900) for p, _ in risky) else "medium"
        fs.append(Finding("NET-001",
                          f"{len(risky)} port(s) listening on all interfaces",
                          sev,
                          details,
                          fix_hint="Bind services to 127.0.0.1 where possible "
                                   "or restrict via firewall."))
    else:
        fs.append(Finding("NET-OK", "No public listening ports", "info",
                          "Only loopback or no TCP listeners."))
    return fs


def check_ssh_config() -> List[Finding]:
    fs: List[Finding] = []
    cfg = _read("/etc/ssh/sshd_config")
    if not cfg:
        return fs
    def grab(key: str) -> Optional[str]:
        for l in cfg.splitlines():
            ls = l.strip()
            if not ls or ls.startswith("#"):
                continue
            parts = ls.split(None, 1)
            if len(parts) == 2 and parts[0].lower() == key.lower():
                return parts[1].strip()
        return None
    pwd = (grab("PasswordAuthentication") or "yes").lower()
    root = (grab("PermitRootLogin") or "yes").lower()
    if pwd == "yes":
        fs.append(Finding("SSH-001", "SSH password auth enabled",
                          "medium",
                          "PasswordAuthentication=yes in sshd_config",
                          fix_hint="Disable once keys are deployed: "
                                   "PasswordAuthentication no"))
    if root in ("yes", "without-password"):
        fs.append(Finding("SSH-002",
                          f"PermitRootLogin = {root}",
                          "high",
                          "Direct root SSH login should be off",
                          fix_hint="PermitRootLogin no in sshd_config"))
    return fs


def check_pending_updates() -> List[Finding]:
    fs: List[Finding] = []
    if not _have("apt-get"):
        return fs
    rc, out, _ = _ro(["apt-get", "-s", "upgrade"], timeout=20)
    if rc != 0:
        return fs
    sec = 0
    for line in out.splitlines():
        if line.startswith("Inst ") and "security" in line.lower():
            sec += 1
    if sec > 0:
        fs.append(Finding("PATCH-001",
                          f"{sec} security update(s) pending",
                          "high" if sec > 5 else "medium",
                          f"{sec} packages need security updates",
                          fix_hint="sudo apt update && sudo apt upgrade"))
    return fs


def check_kernel() -> List[Finding]:
    fs: List[Finding] = []
    try:
        kr = os.uname().release
    except Exception:
        return fs
    m = re.match(r'(\d+)\.(\d+)', kr)
    if not m:
        return fs
    major, minor = int(m.group(1)), int(m.group(2))
    # Anything older than 5.15 is getting stale on modern distros
    if (major, minor) < (5, 15):
        fs.append(Finding("KERN-001",
                          f"Old kernel ({kr})",
                          "medium",
                          "Kernel predates 5.15 LTS",
                          fix_hint="sudo apt upgrade && reboot"))
    else:
        fs.append(Finding("KERN-OK", f"Kernel {kr}",
                          "info", "Modern kernel."))
    return fs


def check_failed_logins() -> List[Finding]:
    fs: List[Finding] = []
    if not _have("journalctl"):
        return fs
    rc, out, _ = _ro(
        ["journalctl", "_COMM=sshd", "--since", "24 hours ago",
         "--no-pager", "-q"], timeout=15)
    if rc != 0:
        return fs
    fails = sum(1 for l in out.splitlines() if "Failed password" in l)
    if fails > 50:
        fs.append(Finding("AUTH-001",
                          f"{fails} failed SSH logins in last 24h",
                          "high",
                          "Possible brute force",
                          fix_hint="Install fail2ban, restrict SSH "
                                   "to known IPs, switch to keys-only."))
    elif fails > 5:
        fs.append(Finding("AUTH-002",
                          f"{fails} failed SSH logins in last 24h",
                          "medium",
                          "Some noise on SSH.",
                          fix_hint="Consider fail2ban or keys-only auth."))
    return fs


def check_disk_encryption() -> List[Finding]:
    fs: List[Finding] = []
    if not _have("lsblk"):
        return fs
    rc, out, _ = _ro(["lsblk", "-o", "NAME,TYPE,FSTYPE,MOUNTPOINT"])
    if rc != 0:
        return fs
    has_crypt = "crypt" in out.lower()
    has_root_crypt = bool(re.search(r'crypt\s+\S+\s+/$', out, re.M))
    if has_root_crypt:
        fs.append(Finding("CRYPTO-001", "Root filesystem is encrypted",
                          "info", "LUKS detected on /"))
    elif has_crypt:
        fs.append(Finding("CRYPTO-002", "Some volumes encrypted, root is not",
                          "medium", "Encrypted partitions exist but root /  "
                          "appears unencrypted"))
    else:
        fs.append(Finding("CRYPTO-003",
                          "No disk encryption detected",
                          "medium",
                          "No LUKS volumes found via lsblk",
                          fix_hint="For a phone or laptop, full-disk "
                                   "encryption is strongly recommended."))
    return fs


def check_world_writable_home() -> List[Finding]:
    fs: List[Finding] = []
    home = os.path.expanduser("~")
    try:
        st = os.stat(home)
        if st.st_mode & 0o002:
            fs.append(Finding("PERM-001",
                              "Home directory is world-writable",
                              "high",
                              f"{home} mode allows other users to write",
                              fix_hint=f"chmod 700 {home}"))
    except Exception:
        pass
    return fs


def check_mac() -> List[Finding]:
    fs: List[Finding] = []
    if _have("aa-status"):
        rc, out, _ = _ro(["aa-status"])
        if rc == 0 and "profiles are loaded" in out:
            fs.append(Finding("MAC-001", "AppArmor is active",
                              "info", out.splitlines()[0] if out else ""))
        else:
            fs.append(Finding("MAC-002", "AppArmor present but not loaded",
                              "low", "aa-status reports no profiles"))
    elif _have("getenforce"):
        rc, out, _ = _ro(["getenforce"])
        if "Enforcing" in out:
            fs.append(Finding("MAC-003", "SELinux enforcing",
                              "info", "getenforce: Enforcing"))
        else:
            fs.append(Finding("MAC-004", f"SELinux mode: {out.strip()}",
                              "low", "SELinux not enforcing"))
    else:
        fs.append(Finding("MAC-005", "No MAC system detected",
                          "low",
                          "No AppArmor or SELinux on this host",
                          fix_hint="On Debian/Ubuntu derivatives, "
                                   "apparmor is usually default."))
    return fs


def check_shell_history() -> List[Finding]:
    fs: List[Finding] = []
    secrets_re = re.compile(
        r'(password|passwd|api[_-]?key|secret|token|bearer)\s*[=:]\s*\S+',
        re.I)
    home = Path.home()
    for hf in (".bash_history", ".zsh_history"):
        p = home / hf
        if not p.exists():
            continue
        try:
            data = p.read_text(errors="replace")
        except Exception:
            continue
        hits = secrets_re.findall(data)
        if hits:
            fs.append(Finding("HIST-001",
                              f"Possible secrets in {hf}",
                              "medium",
                              f"{len(hits)} suspicious line(s) found",
                              fix_hint=f"Review {p} for cleartext credentials"))
    return fs


AUDIT_CHECKS: List[Tuple[str, str, Callable[[], List[Finding]]]] = [
    ("FW",    "Firewall status",        check_firewall),
    ("NET",   "Listening ports",        check_listening_ports),
    ("SSH",   "SSH server config",      check_ssh_config),
    ("PATCH", "Pending sec updates",    check_pending_updates),
    ("KERN",  "Kernel age",             check_kernel),
    ("AUTH",  "Failed SSH logins",      check_failed_logins),
    ("CRYPT", "Disk encryption",        check_disk_encryption),
    ("PERM",  "Home dir perms",         check_world_writable_home),
    ("MAC",   "AppArmor / SELinux",     check_mac),
    ("HIST",  "Shell history secrets",  check_shell_history),
]


def run_security_audit(
    on_progress: Optional[Callable[[str, int, int], None]] = None,
) -> Dict[str, Any]:
    """Run all checks in parallel.  Returns dict with findings + score + grade."""
    t0 = time.time()
    all_findings: List[Finding] = []
    done = 0
    total = len(AUDIT_CHECKS)

    def _safe(fn):
        try:
            return fn() or []
        except Exception:
            return []

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        future_to = {
            ex.submit(_safe, fn): (cid, title)
            for cid, title, fn in AUDIT_CHECKS
        }
        for fut in concurrent.futures.as_completed(future_to, timeout=90):
            cid, title = future_to[fut]
            try:
                results = fut.result()
            except Exception:
                results = []
            all_findings.extend(results)
            done += 1
            if on_progress:
                on_progress(title, done, total)

    score = sum(SEVERITY_WEIGHTS[f.severity] for f in all_findings)
    if   score == 0:  grade = "A+"
    elif score <= 3:  grade = "A"
    elif score <= 8:  grade = "B"
    elif score <= 16: grade = "C"
    elif score <= 30: grade = "D"
    else:             grade = "F"

    return {
        "findings": all_findings,
        "score": score,
        "grade": grade,
        "elapsed": time.time() - t0,
    }


def format_audit_for_chat(audit: Dict[str, Any]) -> str:
    """Render the audit dict as markdown the model can summarise."""
    findings: List[Finding] = audit["findings"]
    sev_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    findings = sorted(findings, key=lambda f: (sev_rank[f.severity], f.check_id))
    lines = []
    lines.append(f"## Security audit — grade **{audit['grade']}** "
                 f"(score {audit['score']}, "
                 f"{audit['elapsed']:.1f}s)")
    lines.append("")
    counts = {}
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1
    summary_parts = [f"{n} {s}" for s, n in counts.items()]
    lines.append("Findings: " + ", ".join(summary_parts))
    lines.append("")
    for f in findings:
        tag = f"`{f.severity.upper():8s}`"
        lines.append(f"- {tag} **{f.title}** ({f.check_id})")
        if f.evidence:
            lines.append(f"  > {f.evidence}")
        if f.fix_hint:
            lines.append(f"  - fix: `{f.fix_hint}`")
    return "\n".join(lines)


# ═════════════════════════════════════════════════════════════════════
# NETWORK SCAN — best-effort, prefer nmap if available
# ═════════════════════════════════════════════════════════════════════

def _detect_local_cidr() -> Optional[str]:
    """Find the local subnet from `ip route`.  Returns 'a.b.c.d/24' or None."""
    if not _have("ip"):
        return None
    rc, out, _ = _ro(["ip", "-4", "route", "show", "default"])
    if rc != 0 or not out:
        return None
    m = re.search(r'dev\s+(\S+)', out)
    if not m:
        return None
    iface = m.group(1)
    rc, out, _ = _ro(["ip", "-4", "-o", "addr", "show", "dev", iface])
    if rc != 0:
        return None
    m = re.search(r'inet\s+(\d+\.\d+\.\d+\.\d+/\d+)', out)
    return m.group(1) if m else None


def run_network_scan(
    cidr: Optional[str] = None,
    on_progress: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """Discover live hosts on the local network."""
    t0 = time.time()
    target = cidr or _detect_local_cidr()
    if not target:
        return {"ok": False, "error": "Could not detect local subnet "
                                      "and none provided."}

    if on_progress:
        on_progress(f"scanning {target}...")

    hosts: List[Dict[str, Any]] = []

    if _have("nmap"):
        rc, out, err = _ro(["nmap", "-sn", "-T4", "-n", target], timeout=60)
        if rc == 0:
            cur = None
            for line in out.splitlines():
                m = re.match(r'Nmap scan report for (\S+)', line)
                if m:
                    if cur:
                        hosts.append(cur)
                    cur = {"ip": m.group(1), "mac": None, "vendor": None}
                m = re.match(r'MAC Address: (\S+)\s+\((.*)\)', line)
                if m and cur:
                    cur["mac"] = m.group(1)
                    cur["vendor"] = m.group(2)
            if cur:
                hosts.append(cur)
        else:
            return {"ok": False, "error": f"nmap failed: {err.strip()}"}
    else:
        # Fallback: arp table only — no active discovery
        if on_progress:
            on_progress("nmap not installed — reading ARP table only")
        rc, out, _ = _ro(["ip", "neigh"])
        if rc == 0:
            for line in out.splitlines():
                m = re.match(
                    r'(\d+\.\d+\.\d+\.\d+).*lladdr\s+(\S+)', line)
                if m:
                    hosts.append({
                        "ip": m.group(1), "mac": m.group(2), "vendor": None,
                    })

    return {
        "ok": True,
        "target": target,
        "hosts": hosts,
        "elapsed": time.time() - t0,
        "scanner": "nmap" if _have("nmap") else "ip-neigh",
    }


def format_scan_for_chat(scan: Dict[str, Any]) -> str:
    if not scan.get("ok"):
        return f"Network scan failed: {scan.get('error')}"
    lines = [f"## Network scan — {scan['target']} "
             f"({len(scan['hosts'])} hosts, "
             f"{scan['elapsed']:.1f}s, via {scan['scanner']})", ""]
    if not scan["hosts"]:
        lines.append("_No live hosts found._")
    else:
        lines.append("| IP | MAC | Vendor |")
        lines.append("|---|---|---|")
        for h in scan["hosts"]:
            lines.append(f"| {h['ip']} | {h.get('mac') or '—'} "
                         f"| {h.get('vendor') or '—'} |")
    return "\n".join(lines)


# ═════════════════════════════════════════════════════════════════════
# OFFLINE DETECTION
# ═════════════════════════════════════════════════════════════════════

def is_online(timeout: float = 1.0) -> bool:
    """Cheap reachability check.  Used purely to gate UI affordances."""
    for host, port in (("1.1.1.1", 53), ("8.8.8.8", 53)):
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except Exception:
            continue
    return False


# ═════════════════════════════════════════════════════════════════════
# TOOL CALL PARSING — extract <tool name="..."> tags from model output
# ═════════════════════════════════════════════════════════════════════

TOOL_TAG_RE = re.compile(
    r'<tool\s+name="([a-zA-Z_]+)"\s*>(.*?)</tool>',
    re.DOTALL,
)


@dataclass
class ToolCall:
    name: str
    args: Dict[str, Any]
    raw: str


def parse_tool_calls(text: str) -> List[ToolCall]:
    calls = []
    for m in TOOL_TAG_RE.finditer(text):
        name = m.group(1)
        body = m.group(2).strip()
        try:
            args = json.loads(body) if body else {}
        except json.JSONDecodeError:
            args = {"_raw": body}
        calls.append(ToolCall(name=name, args=args, raw=m.group(0)))
    return calls


def strip_tool_calls(text: str) -> str:
    """Remove tool-call XML so it doesn't pollute the chat bubble."""
    return TOOL_TAG_RE.sub("", text).strip()
