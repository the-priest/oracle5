"""
mcp.py — a minimal Model Context Protocol (MCP) client for Kali.

MCP is the open standard (Anthropic, Nov 2024; now a Linux Foundation project)
that lets an LLM host discover and call tools exposed by external "servers" over
a JSON-RPC 2.0 channel.  For Kali this is force-multiplying: an enormous
ecosystem of security MCP servers already exists (nmap, sqlmap, ffuf, nuclei,
ZAP, …), and wiring them in once gives the model all of them without a bespoke
wrapper per tool.

This module speaks the **stdio transport**: it launches a configured server as a
subprocess and exchanges newline-delimited JSON-RPC messages over its
stdin/stdout (the transport pentestMCP, cyproxio/mcp-for-security, and most
local security servers use).  It performs the initialize handshake, lists the
server's tools, and calls them.

SECURITY — read this before enabling.  MCP deliberately inverts the usual trust
model: a server can execute actions for the client, and the NSA's 2026 guidance
plus real CVEs (e.g. CVE-2025-49596, RCE via an unauthenticated MCP server)
treat MCP as a genuine remote-code-execution surface.  So this client is
deliberately conservative:

  • OFF by default (`mcp_enabled` is False) and does nothing until the operator
    explicitly configures a server in settings.
  • Every tool call's string arguments are screened with kali_safety: an
    argument that resolves to a catastrophic command (disk wipe, recursive root
    delete, …) is REFUSED before it ever reaches the server.
  • Every call is recorded to the evidence ledger, same as a local command.
  • Server tool names are namespaced ``mcp__<server>__<tool>`` so they can never
    shadow or be confused with Kali's own built-in tools.

It is pure stdlib (subprocess, json, threading, time) and imports kali_safety
for the screen; it does not import the GTK layer.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from typing import Any, Callable, Dict, List, Optional

# kali_safety lives one package up (kali_safety.py at repo root).  Import it
# defensively so a layout where it's not importable just disables screening's
# hard-refuse (we then fall back to refusing nothing extra, but still log).
try:
    import kali_safety as _safety
except Exception:  # pragma: no cover
    try:
        from .. import kali_safety as _safety  # type: ignore
    except Exception:
        _safety = None  # type: ignore

_PROTOCOL_VERSION = "2025-06-18"   # MCP protocol revision this client targets
_CLIENT_INFO = {"name": "kali", "version": "3.2.0"}
_DEFAULT_TIMEOUT = 60


class MCPError(Exception):
    pass


class MCPServer:
    """One stdio MCP server connection: launch, handshake, list, call.

    config keys:
      name     — short id used in the namespaced tool name
      command  — executable to launch (e.g. "docker", "uvx", "python3")
      args     — list of arguments
      env      — optional dict of extra environment variables
      cwd      — optional working directory
    """

    def __init__(self, config: Dict[str, Any]):
        self.name = str(config.get("name") or "server").strip() or "server"
        self.command = config.get("command")
        self.args = list(config.get("args") or [])
        self.env = dict(config.get("env") or {})
        self.cwd = config.get("cwd") or None
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.RLock()
        self._next_id = 0
        self._tools: List[Dict[str, Any]] = []
        self._initialized = False

    # ── lifecycle ─────────────────────────────────────────────────────
    def start(self, timeout: int = _DEFAULT_TIMEOUT) -> None:
        if self._proc and self._proc.poll() is None:
            return
        if not self.command:
            raise MCPError(f"server '{self.name}': no command configured")
        env = dict(os.environ)
        env.update({str(k): str(v) for k, v in self.env.items()})
        try:
            self._proc = subprocess.Popen(
                [self.command, *self.args],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, env=env, cwd=self.cwd,
                text=True, bufsize=1)
        except FileNotFoundError:
            raise MCPError(f"server '{self.name}': command not found: {self.command}")
        except Exception as e:
            raise MCPError(f"server '{self.name}': failed to launch: {e}")
        self._handshake(timeout)

    def stop(self) -> None:
        with self._lock:
            p = self._proc
            self._proc = None
            self._initialized = False
        if not p:
            return
        try:
            p.stdin and p.stdin.close()
        except Exception:
            pass
        try:
            p.terminate()
            p.wait(timeout=5)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass

    def is_alive(self) -> bool:
        return bool(self._proc and self._proc.poll() is None)

    # ── JSON-RPC plumbing ─────────────────────────────────────────────
    def _send(self, obj: Dict[str, Any]) -> None:
        if not (self._proc and self._proc.stdin):
            raise MCPError(f"server '{self.name}': not running")
        line = json.dumps(obj, ensure_ascii=False) + "\n"
        try:
            self._proc.stdin.write(line)
            self._proc.stdin.flush()
        except Exception as e:
            raise MCPError(f"server '{self.name}': write failed: {e}")

    def _read_message(self, timeout: int) -> Dict[str, Any]:
        """Read one newline-delimited JSON message from the server's stdout,
        with a wall-clock timeout enforced via a reader thread (stdio has no
        portable read-with-timeout)."""
        if not (self._proc and self._proc.stdout):
            raise MCPError(f"server '{self.name}': not running")
        result: Dict[str, Any] = {}
        holder: List[Optional[str]] = [None]

        def _rdr():
            try:
                holder[0] = self._proc.stdout.readline()
            except Exception:
                holder[0] = None

        t = threading.Thread(target=_rdr, daemon=True)
        t.start()
        t.join(timeout)
        if t.is_alive():
            raise MCPError(f"server '{self.name}': timed out waiting for reply")
        line = holder[0]
        if not line:
            err = ""
            try:
                if self._proc and self._proc.stderr:
                    err = self._proc.stderr.readline() or ""
            except Exception:
                pass
            raise MCPError(f"server '{self.name}': closed the connection {err}".strip())
        try:
            return json.loads(line)
        except Exception as e:
            raise MCPError(f"server '{self.name}': bad JSON from server: {e}")

    def _request(self, method: str, params: Optional[Dict[str, Any]] = None,
                 timeout: int = _DEFAULT_TIMEOUT) -> Any:
        """Send a request and read replies until the matching id comes back,
        skipping any interleaved notifications/log messages."""
        with self._lock:
            self._next_id += 1
            rid = self._next_id
            self._send({"jsonrpc": "2.0", "id": rid, "method": method,
                        "params": params or {}})
            deadline = time.time() + timeout
            while True:
                remaining = max(1, int(deadline - time.time()))
                msg = self._read_message(remaining)
                if msg.get("id") == rid:
                    if "error" in msg:
                        e = msg["error"]
                        raise MCPError(f"server '{self.name}': {method} error: "
                                       f"{e.get('message', e)}")
                    return msg.get("result")
                # else: a notification or a reply to another id — ignore.

    def _notify(self, method: str, params: Optional[Dict[str, Any]] = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def _handshake(self, timeout: int) -> None:
        self._request("initialize", {
            "protocolVersion": _PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": _CLIENT_INFO,
        }, timeout=timeout)
        self._notify("notifications/initialized")
        self._initialized = True

    # ── tools ─────────────────────────────────────────────────────────
    def list_tools(self, timeout: int = _DEFAULT_TIMEOUT) -> List[Dict[str, Any]]:
        if not self._initialized:
            self.start(timeout)
        result = self._request("tools/list", {}, timeout=timeout) or {}
        self._tools = list(result.get("tools") or [])
        return self._tools

    def call_tool(self, tool: str, arguments: Dict[str, Any],
                  timeout: int = _DEFAULT_TIMEOUT) -> Dict[str, Any]:
        if not self._initialized:
            self.start(timeout)
        result = self._request("tools/call",
                               {"name": tool, "arguments": arguments or {}},
                               timeout=timeout)
        return result or {}


# ── safety screen ─────────────────────────────────────────────────────
def _arguments_are_catastrophic(arguments: Dict[str, Any]) -> Optional[str]:
    """If any string argument resolves to a catastrophic command, return it so
    the caller can refuse.  This is the same hard floor Kali applies to its own
    `run` — an MCP server is untrusted, so a tool argument that says
    `rm -rf /` (however obfuscated) is blocked before it leaves the process."""
    if _safety is None:
        return None

    def _walk(v: Any) -> Optional[str]:
        if isinstance(v, str):
            if _safety.is_catastrophic_command(v):
                return v
        elif isinstance(v, dict):
            for x in v.values():
                hit = _walk(x)
                if hit:
                    return hit
        elif isinstance(v, (list, tuple)):
            for x in v:
                hit = _walk(x)
                if hit:
                    return hit
        return None

    return _walk(arguments or {})


def _flatten_content(result: Dict[str, Any]) -> str:
    """Turn an MCP tools/call result into readable text for the model."""
    if not isinstance(result, dict):
        return str(result)
    parts: List[str] = []
    for block in (result.get("content") or []):
        if isinstance(block, dict):
            if block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif "text" in block:
                parts.append(str(block["text"]))
            else:
                parts.append(json.dumps(block, ensure_ascii=False))
        else:
            parts.append(str(block))
    text = "\n".join(p for p in parts if p)
    if result.get("isError"):
        text = "[tool reported an error]\n" + text
    return text or "(no output)"


class MCPManager:
    """Owns the configured servers and exposes their tools to Kali, namespaced
    and safety-screened.  ``ledger`` (optional) is Kali's EvidenceLedger; if
    provided, every MCP call is recorded like a local command."""

    def __init__(self, servers_config: List[Dict[str, Any]],
                 ledger: Any = None):
        self.servers: Dict[str, MCPServer] = {}
        self.ledger = ledger
        for cfg in (servers_config or []):
            try:
                srv = MCPServer(cfg)
                self.servers[srv.name] = srv
            except Exception:
                continue

    def discover(self) -> Dict[str, List[Dict[str, Any]]]:
        """Start each server and list its tools.  Failures are reported per
        server rather than aborting the whole discovery."""
        out: Dict[str, List[Dict[str, Any]]] = {}
        for name, srv in self.servers.items():
            try:
                out[name] = srv.list_tools()
            except Exception as e:
                out[name] = [{"_error": str(e)}]
        return out

    def tool_specs(self) -> List[Dict[str, Any]]:
        """Namespaced specs (name/description/schema) for the model's tool list."""
        specs: List[Dict[str, Any]] = []
        for name, srv in self.servers.items():
            for t in srv._tools:
                if "_error" in t:
                    continue
                specs.append({
                    "name": f"mcp__{name}__{t.get('name')}",
                    "description": t.get("description", ""),
                    "schema": t.get("inputSchema", {}),
                })
        return specs

    def call(self, namespaced_tool: str, arguments: Dict[str, Any],
             timeout: int = _DEFAULT_TIMEOUT) -> str:
        """Call mcp__<server>__<tool> after the safety screen, log it, return
        readable text."""
        try:
            _, server_name, tool = namespaced_tool.split("__", 2)
        except ValueError:
            return f"error: malformed MCP tool name {namespaced_tool!r}"
        srv = self.servers.get(server_name)
        if not srv:
            return f"error: unknown MCP server {server_name!r}"

        bad = _arguments_are_catastrophic(arguments)
        if bad is not None:
            return (f"refused: MCP tool '{tool}' was called with an argument "
                    f"that resolves to a system-destroying command "
                    f"({bad!r}); blocked by Kali's safety floor.")

        t0 = time.time()
        try:
            result = srv.call_tool(tool, arguments, timeout=timeout)
            text = _flatten_content(result)
            ok = not result.get("isError", False)
            err = None
        except Exception as e:
            text = f"error: {e}"
            ok = False
            err = str(e)

        if self.ledger is not None:
            try:
                self.ledger.record(
                    f"mcp:{server_name}/{tool} {json.dumps(arguments, ensure_ascii=False)}",
                    "MCP tool call",
                    {"ok": ok, "rc": 0 if ok else 1,
                     "stdout": text if ok else "", "stderr": "" if ok else text,
                     "error": err,
                     "duration_ms": int((time.time() - t0) * 1000)},
                    kind="mcp")
            except Exception:
                pass
        return text

    def shutdown(self) -> None:
        for srv in self.servers.values():
            try:
                srv.stop()
            except Exception:
                pass
