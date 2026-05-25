#!/usr/bin/env python3
"""
kali_core — non-UI logic for Kali.

  · Backend abstraction (Groq primary, Ollama fallback when offline)
  · Streaming chat
  · SQLite chat history
  · Full system tools: file r, command exec, system info, package
    management, service control, downloads watcher, journal tail,
    process list, network state
  · Security audit (parallel, read-only)
  · Local network scan
  · Background watcher daemon (optional)
"""

from __future__ import annotations

import os
import re
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
from typing import (List, Dict, Tuple, Optional, Any, Callable,
                    Protocol)

try:
    from groq import Groq
    GROQ_LIB_OK = True
except ImportError:
    GROQ_LIB_OK = False
    Groq = None  # type: ignore


# ═════════════════════════════════════════════════════════════════════
# PATHS & CONSTANTS
# ═════════════════════════════════════════════════════════════════════

HOME              = Path.home()
DATA_DIR          = HOME / ".local" / "share" / "kali"
CONFIG_DIR        = HOME / ".config" / "kali"
CHATS_DB          = DATA_DIR / "chats.db"
SETTINGS_JSON     = CONFIG_DIR / "settings.json"
LOG_FILE          = DATA_DIR / "kali.log"
WATCHER_STATE     = DATA_DIR / "watcher.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

OLLAMA_HOST       = "http://127.0.0.1:11434"
HTTP_TIMEOUT_S    = 600
HEALTH_TIMEOUT_S  = 1.5

GROQ_DEFAULT_MODEL = "llama-3.3-70b-versatile"
# Ordered roughly by capability (biggest first).  Each model on Groq has
# its OWN rate-limit bucket — when one hits a 429, the chain moves to
# the next so testing/iteration doesn't grind to a halt.  Verified
# against the current GroqCloud catalogue (May 2026).
GROQ_FALLBACK_CHAIN = [
    "llama-3.3-70b-versatile",                       # default; 70B Llama, best quality
    "openai/gpt-oss-120b",                           # 120B OpenAI open-weight
    "meta-llama/llama-4-scout-17b-16e-instruct",     # newest Llama 4, fast
    "qwen/qwen3-32b",                                # different family, strong reasoning
    "openai/gpt-oss-20b",                            # 20B, very fast
    "llama-3.1-8b-instant",                          # last resort, 560 t/s
]
OLLAMA_DEFAULT_MODEL = "llama3.2:1b"

# ─────────────────────────────────────────────────────────────────────
# CLOUD PROVIDER REGISTRY
#
# Every cloud provider below SiliconFlow speaks the OpenAI-compatible
# /chat/completions schema, so one generic backend (OpenAICompatBackend)
# drives all of them — no extra Python dependencies, just urllib + SSE.
# Groq keeps its own library-backed backend (it's what the operator
# already relies on) but is registered here too so the UI treats every
# provider uniformly.
#
# Each chain is ordered BIGGEST/BEST FIRST.  The chain is both the
# default model (chain[0]) and the in-provider fallback order: if the
# selected model is rate-limited or unavailable, the backend walks down
# the chain before giving up.  Model IDs drift over time — every
# provider also supports live discovery (GET /models) and the model
# field in Settings is editable, so a stale ID here is never fatal.
# Verified against each provider's docs, May 2026.
# ─────────────────────────────────────────────────────────────────────

SILICONFLOW_CHAIN = [
    "deepseek-ai/DeepSeek-V3",
    "Qwen/Qwen3-235B-A22B-Instruct",
    "moonshotai/Kimi-K2-Instruct",
    "deepseek-ai/DeepSeek-R1",
    "Qwen/Qwen3-32B",
    "Qwen/Qwen2.5-72B-Instruct",
]

NOVITA_CHAIN = [
    "qwen/qwen3-coder-480b-a35b-instruct",
    "deepseek/deepseek-v3",
    "openai/gpt-oss-120b",
    "moonshotai/kimi-k2.5",
    "meta-llama/llama-3.3-70b-instruct",
]

GITHUB_CHAIN = [
    "openai/gpt-4.1",
    "openai/gpt-4o",
    "deepseek/DeepSeek-R1",
    "meta/Llama-3.3-70B-Instruct",
    "openai/gpt-4.1-mini",
    "openai/gpt-4o-mini",
]

GOOGLE_CHAIN = [
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
]


@dataclass
class ProviderSpec:
    """Static description of a cloud provider.  Drives both routing and
    the Settings UI — add an entry here and a provider appears wired-up
    everywhere with no other edits."""
    key: str              # internal id and settings prefix, e.g. "groq"
    label: str            # UI display name, e.g. "Groq"
    blurb: str            # one-line description for Settings
    base_url: str         # OpenAI-compatible API root (no trailing slash)
    chain: List[str]      # models, biggest/best first
    key_url: str          # where the operator gets a key
    engine: str = "openai_compat"   # "openai_compat" or "groq"
    extra_headers: Optional[Dict[str, str]] = None

    @property
    def default_model(self) -> str:
        return self.chain[0] if self.chain else ""


# Ordered: Groq first (the established default), then the rest.
PROVIDERS: List[ProviderSpec] = [
    ProviderSpec(
        key="groq", label="Groq", engine="groq",
        blurb="Fast cloud inference. Free key at console.groq.com.",
        base_url="https://api.groq.com/openai/v1",
        chain=list(GROQ_FALLBACK_CHAIN),
        key_url="https://console.groq.com/keys"),
    ProviderSpec(
        key="siliconflow", label="SiliconFlow",
        blurb="OpenAI-compatible. Big open models (DeepSeek, Qwen, Kimi).",
        base_url="https://api.siliconflow.com/v1",
        chain=SILICONFLOW_CHAIN,
        key_url="https://cloud.siliconflow.com/account/ak"),
    ProviderSpec(
        key="novita", label="Novita AI",
        blurb="OpenAI-compatible. Cheap GPU inference, many open models.",
        base_url="https://api.novita.ai/v3/openai",
        chain=NOVITA_CHAIN,
        key_url="https://novita.ai/settings/key-management"),
    ProviderSpec(
        key="github", label="GitHub Models",
        blurb="Free tier. Use a GitHub PAT with the models:read scope.",
        base_url="https://models.github.ai/inference",
        chain=GITHUB_CHAIN,
        key_url="https://github.com/settings/personal-access-tokens"),
    ProviderSpec(
        key="google", label="Google AI Studio",
        blurb="Gemini models. Free key at aistudio.google.com.",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        chain=GOOGLE_CHAIN,
        key_url="https://aistudio.google.com/apikey"),
]

PROVIDERS_BY_KEY: Dict[str, ProviderSpec] = {p.key: p for p in PROVIDERS}
CLOUD_PROVIDER_KEYS = [p.key for p in PROVIDERS]

# Paths that need explicit operator confirmation even in agent mode
SENSITIVE_PATHS = (
    "/etc/shadow", "/etc/gshadow", "/etc/sudoers",
    "/root/.ssh", str(HOME / ".ssh"),
    str(HOME / ".gnupg"),
    str(HOME / ".aws"), str(HOME / ".config" / "gh"),
    str(HOME / ".password-store"),
    "/proc/kcore", "/proc/kmem",
)


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
    # ── Provider routing ──
    # Which cloud provider to use when online + configured.  Falls back
    # to Ollama (local) when this provider has no key, is offline, or
    # errors.  "prefer_cloud" off = always use local Ollama.
    "active_provider": "groq",
    "prefer_cloud": True,

    # Per-provider API key + selected model.  One pair per registered
    # provider; populated from DEFAULT_SETTINGS so a fresh install has
    # every field present.  (Built programmatically below.)

    # ── Local fallback ──
    "ollama_model": OLLAMA_DEFAULT_MODEL,

    # Generation
    "temperature": 0.7,
    "top_p": 0.9,
    "num_ctx": 4096,
    "max_tokens": 2048,

    # Behaviour
    "system_prompt": "",
    "auto_start_ollama": True,
    "stop_ollama_on_quit": True,
    "agent_mode_default": True,        # Kali defaults to agent on
    "confirm_all_commands": True,

    # Watcher
    "watcher_enabled": False,
    "watcher_check_updates": True,
    "watcher_check_downloads": True,
    "watcher_check_journal": False,
    "watcher_interval_minutes": 60,

    # UI
    "theme": "mocha",
    "ui_scale": 0,  # 0 = auto-detect; manual values 0.3 to 3.0
    "show_token_count": False,
    "show_provider_pill": True,
}

# Add a key + model slot for every registered provider so the schema is
# always complete (e.g. "groq_api_key", "groq_model", "novita_api_key"…).
for _p in PROVIDERS:
    DEFAULT_SETTINGS.setdefault(f"{_p.key}_api_key", "")
    DEFAULT_SETTINGS.setdefault(f"{_p.key}_model", _p.default_model)


def load_settings() -> Dict[str, Any]:
    if SETTINGS_JSON.exists():
        try:
            with open(SETTINGS_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
            merged = dict(DEFAULT_SETTINGS)
            merged.update(data)
            _migrate_settings(merged, data)
            return merged
        except Exception:
            pass
    return dict(DEFAULT_SETTINGS)


def _migrate_settings(merged: Dict[str, Any], raw: Dict[str, Any]) -> None:
    """In-place upgrade of settings loaded from an older Kali/Oracle
    install so adding multi-provider support never silently drops the
    operator's existing Groq config."""
    # Old single-provider builds used `prefer_groq`; the new schema uses
    # `prefer_cloud` + `active_provider`.  Honour the old value if the
    # new one wasn't explicitly written.
    if "prefer_cloud" not in raw and "prefer_groq" in raw:
        merged["prefer_cloud"] = bool(raw.get("prefer_groq"))
    # If a Groq key exists but no provider was chosen, keep Groq active.
    if "active_provider" not in raw:
        merged["active_provider"] = "groq"
    # Guard against an active_provider that no longer exists in the
    # registry (e.g. a renamed/removed provider) — fall back to groq.
    if merged.get("active_provider") not in PROVIDERS_BY_KEY:
        merged["active_provider"] = "groq"


def save_settings(settings: Dict[str, Any]) -> None:
    # Atomic write: temp file in same directory, then os.replace.  Without
    # this, a crash mid-write would leave settings.json truncated or empty
    # and the next load would silently fall back to defaults — wiping the
    # operator's Groq API key, ollama model selection, etc.
    try:
        tmp = SETTINGS_JSON.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
        os.replace(tmp, SETTINGS_JSON)
    except Exception as e:
        log(f"save_settings error: {e}")


# ═════════════════════════════════════════════════════════════════════
# OFFLINE DETECTION
# ═════════════════════════════════════════════════════════════════════

_online_cache = {"value": False, "ts": 0.0}
_online_lock = threading.Lock()


def is_online(timeout: float = 1.0, max_age: float = 8.0) -> bool:
    """Cached reachability check.  Refreshes every max_age seconds."""
    now = time.time()
    with _online_lock:
        if now - _online_cache["ts"] < max_age:
            return bool(_online_cache["value"])
    result = False
    for host, port in (("1.1.1.1", 53), ("8.8.8.8", 53)):
        try:
            with socket.create_connection((host, port), timeout=timeout):
                result = True
                break
        except Exception:
            continue
    with _online_lock:
        _online_cache["value"] = result
        _online_cache["ts"] = now
    return result


# ═════════════════════════════════════════════════════════════════════
# BACKENDS — Groq and Ollama, with a router on top
# ═════════════════════════════════════════════════════════════════════

class Backend(Protocol):
    name: str
    def is_available(self) -> bool: ...
    def list_models(self) -> List[Dict[str, Any]]: ...
    def stream_chat(self, model: str, messages: List[Dict[str, str]],
                    on_token: Callable[[str], None],
                    on_done: Callable[[Dict[str, Any]], None],
                    on_error: Callable[[str], None],
                    options: Optional[Dict[str, Any]] = None,
                    cancel_event: Optional[threading.Event] = None) -> None: ...


class OllamaBackend:
    name = "ollama"

    def __init__(self):
        self._proc: Optional[subprocess.Popen] = None
        self._started_by_us = False
        # Cache the most recent health probe so the UI thread doesn't
        # block 1.5s on every send when ollama is unreachable.
        self._running_cache = {"value": False, "ts": 0.0}
        self._running_cache_lock = threading.Lock()

    def is_running(self, max_age: float = 4.0) -> bool:
        """Cached health check.  Re-probes at most every max_age seconds."""
        now = time.time()
        with self._running_cache_lock:
            if now - self._running_cache["ts"] < max_age:
                return bool(self._running_cache["value"])
        try:
            req = urllib.request.Request(f"{OLLAMA_HOST}/api/version")
            with urllib.request.urlopen(req, timeout=HEALTH_TIMEOUT_S) as r:
                value = (r.status == 200)
        except Exception:
            value = False
        with self._running_cache_lock:
            self._running_cache["value"] = value
            self._running_cache["ts"] = now
        return value

    def _invalidate_running_cache(self):
        with self._running_cache_lock:
            self._running_cache["ts"] = 0.0

    def is_available(self) -> bool:
        return self.is_running()

    def start_serve(self) -> bool:
        if self.is_running():
            return True
        if not shutil.which("ollama"):
            return False
        try:
            self._proc = subprocess.Popen(
                ["ollama", "serve"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            self._started_by_us = True
            for _ in range(20):
                time.sleep(0.25)
                self._invalidate_running_cache()
                if self.is_running():
                    return True
            return False
        except Exception as e:
            log(f"ollama start_serve error: {e}")
            return False

    def stop_serve(self) -> None:
        # Best-effort: stop any kali-managed systemd unit too
        for unit in ("kali-ollama.service", "oracle-ollama.service"):
            try:
                subprocess.run(
                    ["systemctl", "--user", "stop", unit],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=4)
            except Exception:
                pass

        # Terminate the subprocess we spawned (if any)
        if self._started_by_us and self._proc is not None:
            try:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
            except Exception:
                pass
            finally:
                self._proc = None
                self._started_by_us = False

        # Also kill any orphaned `ollama serve` left over from a previous
        # Kali run that quit uncleanly.  Scoped to OUR user so it can't
        # hit a system-level ollama running as another user.
        try:
            subprocess.run(
                ["pkill", "-u", os.environ.get("USER", ""), "-f",
                 "ollama serve"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=4)
        except Exception:
            pass
        self._invalidate_running_cache()

    def list_models(self) -> List[Dict[str, Any]]:
        try:
            req = urllib.request.Request(f"{OLLAMA_HOST}/api/tags")
            with urllib.request.urlopen(req, timeout=5) as r:
                data = json.loads(r.read())
            return sorted(data.get("models", []),
                          key=lambda m: m.get("name", ""))
        except Exception:
            return []

    def version(self) -> Optional[str]:
        try:
            req = urllib.request.Request(f"{OLLAMA_HOST}/api/version")
            with urllib.request.urlopen(req, timeout=HEALTH_TIMEOUT_S) as r:
                return json.loads(r.read()).get("version")
        except Exception:
            return None

    def stream_chat(self, model, messages, on_token, on_done, on_error,
                    options=None, cancel_event=None) -> None:
        payload = {"model": model, "messages": messages, "stream": True}
        if options:
            # Translate our generic option names to Ollama's.  Critically,
            # Ollama caps generation length with `num_predict`, NOT
            # `max_tokens` — passing max_tokens did nothing, so the local
            # model ignored the user's token limit entirely.
            ol_opts: Dict[str, Any] = {}
            for src, dst in (("temperature", "temperature"),
                             ("top_p", "top_p"),
                             ("top_k", "top_k"),
                             ("num_ctx", "num_ctx"),
                             ("max_tokens", "num_predict"),
                             ("num_predict", "num_predict")):
                if options.get(src) is not None:
                    ol_opts[dst] = options[src]
            if ol_opts:
                payload["options"] = ol_opts
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                f"{OLLAMA_HOST}/api/chat",
                data=data,
                headers={"Content-Type": "application/json"})
            parts: List[str] = []
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as r:
                for line in r:
                    if cancel_event and cancel_event.is_set():
                        on_done({"cancelled": True, "text": "".join(parts),
                                 "backend": "ollama"})
                        return
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except Exception:
                        continue
                    tok = chunk.get("message", {}).get("content", "")
                    if tok:
                        parts.append(tok)
                        on_token(tok)
                    if chunk.get("done"):
                        on_done({
                            "text": "".join(parts),
                            "backend": "ollama",
                            "model": model,
                            "eval_count": chunk.get("eval_count"),
                            "cancelled": False,
                        })
                        return
            on_done({"text": "".join(parts), "backend": "ollama",
                     "cancelled": False})
        except urllib.error.URLError as e:
            on_error(f"ollama connection: {e.reason}")
        except Exception as e:
            on_error(f"ollama {type(e).__name__}: {e}")


class GroqBackend:
    name = "groq"

    def __init__(self, api_key: str = "",
                 fallback_chain: List[str] = None):
        self.api_key = api_key
        self._client = None
        self.fallback_chain = fallback_chain or list(GROQ_FALLBACK_CHAIN)
        self._build_client()

    def _build_client(self):
        if not GROQ_LIB_OK or not self.api_key:
            self._client = None
            return
        try:
            self._client = Groq(api_key=self.api_key)
        except Exception as e:
            log(f"groq client error: {e}")
            self._client = None

    def set_api_key(self, key: str) -> None:
        self.api_key = key
        self._build_client()

    def is_available(self) -> bool:
        return GROQ_LIB_OK and bool(self._client) and is_online()

    def list_models(self) -> List[Dict[str, Any]]:
        return [{"name": m} for m in self.fallback_chain]

    def stream_chat(self, model, messages, on_token, on_done, on_error,
                    options=None, cancel_event=None) -> None:
        if not self._client:
            on_error("groq not configured")
            return
        opts = options or {}
        temperature = opts.get("temperature", 0.7)
        top_p = opts.get("top_p", 0.9)
        max_tokens = opts.get("max_tokens", 2048)

        # Build a model order: requested first, then any fallbacks not equal
        order = [model] + [m for m in self.fallback_chain if m != model]
        last_err = None
        any_tokens_emitted = False  # see below

        for attempt_model in order:
            if cancel_event and cancel_event.is_set():
                on_done({"cancelled": True, "text": "", "backend": "groq"})
                return
            try:
                resp = self._client.chat.completions.create(
                    model=attempt_model,
                    messages=messages,
                    temperature=temperature,
                    top_p=top_p,
                    max_tokens=max_tokens,
                    stream=True,
                )
                parts: List[str] = []
                for chunk in resp:
                    if cancel_event and cancel_event.is_set():
                        on_done({"cancelled": True,
                                 "text": "".join(parts),
                                 "backend": "groq",
                                 "model": attempt_model})
                        return
                    delta = chunk.choices[0].delta
                    tok = getattr(delta, "content", None) or ""
                    if tok:
                        parts.append(tok)
                        any_tokens_emitted = True
                        on_token(tok)
                on_done({
                    "text": "".join(parts),
                    "backend": "groq",
                    "model": attempt_model,
                    "cancelled": False,
                })
                return
            except Exception as e:
                last_err = e
                msg = str(e).lower()

                # If we've already emitted tokens to the UI, falling back
                # to a different model would APPEND its tokens after the
                # partial output from this one — the user would see a
                # garbled mash-up.  Propagate the error instead.
                if any_tokens_emitted:
                    on_error(f"groq {type(e).__name__} mid-stream: "
                             f"{str(e)[:200]}")
                    return

                if any(s in msg for s in ("rate", "429", "quota", "limit")):
                    log(f"groq {attempt_model} rate-limited, trying next")
                    continue
                if any(s in msg for s in ("404", "not_found",
                                          "does not exist")):
                    log(f"groq {attempt_model} not available, skipping")
                    continue
                if "cloudflare" in msg:
                    continue
                # otherwise, propagate
                on_error(f"groq {type(e).__name__}: {str(e)[:200]}")
                return

        on_error(f"groq exhausted all models: {last_err}")


def _join_url(base: str, path: str) -> str:
    """Join an API base with a path, tolerating a trailing slash on the
    base (Google's endpoint is commonly written with one)."""
    return base.rstrip("/") + "/" + path.lstrip("/")


class OpenAICompatBackend:
    """Generic backend for any OpenAI-compatible /chat/completions API.

    Drives SiliconFlow, Novita, GitHub Models, and Google AI Studio with
    no extra dependencies — just urllib + Server-Sent-Events parsing,
    the same toolkit the Ollama backend already uses.  Mirrors
    GroqBackend's behaviour: biggest-model-first fallback chain, and a
    hard stop on mid-stream fallback so two models' output never gets
    spliced together on screen.
    """

    def __init__(self, spec: "ProviderSpec", api_key: str = ""):
        self.spec = spec
        self.name = spec.key
        self.api_key = api_key or ""
        self.base_url = spec.base_url
        self.fallback_chain = list(spec.chain)
        self.extra_headers = dict(spec.extra_headers or {})

    def set_api_key(self, key: str) -> None:
        self.api_key = key or ""

    def is_available(self) -> bool:
        return bool(self.api_key) and is_online()

    def _headers(self) -> Dict[str, str]:
        h = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        h.update(self.extra_headers)
        return h

    def list_models(self) -> List[Dict[str, Any]]:
        """Curated chain — instant, no network.  Used as the default
        Settings list."""
        return [{"name": m} for m in self.fallback_chain]

    def list_models_live(self, timeout: float = 8.0) -> List[str]:
        """Query the provider's /models endpoint for the real, current
        catalogue.  Returns [] on any failure so the caller can fall
        back to the curated chain."""
        if not self.api_key:
            return []
        try:
            req = urllib.request.Request(
                _join_url(self.base_url, "models"),
                headers=self._headers())
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read())
            items = data.get("data", data) if isinstance(data, dict) else data
            ids = []
            for it in items or []:
                mid = it.get("id") if isinstance(it, dict) else None
                if mid:
                    ids.append(mid)
            return sorted(ids)
        except Exception as e:
            log(f"{self.name} list_models_live failed: {e}")
            return []

    def stream_chat(self, model, messages, on_token, on_done, on_error,
                    options=None, cancel_event=None) -> None:
        if not self.api_key:
            on_error(f"{self.name} not configured (no API key)")
            return
        opts = options or {}
        body_base = {
            "messages": messages,
            "temperature": opts.get("temperature", 0.7),
            "top_p": opts.get("top_p", 0.9),
            "max_tokens": opts.get("max_tokens", 2048),
            "stream": True,
        }
        order = [model] + [m for m in self.fallback_chain if m != model]
        last_err = None
        any_tokens_emitted = False
        recovered_live = False   # only refresh the live catalogue once
        url = _join_url(self.base_url, "chat/completions")

        idx = 0
        while idx < len(order):
            attempt_model = order[idx]
            idx += 1
            if cancel_event and cancel_event.is_set():
                on_done({"cancelled": True, "text": "", "backend": self.name})
                return
            payload = dict(body_base)
            payload["model"] = attempt_model
            try:
                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(
                    url, data=data, headers=self._headers())
                parts: List[str] = []
                with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as r:
                    for raw in r:
                        if cancel_event and cancel_event.is_set():
                            on_done({"cancelled": True,
                                     "text": "".join(parts),
                                     "backend": self.name,
                                     "model": attempt_model})
                            return
                        line = raw.decode("utf-8", "replace").strip()
                        if not line or not line.startswith("data:"):
                            continue
                        chunk = line[len("data:"):].strip()
                        if chunk == "[DONE]":
                            break
                        try:
                            obj = json.loads(chunk)
                        except Exception:
                            continue
                        choices = obj.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta") or {}
                        tok = delta.get("content") or ""
                        if tok:
                            parts.append(tok)
                            any_tokens_emitted = True
                            on_token(tok)
                on_done({
                    "text": "".join(parts),
                    "backend": self.name,
                    "model": attempt_model,
                    "cancelled": False,
                })
                return
            except urllib.error.HTTPError as e:
                # Read the body once for diagnostics + retry decisions.
                try:
                    detail = e.read().decode("utf-8", "replace")[:300]
                except Exception:
                    detail = ""
                last_err = f"HTTP {e.code}: {detail or e.reason}"
                if any_tokens_emitted:
                    on_error(f"{self.name} {last_err} mid-stream")
                    return
                # 429 = rate limit; 404/400 = bad/unavailable model.
                if e.code in (404, 400) and not recovered_live:
                    # The hardcoded model ID may be stale.  Pull the live
                    # catalogue ONCE and append any unseen models so the
                    # next attempt uses a real, currently-served model
                    # instead of another guess.
                    recovered_live = True
                    live = self.list_models_live()
                    new = [m for m in live if m not in order]
                    if new:
                        log(f"{self.name} {attempt_model} -> {e.code}; "
                            f"recovered {len(new)} live models")
                        order.extend(new)
                        continue
                if e.code in (429, 404, 400, 502, 503):
                    log(f"{self.name} {attempt_model} -> {e.code}, next")
                    continue
                if e.code in (401, 403):
                    on_error(f"{self.name} auth failed (HTTP {e.code}) — "
                             f"check the API key")
                    return
                on_error(f"{self.name} {last_err}")
                return
            except urllib.error.URLError as e:
                last_err = f"connection: {getattr(e, 'reason', e)}"
                if any_tokens_emitted:
                    on_error(f"{self.name} {last_err} mid-stream")
                    return
                on_error(f"{self.name} {last_err}")
                return
            except Exception as e:
                last_err = f"{type(e).__name__}: {e}"
                if any_tokens_emitted:
                    on_error(f"{self.name} {last_err} mid-stream")
                    return
                continue

        on_error(f"{self.name} exhausted all models: {last_err}")


class BackendRouter:
    """Routes to the active cloud provider when online & configured,
    otherwise to local Ollama.  Holds one backend per registered cloud
    provider plus the local Ollama backend."""

    def __init__(self, cloud: Dict[str, Backend], ollama: OllamaBackend,
                 settings: Dict[str, Any]):
        self.cloud = cloud            # {provider_key: backend}
        self.ollama = ollama
        self.settings = settings
        # Back-compat: callers/tests that referenced router.groq directly
        # still work.
        self.groq = cloud.get("groq")

    def active_cloud(self) -> Tuple[Optional[Backend], str]:
        """Return (backend, provider_key) for the configured active
        provider, or (None, key) if it isn't usable right now."""
        key = self.settings.get("active_provider", "groq")
        backend = self.cloud.get(key)
        if backend is None:
            backend = self.cloud.get("groq")
            key = "groq"
        return backend, key

    def pick(self) -> Tuple[Backend, str]:
        """Returns (backend, model_name)."""
        if self.settings.get("prefer_cloud", True):
            backend, key = self.active_cloud()
            if backend is not None and backend.is_available():
                model = self.settings.get(
                    f"{key}_model",
                    PROVIDERS_BY_KEY[key].default_model
                    if key in PROVIDERS_BY_KEY else "")
                return backend, model
        return self.ollama, self.settings.get("ollama_model",
                                               OLLAMA_DEFAULT_MODEL)

    def stream_chat(self, messages, on_token, on_done, on_error,
                    cancel_event=None) -> Tuple[str, str]:
        backend, model = self.pick()
        opts = {
            "temperature": self.settings.get("temperature", 0.7),
            "top_p": self.settings.get("top_p", 0.9),
            "max_tokens": self.settings.get("max_tokens", 2048),
            "num_ctx": self.settings.get("num_ctx", 4096),
        }

        # Track whether we emitted any tokens through the wrapper.
        emitted = {"any": False}

        def _on_tok(t: str):
            emitted["any"] = True
            on_token(t)

        # Wrap on_error so we can attempt Ollama fallback if a cloud
        # provider fails — but only when no tokens have made it to the UI
        # yet.  Otherwise we'd splice two model outputs together.
        is_cloud = backend is not self.ollama

        def _on_err(err: str):
            if (is_cloud
                    and not emitted["any"]
                    and self.ollama.is_running()):
                log(f"{backend.name} failed ({err}) — falling back to ollama")
                self.ollama.stream_chat(
                    self.settings.get("ollama_model", OLLAMA_DEFAULT_MODEL),
                    messages, _on_tok, on_done, on_error, opts, cancel_event)
            else:
                on_error(err)

        backend.stream_chat(model, messages, _on_tok, on_done, _on_err,
                            opts, cancel_event)
        return backend.name, model


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
    role: str
    content: str
    ts: float
    meta: Dict[str, Any] = field(default_factory=dict)


class ChatStore:
    def __init__(self, path: Path = CHATS_DB):
        self.path = path
        self._lock = threading.Lock()
        # ONE persistent connection.  Previously we opened a fresh
        # connection per call via `with self._conn() as c:` — the
        # context manager commits but does NOT close, so every
        # operation leaked a file handle.  Over hundreds of operations
        # the app would hit ulimit and start failing.
        self._db = sqlite3.connect(str(path), check_same_thread=False,
                                    isolation_level=None)  # autocommit
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.executescript(CHAT_DDL)

    def close(self) -> None:
        try:
            with self._lock:
                self._db.close()
        except Exception:
            pass

    def __del__(self):
        self.close()

    def create_chat(self, title: str, model: str,
                    agent_mode: bool = True) -> int:
        now = time.time()
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO chats (title, model, created_at, updated_at, "
                "agent_mode) VALUES (?, ?, ?, ?, ?)",
                (title, model, now, now, 1 if agent_mode else 0))
            return cur.lastrowid

    def list_chats(self, limit: int = 200) -> List[Chat]:
        with self._lock:
            rows = self._db.execute(
                "SELECT id, title, model, created_at, updated_at, pinned, "
                "agent_mode FROM chats "
                "ORDER BY pinned DESC, updated_at DESC LIMIT ?",
                (limit,)).fetchall()
        return [Chat(*r) for r in rows]

    def get_chat(self, chat_id: int) -> Optional[Chat]:
        with self._lock:
            row = self._db.execute(
                "SELECT id, title, model, created_at, updated_at, pinned, "
                "agent_mode FROM chats WHERE id=?", (chat_id,)).fetchone()
        return Chat(*row) if row else None

    def rename_chat(self, chat_id: int, title: str) -> None:
        with self._lock:
            self._db.execute("UPDATE chats SET title=?, updated_at=? WHERE id=?",
                             (title, time.time(), chat_id))

    def set_pinned(self, chat_id: int, pinned: bool) -> None:
        with self._lock:
            self._db.execute("UPDATE chats SET pinned=? WHERE id=?",
                             (1 if pinned else 0, chat_id))

    def set_agent_mode(self, chat_id: int, agent: bool) -> None:
        with self._lock:
            self._db.execute("UPDATE chats SET agent_mode=? WHERE id=?",
                             (1 if agent else 0, chat_id))

    def delete_chat(self, chat_id: int) -> None:
        with self._lock:
            self._db.execute("DELETE FROM chats WHERE id=?", (chat_id,))

    def add_message(self, chat_id: int, role: str, content: str,
                    meta: Optional[Dict[str, Any]] = None) -> int:
        meta_s = json.dumps(meta) if meta else None
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO messages (chat_id, role, content, ts, meta) "
                "VALUES (?, ?, ?, ?, ?)",
                (chat_id, role, content, time.time(), meta_s))
            self._db.execute("UPDATE chats SET updated_at=? WHERE id=?",
                             (time.time(), chat_id))
            return cur.lastrowid

    def list_messages(self, chat_id: int) -> List[Message]:
        with self._lock:
            rows = self._db.execute(
                "SELECT id, chat_id, role, content, ts, meta "
                "FROM messages WHERE chat_id=? ORDER BY ts ASC, id ASC",
                (chat_id,)).fetchall()
        out = []
        for r in rows:
            try:
                meta = json.loads(r[5]) if r[5] else {}
            except json.JSONDecodeError:
                meta = {}
            out.append(Message(r[0], r[1], r[2], r[3], r[4], meta))
        return out

    def update_message(self, msg_id: int, content: str) -> None:
        with self._lock:
            self._db.execute("UPDATE messages SET content=? WHERE id=?",
                             (content, msg_id))

    def count_messages_by_role(self, chat_id: int, role: str) -> int:
        """Cheap count for first-message detection — avoids re-fetching all."""
        with self._lock:
            row = self._db.execute(
                "SELECT COUNT(*) FROM messages WHERE chat_id=? AND role=?",
                (chat_id, role)).fetchone()
        return row[0] if row else 0


# ═════════════════════════════════════════════════════════════════════
# TOOLS — file access, command exec, system info
# ═════════════════════════════════════════════════════════════════════

def is_sensitive_path(path: str) -> bool:
    rp = os.path.realpath(os.path.expanduser(path))
    for p in SENSITIVE_PATHS:
        if rp.rstrip("/") == p.rstrip("/") or rp.startswith(p.rstrip("/") + "/"):
            return True
    return False


def _ro(argv: List[str], timeout: int = 12) -> Tuple[int, str, str]:
    try:
        # Preserve the subset of env vars that systemctl --user /
        # journalctl --user / D-Bus tooling need to find the user session.
        # Stripping these (as the previous version did) silently broke
        # any --user command.
        env = {
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
            "HOME": os.path.expanduser("~"),
            "USER": os.environ.get("USER", ""),
        }
        for key in ("DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR",
                    "XDG_DATA_DIRS", "XDG_CONFIG_DIRS", "XDG_CACHE_HOME",
                    "DISPLAY", "WAYLAND_DISPLAY"):
            if key in os.environ:
                env[key] = os.environ[key]

        p = subprocess.run(
            argv, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout, env=env, text=True, errors="replace")
        return (p.returncode, p.stdout or "", p.stderr or "")
    except subprocess.TimeoutExpired:
        return (124, "", "timeout")
    except FileNotFoundError:
        return (127, "", "not found")
    except Exception as e:
        return (1, "", f"err: {type(e).__name__}: {e}")


def _have(c: str) -> bool:
    return shutil.which(c) is not None


def _read(path: str, max_bytes: int = 100_000) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(max_bytes)
    except Exception:
        return None


def _human_bytes(n: int) -> str:
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f}{u}"
        n /= 1024
    return f"{n:.1f}PB"


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
        return {"ok": True, "path": rp, "size": size, "kind": kind,
                "truncated": size > max_bytes, "content": text}
    except PermissionError:
        return {"ok": False, "error": f"permission denied: {path}"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def make_edit_diff(path: str, new_content: str,
                   context: int = 3) -> Dict[str, Any]:
    """Build a COMPACT preview of what writing `new_content` to `path`
    would change, for the confirmation card.  Returns the changed
    hunks only (not the whole file) plus line-count deltas, so the
    operator sees exactly what moves without scrolling a wall of text.

    This performs NO write — it's purely advisory, computed when the
    model proposes an edit so the card can show a real diff.
    """
    import difflib
    rp = os.path.realpath(os.path.expanduser(path))
    is_new = not os.path.exists(rp)
    old = ""
    if not is_new:
        try:
            with open(rp, "r", encoding="utf-8", errors="replace") as f:
                old = f.read()
        except Exception as e:
            return {"ok": False, "error": f"can't read target: {e}"}

    old_lines = old.splitlines()
    new_lines = new_content.splitlines()
    diff = list(difflib.unified_diff(
        old_lines, new_lines,
        fromfile=("(new file)" if is_new else "current"),
        tofile="proposed", n=context, lineterm=""))
    added = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))

    # Cap the rendered diff so a huge rewrite doesn't make an unreadable
    # card.  If it's enormous, summarise instead of dumping everything.
    MAX_DIFF_LINES = 80
    truncated = len(diff) > MAX_DIFF_LINES
    shown = diff[:MAX_DIFF_LINES]

    return {"ok": True, "path": rp, "is_new": is_new,
            "added": added, "removed": removed,
            "diff": shown, "truncated": truncated,
            "is_python": rp.endswith(".py")}


def _extract_guardrail_blocks(text: str) -> List[str]:
    """Return the protected text of every GUARDRAIL block in `text`.

    A block is the content strictly BETWEEN a line containing the opening
    marker ("GUARDRAIL" but not "END GUARDRAIL") and the next line
    containing "END GUARDRAIL".  Matched line-by-line rather than with a
    single regex, so cosmetic divider characters around the markers don't
    throw it off.  Returned text is stripped for comparison.
    """
    blocks: List[str] = []
    lines = text.splitlines()
    i = 0
    n = len(lines)
    while i < n:
        up = lines[i].upper()
        is_open = ("GUARDRAIL" in up) and ("END GUARDRAIL" not in up)
        if is_open:
            body: List[str] = []
            j = i + 1
            closed = False
            while j < n:
                if "END GUARDRAIL" in lines[j].upper():
                    closed = True
                    break
                body.append(lines[j])
                j += 1
            if closed:
                blocks.append("\n".join(body).strip())
                i = j + 1
                continue
        i += 1
    return blocks


# Files whose guardrail blocks are protected from self-edits.  Keyed by
# basename so it matches wherever the install lives.
_PROTECTED_FILES = {"kali_persona.py"}


def _check_protected_regions(realpath: str, new_content: str
                             ) -> Optional[Dict[str, Any]]:
    """If `realpath` is a protected file, refuse the write unless every
    GUARDRAIL block in it is preserved byte-for-byte.  Returns a refusal
    result dict on violation, or None if the write is allowed.

    Rules enforced:
      · the proposed content must contain the SAME number of guardrail
        blocks as the file on disk (can't drop one),
      · each block's protected text must be unchanged (can't alter one),
      · a brand-new file may introduce blocks freely (nothing to protect
        yet) — protection only binds once a block exists on disk.
    """
    base = os.path.basename(realpath)
    if base not in _PROTECTED_FILES:
        return None
    if not os.path.exists(realpath):
        return None  # new file; no existing guardrails to protect
    try:
        with open(realpath, "r", encoding="utf-8", errors="replace") as f:
            current = f.read()
    except Exception:
        # If we can't read the original to compare, fail safe: refuse.
        return {"ok": False, "path": realpath,
                "error": "refused: cannot read current file to verify its "
                         "guardrail block is preserved. Nothing was written.",
                "guardrail_violation": True}

    cur_blocks = _extract_guardrail_blocks(current)
    new_blocks = _extract_guardrail_blocks(new_content)

    if not cur_blocks:
        return None  # file has no protected block to guard

    if len(new_blocks) < len(cur_blocks):
        return {"ok": False, "path": realpath,
                "error": "refused: this edit removes a GUARDRAIL block. "
                         "The safety block is immutable and cannot be "
                         "deleted by a self-edit. Nothing was written.",
                "guardrail_violation": True}

    for i, cur in enumerate(cur_blocks):
        if i >= len(new_blocks) or new_blocks[i] != cur:
            return {"ok": False, "path": realpath,
                    "error": "refused: this edit alters a protected "
                             "GUARDRAIL block. That block is immutable — "
                             "edit anything else in the file, but the "
                             "guardrails stay exactly as they are. "
                             "Nothing was written.",
                    "guardrail_violation": True}
    return None


def tool_write_file(path: str, content: str,
                    make_backup: bool = True) -> Dict[str, Any]:
    """Write `content` to `path` — the executing half of a self-edit.

    Reached ONLY after the operator approves the diff card.  Safety net,
    in order:
      1. If the target is a .py file, parse-check the NEW content with
         ast BEFORE touching disk.  A syntax error means we refuse the
         write entirely — this is what stops Kali from rewriting its own
         source into something that won't launch.
      2. Back up the existing file to backups/ with a timestamp so any
         change is one copy away from being undone.
      3. Write atomically (temp file in the same dir, then os.replace),
         so a crash mid-write can't leave a half-written, truncated
         source file.
    """
    try:
        rp = os.path.realpath(os.path.expanduser(path))

        # 1. parse-check python before we risk the existing file
        if rp.endswith(".py"):
            import ast
            try:
                ast.parse(content)
            except SyntaxError as e:
                return {"ok": False, "path": rp,
                        "error": f"refused: new content has a Python syntax "
                                 f"error (line {e.lineno}: {e.msg}). "
                                 f"Nothing was written.",
                        "syntax_error": True}

        # 1b. PROTECTED-REGION GUARD.  Any block delimited by the
        # GUARDRAIL markers below is immutable: a write that adds,
        # removes, or alters the text inside it is refused outright,
        # before any backup or write happens.  This is what makes the
        # safety block tamper-proof rather than just visually labelled —
        # Kali can rewrite anything else in its own source, but it
        # physically cannot edit (or delete) its own guardrails.
        guard = _check_protected_regions(rp, content)
        if guard is not None:
            return guard

        parent = os.path.dirname(rp)
        if parent and not os.path.isdir(parent):
            return {"ok": False, "path": rp,
                    "error": f"parent directory does not exist: {parent}"}

        # 2. back up the original if it exists
        backup_path = None
        existed = os.path.exists(rp)
        if existed and make_backup:
            try:
                BACKUP_DIR = DATA_DIR / "backups"
                BACKUP_DIR.mkdir(parents=True, exist_ok=True)
                stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
                base = os.path.basename(rp)
                backup_path = str(BACKUP_DIR / f"{base}.{stamp}.bak")
                shutil.copy2(rp, backup_path)
            except Exception as e:
                # A failed backup is a hard stop — we don't overwrite
                # something we couldn't first preserve.
                return {"ok": False, "path": rp,
                        "error": f"refused: could not back up the original "
                                 f"before writing ({e}). Nothing was written."}

        # 3. atomic write
        tmp = rp + ".kali-tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
        # preserve the original mode/owner where possible
        if existed:
            try:
                st = os.stat(rp)
                os.chmod(tmp, st.st_mode)
            except Exception:
                pass
        os.replace(tmp, rp)

        size = os.path.getsize(rp)
        log(f"wrote {rp} ({size} bytes)"
            + (f", backup {backup_path}" if backup_path else ""))
        return {"ok": True, "path": rp, "size": size,
                "created": not existed, "backup": backup_path,
                "is_python": rp.endswith(".py")}
    except PermissionError:
        return {"ok": False, "path": path,
                "error": f"permission denied: {path} "
                         f"(a root-owned path needs the `run` tool with "
                         f"`sudo tee` instead)"}
    except Exception as e:
        return {"ok": False, "path": path,
                "error": f"{type(e).__name__}: {e}"}


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
                    "mtime": st.st_mtime,
                })
            except Exception:
                entries.append({"name": name, "size": -1, "is_dir": False,
                                "mtime": 0})
        return {"ok": True, "path": rp, "entries": entries}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# Matches a `sudo` invocation at the start of the command or after a
# shell separator (; | & && || ( newline), so we don't false-positive on
# e.g. `echo "pseudo"` or a path like /opt/sudoku.  Also tolerates one or
# more leading environment assignments (`FOO=bar sudo ...`), which are
# still command-position invocations.  `sudo` followed by a word boundary
# only.
_SUDO_RE = re.compile(
    r'(?:^|[\n;&|(]\s*|\b&&\s*|\b\|\|\s*)(?:\w+=\S*\s+)*sudo\b')


def command_needs_sudo(command: str) -> bool:
    """True if the command contains a real `sudo` invocation."""
    if not command:
        return False
    return bool(_SUDO_RE.search(command))


# Same matcher, but capturing the leading boundary so we can inject an
# askpass flag into each `sudo` invocation when we fall back to that path.
_SUDO_INJECT_RE = re.compile(r'(^|[\n;&|(]\s*|&&\s*|\|\|\s*)sudo(?=\s|$)')


def _inject_askpass(command: str) -> str:
    """Turn each `sudo` invocation into `sudo -A` (use SUDO_ASKPASS).
    Safe with any command — unlike `-S`, askpass never reads the
    command's stdin, so `sudo -A tee file` still works correctly."""
    if " -A" in command and "sudo -A" in command:
        return command
    return _SUDO_INJECT_RE.sub(r'\1sudo -A', command)


def _ensure_askpass_helper() -> Optional[str]:
    """Write (once) a tiny askpass helper that echoes $KALI_SUDO_PW.
    The script itself holds NO secret — the password is handed to it
    via the environment of the single sudo call, and only that call."""
    path = DATA_DIR / ".kali-askpass.sh"
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write('#!/bin/sh\nprintf "%s\\n" "$KALI_SUDO_PW"\n')
        os.chmod(path, 0o700)
        return str(path)
    except Exception as e:
        log(f"askpass helper write failed: {e}")
        return None


def _format_run_result(command: str, p, needs_sudo: bool) -> Dict[str, Any]:
    stderr = p.stderr or ""
    result = {
        "ok": True, "command": command, "rc": p.returncode,
        "stdout": (p.stdout or "")[:80_000],
        "stderr": stderr[:20_000],
        "truncated_stdout": len(p.stdout or "") > 80_000,
        "needs_sudo": needs_sudo,
    }
    low = stderr.lower()
    if needs_sudo and p.returncode != 0 and (
            "a terminal is required" in low
            or "no password was provided" in low
            or "a password is required" in low
            or "askpass" in low):
        result["sudo_auth_failed"] = True
    return result


def _run_sudo_inline(command: str, password: str, timeout: int,
                     cwd: Optional[str]) -> Dict[str, Any]:
    """Authenticate and run in ONE shell session so the cached sudo
    credential is guaranteed to apply to the command's own `sudo` calls.

    The password is fed once on stdin and consumed by `sudo -S -v`; the
    command then runs with that fresh credential.  Password never touches
    disk, env, the log, or the command's stdin (sudo -v eats the single
    line we send; the command sees EOF)."""
    # rc 97 is our private sentinel for "authentication failed".
    script = "sudo -S -p '' -v || exit 97\n" + command
    try:
        p = subprocess.run(
            ["bash", "-c", script],
            input=password + "\n",
            cwd=cwd or os.path.expanduser("~"),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout, text=True, errors="replace")
        if p.returncode == 97:
            err = (p.stderr or "").strip().lower()
            if "not in the sudoers" in err or "not allowed" in err:
                why = "this account is not permitted to use sudo"
            else:
                why = "incorrect sudo password"
            return {"ok": False, "command": command, "rc": 97,
                    "stdout": "", "stderr": p.stderr or why,
                    "error": f"sudo: {why}", "needs_sudo": True,
                    "auth_rejected": True}
        return _format_run_result(command, p, needs_sudo=True)
    except subprocess.TimeoutExpired:
        return {"ok": False, "command": command,
                "error": f"timeout after {timeout}s", "needs_sudo": True}
    except FileNotFoundError:
        return {"ok": False, "command": command,
                "error": "bash or sudo not found", "needs_sudo": True}
    except Exception as e:
        return {"ok": False, "command": command,
                "error": f"{type(e).__name__}: {e}", "needs_sudo": True}


def _run_sudo_askpass(command: str, password: str, timeout: int,
                      cwd: Optional[str]) -> Optional[Dict[str, Any]]:
    """Fallback for hardened sudoers (e.g. timestamp_timeout=0) where the
    inline cached credential won't carry to the command's sudo.  Uses
    SUDO_ASKPASS, which authenticates each `sudo` independently and never
    depends on a shared timestamp.  Returns None if the helper can't be
    set up (so the caller can keep the inline result)."""
    helper = _ensure_askpass_helper()
    if not helper:
        return None
    cmd2 = _inject_askpass(command)
    env = dict(os.environ)
    env["SUDO_ASKPASS"] = helper
    env["KALI_SUDO_PW"] = password
    try:
        p = subprocess.run(
            cmd2, shell=True,
            cwd=cwd or os.path.expanduser("~"),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout, text=True, errors="replace", env=env)
        return _format_run_result(command, p, needs_sudo=True)
    except subprocess.TimeoutExpired:
        return {"ok": False, "command": command,
                "error": f"timeout after {timeout}s", "needs_sudo": True}
    except Exception as e:
        return {"ok": False, "command": command,
                "error": f"{type(e).__name__}: {e}", "needs_sudo": True}
    finally:
        # Drop the secret from our env copy promptly.
        env["KALI_SUDO_PW"] = ""


def tool_run_command(command: str, timeout: int = 30,
                     cwd: Optional[str] = None,
                     sudo_password: Optional[str] = None) -> Dict[str, Any]:
    """Run a shell command as the operator's user.

    If `sudo_password` is supplied and the command needs root, we
    authenticate and run in the SAME shell session (so the credential
    actually applies), and transparently fall back to SUDO_ASKPASS if a
    hardened sudoers config defeats the cached credential.  The password
    is never written to disk, the log, or the command's own stdin.
    """
    needs_sudo = command_needs_sudo(command)

    if needs_sudo and sudo_password is not None:
        result = _run_sudo_inline(command, sudo_password, timeout, cwd)
        # If the password was simply wrong, report that — don't retry.
        if result.get("auth_rejected"):
            sudo_password = None
            return result
        # If the inline path authenticated but the command's own sudo
        # still couldn't get a credential (hardened sudoers), retry via
        # askpass before giving up.
        if result.get("sudo_auth_failed"):
            alt = _run_sudo_askpass(command, sudo_password, timeout, cwd)
            if alt is not None:
                result = alt
        sudo_password = None  # drop reference
        return result

    try:
        p = subprocess.run(
            command, shell=True,
            cwd=cwd or os.path.expanduser("~"),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout, text=True, errors="replace")
        return _format_run_result(command, p, needs_sudo)
    except subprocess.TimeoutExpired:
        return {"ok": False, "command": command,
                "error": f"timeout after {timeout}s", "needs_sudo": needs_sudo}
    except Exception as e:
        return {"ok": False, "command": command,
                "error": f"{type(e).__name__}: {e}", "needs_sudo": needs_sudo}


def tool_system_info() -> Dict[str, Any]:
    info: Dict[str, Any] = {}
    try:
        info["hostname"] = socket.gethostname()
    except Exception:
        pass
    try:
        info["uname"] = " ".join(os.uname())
    except Exception:
        pass
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
    try:
        with open("/proc/uptime") as f:
            up = float(f.read().split()[0])
        info["uptime_sec"] = int(up)
    except Exception:
        pass
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
    try:
        with open("/proc/loadavg") as f:
            info["load"] = f.read().strip()
    except Exception:
        pass
    return info


# ═════════════════════════════════════════════════════════════════════
# OS-LEVEL TOOLS — packages, services, downloads, processes, journal
# ═════════════════════════════════════════════════════════════════════

def tool_check_updates() -> Dict[str, Any]:
    """List packages with pending updates.  apt-based systems only."""
    if not _have("apt"):
        return {"ok": False, "error": "apt not installed on this system"}
    rc, out, _ = _ro(["apt", "list", "--upgradable"], timeout=30)
    if rc != 0:
        return {"ok": False, "error": "apt list failed (try sudo apt update first)"}
    pkgs = []
    sec_count = 0
    for line in out.splitlines():
        if "/" not in line or "[upgradable" not in line:
            continue
        name = line.split("/", 1)[0].strip()
        is_security = "-security" in line.lower()
        if is_security:
            sec_count += 1
        pkgs.append({"name": name, "security": is_security})
    return {"ok": True, "count": len(pkgs), "security_count": sec_count,
            "packages": pkgs}


def tool_recent_downloads(limit: int = 20) -> Dict[str, Any]:
    paths_to_check = [HOME / "Downloads", HOME / "downloads"]
    found = None
    for p in paths_to_check:
        if p.is_dir():
            found = p
            break
    if not found:
        return {"ok": False, "error": "no Downloads folder found"}

    # Build (entry, mtime) list defensively — a dangling symlink in the
    # directory would raise inside the sort key lambda otherwise, killing
    # the whole call.
    def _mtime_safe(entry):
        try:
            return entry.stat().st_mtime
        except Exception:
            return 0.0

    files = []
    try:
        all_entries = list(found.iterdir())
        all_entries.sort(key=_mtime_safe, reverse=True)
        for entry in all_entries[:limit]:
            try:
                st = entry.stat()
                files.append({
                    "name": entry.name,
                    "size_human": _human_bytes(st.st_size),
                    "size": st.st_size,
                    "mtime": st.st_mtime,
                    "age_seconds": time.time() - st.st_mtime,
                    "is_dir": entry.is_dir(),
                })
            except Exception:
                # Dangling symlink, permission denied — still list it
                files.append({
                    "name": entry.name,
                    "size_human": "?", "size": -1,
                    "mtime": 0.0, "age_seconds": 0.0,
                    "is_dir": False,
                })
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "path": str(found), "files": files}


def tool_service_status(name: Optional[str] = None) -> Dict[str, Any]:
    if not _have("systemctl"):
        return {"ok": False, "error": "systemctl not available"}
    if name:
        rc, out, _ = _ro(["systemctl", "status", "--no-pager", "-n", "0",
                          name], timeout=8)
        active = "active (running)" in out or "active (exited)" in out
        return {"ok": True, "service": name, "active": active,
                "raw": out[:4000]}
    else:
        rc, out, _ = _ro(["systemctl", "list-units", "--type=service",
                          "--state=running", "--no-pager", "--plain",
                          "--no-legend"], timeout=8)
        services = []
        for line in out.splitlines():
            parts = line.split(None, 4)
            if len(parts) >= 1 and parts[0].endswith(".service"):
                services.append(parts[0])
        return {"ok": True, "running_services": services,
                "count": len(services)}


def tool_journal_tail(lines: int = 50,
                      unit: Optional[str] = None,
                      since: Optional[str] = None) -> Dict[str, Any]:
    if not _have("journalctl"):
        return {"ok": False, "error": "journalctl not available"}
    argv = ["journalctl", "--no-pager", "-n", str(lines)]
    if unit:
        argv += ["-u", unit]
    if since:
        argv += ["--since", since]
    rc, out, _ = _ro(argv, timeout=15)
    if rc != 0:
        # might need user-mode
        argv.insert(1, "--user")
        rc, out, _ = _ro(argv, timeout=15)
    if rc != 0:
        return {"ok": False, "error": "journalctl failed"}
    return {"ok": True, "lines": out.splitlines()[-lines:],
            "raw": out[-20000:]}


def tool_disk_usage() -> Dict[str, Any]:
    if not _have("df"):
        return {"ok": False, "error": "df not available"}
    rc, out, _ = _ro(["df", "-h", "--output=source,size,used,avail,pcent,target"])
    if rc != 0:
        return {"ok": False, "error": "df failed"}
    rows = []
    lines = out.splitlines()[1:]
    for line in lines:
        parts = line.split(None, 5)
        if len(parts) >= 6 and not parts[0].startswith(("tmpfs", "devtmpfs",
                                                       "/dev/loop")):
            rows.append({
                "source": parts[0], "size": parts[1], "used": parts[2],
                "avail": parts[3], "use_pct": parts[4],
                "mount": parts[5],
            })
    return {"ok": True, "filesystems": rows}


def tool_processes(top_n: int = 15) -> Dict[str, Any]:
    if not _have("ps"):
        return {"ok": False, "error": "ps not available"}
    rc, out, _ = _ro(["ps", "-eo", "pid,pcpu,pmem,comm",
                      "--sort=-pcpu"], timeout=5)
    if rc != 0:
        return {"ok": False, "error": "ps failed"}
    lines = out.splitlines()
    procs = []
    for line in lines[1:top_n + 1]:
        parts = line.split(None, 3)
        if len(parts) >= 4:
            procs.append({
                "pid": parts[0],
                "cpu_pct": parts[1],
                "mem_pct": parts[2],
                "comm": parts[3],
            })
    return {"ok": True, "processes": procs}


def tool_network_status() -> Dict[str, Any]:
    info: Dict[str, Any] = {"online": is_online()}
    if _have("ip"):
        rc, out, _ = _ro(["ip", "-4", "-o", "addr"])
        ifaces = []
        for line in out.splitlines():
            m = re.match(r'\d+:\s+(\S+)\s+inet\s+(\S+)', line)
            if m and m.group(1) != "lo":
                ifaces.append({"name": m.group(1), "addr": m.group(2)})
        info["interfaces"] = ifaces

        rc, out, _ = _ro(["ip", "-4", "route", "show", "default"])
        m = re.search(r'default via (\S+).*dev\s+(\S+)', out)
        if m:
            info["default_gateway"] = m.group(1)
            info["default_iface"] = m.group(2)

    if _have("ss"):
        rc, out, _ = _ro(["ss", "-tnH"])
        info["established_connections"] = len(out.splitlines())
    return {"ok": True, **info}


def tool_find_file(pattern: str,
                   search_path: str = "~",
                   max_results: int = 50) -> Dict[str, Any]:
    """Find files by name pattern."""
    if not _have("find"):
        return {"ok": False, "error": "find not available"}
    rp = os.path.expanduser(search_path)
    if not os.path.isdir(rp):
        return {"ok": False, "error": f"not a directory: {search_path}"}
    rc, out, err = _ro(["find", rp, "-name", pattern, "-type", "f"],
                       timeout=30)
    if rc == 124:
        return {"ok": False, "error": "find timed out after 30s — "
                                       "narrow the search path or pattern",
                "partial": out.splitlines()[:max_results]}
    all_lines = out.splitlines()
    results = all_lines[:max_results]
    return {"ok": True, "pattern": pattern, "search_path": rp,
            "found": results, "count": len(results),
            "truncated": len(all_lines) > max_results}


# ═════════════════════════════════════════════════════════════════════
# SECURITY AUDIT (from ares.py, abbreviated)
# ═════════════════════════════════════════════════════════════════════

SEVERITY_WEIGHTS = {"info": 0, "low": 1, "medium": 3, "high": 8, "critical": 20}


@dataclass
class Finding:
    check_id: str
    title: str
    severity: str
    evidence: str
    fix_hint: str = ""
    raw: str = ""

    def __post_init__(self):
        if self.severity not in SEVERITY_WEIGHTS:
            self.severity = "info"
        if self.raw and len(self.raw) > 1500:
            self.raw = self.raw[:1500]


def check_firewall() -> List[Finding]:
    """Detect firewall presence WITHOUT requiring root.

    The previous version called `ufw status`, `iptables -S`, and `nft
    list ruleset` directly — all of which require CAP_NET_ADMIN.  When
    the audit ran as the regular user (the normal case) every command
    returned permission-denied, the script fell through to the final
    "No firewall detected — HIGH" branch, and the user got told their
    system was open even when it wasn't.

    New approach: ask systemd first.  `systemctl is-active <unit>` is
    readable by any user and tells us whether the firewall *service*
    is up.  Then check ufw.conf for the boot-time enable flag.  Only
    after that do we try the privileged inspectors — and if they fail
    we report uncertainty rather than asserting absence.
    """
    fs: List[Finding] = []
    fw_active = False
    detected_via = None

    # ── pass 1: systemd services (no root needed) ─────────────────
    if _have("systemctl"):
        for svc in ("ufw", "firewalld", "nftables", "iptables",
                    "netfilter-persistent"):
            rc, out, _ = _ro(
                ["systemctl", "is-active", f"{svc}.service"], timeout=4)
            if out.strip() == "active":
                fw_active = True
                detected_via = svc
                fs.append(Finding(
                    f"FW-S{svc[:3].upper()}",
                    f"{svc} service is active",
                    "info",
                    f"systemctl reports {svc}.service active"))
                break

    # ── pass 2: ufw.conf (also no root needed) ────────────────────
    if not fw_active:
        ufw_conf = _read("/etc/ufw/ufw.conf")
        if ufw_conf and re.search(
                r'^\s*ENABLED\s*=\s*yes', ufw_conf, re.M | re.I):
            fw_active = True
            detected_via = "ufw.conf"
            fs.append(Finding(
                "FW-CONF", "UFW enabled in /etc/ufw/ufw.conf", "info",
                "ufw.conf has ENABLED=yes"))

    # ── pass 3: privileged inspectors (best-effort) ───────────────
    # These tell us about RULES, not just service state.  They mostly
    # fail without root; we treat that as "no extra info", not as a
    # negative signal.
    privileged_attempts: List[Tuple[str, List[str]]] = []
    if _have("ufw"):
        privileged_attempts.append(("ufw",      ["ufw", "status"]))
    if _have("iptables"):
        privileged_attempts.append(("iptables", ["iptables", "-S"]))
    if _have("nft"):
        privileged_attempts.append(("nft",      ["nft", "list", "ruleset"]))

    for label, argv in privileged_attempts:
        rc, out, err = _ro(argv, timeout=6)
        # Recognise the various "need root" responses so we don't
        # mistake them for "no rules".
        needs_root = (
            rc != 0 and (
                "need to be root" in (err + out).lower()
                or "permission denied" in (err + out).lower()
                or "operation not permitted" in (err + out).lower()))
        if needs_root:
            continue
        if rc != 0:
            continue
        if label == "ufw" and re.search(r'status:\s*active', out, re.I):
            if not fw_active:
                fw_active = True
                detected_via = "ufw status"
                fs.append(Finding("FW-001", "UFW firewall is active",
                                  "info", "ufw status: active",
                                  raw=out[:1200]))
        elif label == "ufw" and re.search(
                r'status:\s*inactive', out, re.I) and not fw_active:
            fs.append(Finding("FW-002", "UFW firewall is INACTIVE", "high",
                              "ufw installed but not enabled",
                              fix_hint=("sudo ufw default deny incoming && "
                                        "sudo ufw allow ssh && sudo ufw enable"),
                              raw=out[:1200]))
        elif label == "iptables" and any(
                re.search(r'-[PA]\s+\w+.*-j\s+(DROP|REJECT)', l)
                or re.search(r'-P\s+\w+\s+(DROP|REJECT)', l)
                for l in out.splitlines()):
            if not fw_active:
                fw_active = True
                detected_via = "iptables"
                fs.append(Finding("FW-003", "iptables rules present",
                                  "info", "iptables rules configured",
                                  raw=out[:1200]))
        elif label == "nft" and out.strip():
            if not fw_active:
                fw_active = True
                detected_via = "nft"
                fs.append(Finding("FW-005", "nftables rules present",
                                  "info", "nftables ruleset loaded",
                                  raw=out[:1200]))

    # ── verdict ───────────────────────────────────────────────────
    if not fw_active:
        fs.append(Finding(
            "FW-006",
            "No firewall detected (limited visibility without root)",
            "medium",
            "No ufw/firewalld/nftables/iptables service is active, "
            "/etc/ufw/ufw.conf does not enable ufw, and the privileged "
            "tools could not be inspected as a regular user.  Re-run the "
            "audit with sudo for a definitive check.",
            fix_hint=("sudo apt install ufw && sudo ufw default deny "
                      "incoming && sudo ufw allow ssh && sudo ufw enable")))
    else:
        log(f"firewall detected via: {detected_via}")
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
        if local.startswith(("0.0.0.0", "*", "[::]", "::")):
            risky.append((port, local))
    if risky:
        details = "\n".join(f"  :{p} on {a}" for p, a in risky[:15])
        sev = "high" if any(p in (21, 23, 2049, 5900) for p, _ in risky) else "medium"
        fs.append(Finding("NET-001",
                          f"{len(risky)} port(s) on all interfaces",
                          sev, details,
                          fix_hint="Bind services to 127.0.0.1 or firewall them"))
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
        fs.append(Finding("SSH-001", "SSH password auth enabled", "medium",
                          "PasswordAuthentication=yes",
                          fix_hint="PasswordAuthentication no"))
    if root in ("yes", "without-password"):
        fs.append(Finding("SSH-002", f"PermitRootLogin = {root}", "high",
                          "Root SSH login should be off",
                          fix_hint="PermitRootLogin no"))
    return fs


def check_pending_updates_audit() -> List[Finding]:
    fs: List[Finding] = []
    if not _have("apt-get"):
        return fs
    rc, out, _ = _ro(["apt-get", "-s", "upgrade"], timeout=20)
    if rc != 0:
        return fs
    sec = sum(1 for l in out.splitlines()
              if l.startswith("Inst ") and "security" in l.lower())
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
    if (major, minor) < (5, 15):
        fs.append(Finding("KERN-001", f"Old kernel ({kr})", "medium",
                          "Kernel predates 5.15 LTS",
                          fix_hint="sudo apt upgrade && reboot"))
    else:
        fs.append(Finding("KERN-OK", f"Kernel {kr}", "info", "Modern kernel"))
    return fs


def check_failed_logins() -> List[Finding]:
    fs: List[Finding] = []
    if not _have("journalctl"):
        return fs
    rc, out, _ = _ro(["journalctl", "_COMM=sshd", "--since", "24 hours ago",
                      "--no-pager", "-q"], timeout=15)
    if rc != 0:
        return fs
    fails = sum(1 for l in out.splitlines() if "Failed password" in l)
    if fails > 50:
        fs.append(Finding("AUTH-001",
                          f"{fails} failed SSH logins last 24h", "high",
                          "Possible brute force",
                          fix_hint="Install fail2ban, keys-only auth"))
    elif fails > 5:
        fs.append(Finding("AUTH-002",
                          f"{fails} failed SSH logins last 24h", "medium",
                          "Some noise on SSH"))
    return fs


def check_disk_encryption() -> List[Finding]:
    fs: List[Finding] = []
    if not _have("lsblk"):
        return fs
    rc, out, _ = _ro(["lsblk", "-o", "NAME,TYPE,FSTYPE,MOUNTPOINT"])
    if rc != 0:
        return fs
    has_root_crypt = bool(re.search(r'crypt\s+\S+\s+/$', out, re.M))
    has_crypt = "crypt" in out.lower()
    if has_root_crypt:
        fs.append(Finding("CRYPTO-001", "Root filesystem encrypted", "info",
                          "LUKS detected on /"))
    elif has_crypt:
        fs.append(Finding("CRYPTO-002", "Some volumes encrypted, root not",
                          "medium", "Encrypted partitions exist; root /  "
                          "appears unencrypted"))
    else:
        fs.append(Finding("CRYPTO-003", "No disk encryption", "medium",
                          "No LUKS volumes found",
                          fix_hint="FDE strongly recommended for phones/laptops"))
    return fs


def check_world_writable_home() -> List[Finding]:
    fs: List[Finding] = []
    home = os.path.expanduser("~")
    try:
        st = os.stat(home)
        if st.st_mode & 0o002:
            fs.append(Finding("PERM-001", "Home dir world-writable", "high",
                              f"{home} allows other users to write",
                              fix_hint=f"chmod 700 {home}"))
    except Exception:
        pass
    return fs


def check_mac() -> List[Finding]:
    fs: List[Finding] = []
    # ── AppArmor: prefer the rootless probe ───────────────────────
    # /sys/module/apparmor/parameters/enabled returns "Y" or "N" and
    # is world-readable.  aa-status needs root for the full picture,
    # so try it only as a bonus.
    aa_enabled_flag = _read("/sys/module/apparmor/parameters/enabled")
    if aa_enabled_flag is not None:
        if aa_enabled_flag.strip().upper().startswith("Y"):
            # Module is loaded.  Try aa-status for profile count, but
            # fall back to a positive finding if it can't run.
            details = "apparmor kernel module enabled"
            if _have("aa-status"):
                rc, out, _ = _ro(["aa-status"], timeout=4)
                if rc == 0 and "profiles are loaded" in out:
                    details = out.splitlines()[0] if out else details
            fs.append(Finding("MAC-001", "AppArmor active", "info", details))
            return fs
        else:
            fs.append(Finding("MAC-002", "AppArmor not loaded", "low",
                              "/sys/module/apparmor/parameters/enabled=N"))
            return fs

    # ── SELinux fallback ──────────────────────────────────────────
    if _have("getenforce"):
        rc, out, _ = _ro(["getenforce"])
        mode = out.strip()
        if rc == 0 and mode == "Enforcing":
            fs.append(Finding("MAC-003", "SELinux enforcing", "info",
                              "getenforce: Enforcing"))
        elif rc == 0 and mode:
            fs.append(Finding("MAC-004", f"SELinux mode: {mode}",
                              "low", "SELinux not enforcing"))
        else:
            fs.append(Finding("MAC-005", "No MAC system detected", "low",
                              "AppArmor not loaded, SELinux not reporting"))
    else:
        fs.append(Finding("MAC-005", "No MAC system detected", "low",
                          "No AppArmor or SELinux"))
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
            fs.append(Finding("HIST-001", f"Possible secrets in {hf}",
                              "medium",
                              f"{len(hits)} suspicious line(s) found",
                              fix_hint=f"Review {p}"))
    return fs


AUDIT_CHECKS: List[Tuple[str, str, Callable[[], List[Finding]]]] = [
    ("FW",    "Firewall status",        check_firewall),
    ("NET",   "Listening ports",        check_listening_ports),
    ("SSH",   "SSH server config",      check_ssh_config),
    ("PATCH", "Pending sec updates",    check_pending_updates_audit),
    ("KERN",  "Kernel age",             check_kernel),
    ("AUTH",  "Failed SSH logins",      check_failed_logins),
    ("CRYPT", "Disk encryption",        check_disk_encryption),
    ("PERM",  "Home dir perms",         check_world_writable_home),
    ("MAC",   "AppArmor / SELinux",     check_mac),
    ("HIST",  "Shell history secrets",  check_shell_history),
]


def run_security_audit(
        on_progress: Optional[Callable[[str, int, int], None]] = None
        ) -> Dict[str, Any]:
    t0 = time.time()
    all_findings: List[Finding] = []
    total = len(AUDIT_CHECKS)
    done = 0

    def _safe(fn):
        try:
            return fn() or []
        except Exception:
            return []

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        future_to = {ex.submit(_safe, fn): (cid, title)
                     for cid, title, fn in AUDIT_CHECKS}
        for fut in concurrent.futures.as_completed(future_to, timeout=90):
            cid, title = future_to[fut]
            try:
                all_findings.extend(fut.result())
            except Exception:
                pass
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
    return {"findings": all_findings, "score": score, "grade": grade,
            "elapsed": time.time() - t0}


def format_audit_for_chat(audit: Dict[str, Any]) -> str:
    findings: List[Finding] = audit["findings"]
    sev_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    findings = sorted(findings, key=lambda f: (sev_rank[f.severity],
                                                f.check_id))
    lines = [f"## Security audit — grade **{audit['grade']}** "
             f"(score {audit['score']}, {audit['elapsed']:.1f}s)", ""]
    counts: Dict[str, int] = {}
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1
    lines.append("Findings: " +
                 ", ".join(f"{n} {s}" for s, n in counts.items()))
    lines.append("")
    for f in findings:
        lines.append(f"- `{f.severity.upper():8s}` **{f.title}** ({f.check_id})")
        if f.evidence:
            lines.append(f"  > {f.evidence}")
        if f.fix_hint:
            lines.append(f"  - fix: `{f.fix_hint}`")
    return "\n".join(lines)


# ═════════════════════════════════════════════════════════════════════
# NETWORK SCAN
# ═════════════════════════════════════════════════════════════════════

def _detect_local_cidr() -> Optional[str]:
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


def run_network_scan(cidr: Optional[str] = None,
                     on_progress: Optional[Callable[[str], None]] = None
                     ) -> Dict[str, Any]:
    t0 = time.time()
    target = cidr or _detect_local_cidr()
    if not target:
        return {"ok": False, "error": "could not detect local subnet"}
    if on_progress:
        on_progress(f"scanning {target}...")
    hosts: List[Dict[str, Any]] = []
    if _have("nmap"):
        rc, out, err = _ro(["nmap", "-sn", "-T4", "-n", target], timeout=60)
        if rc != 0:
            return {"ok": False, "error": f"nmap failed: {err.strip()}"}
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
        rc, out, _ = _ro(["ip", "neigh"])
        if rc == 0:
            for line in out.splitlines():
                m = re.match(r'(\d+\.\d+\.\d+\.\d+).*lladdr\s+(\S+)', line)
                if m:
                    hosts.append({"ip": m.group(1), "mac": m.group(2),
                                  "vendor": None})
    return {"ok": True, "target": target, "hosts": hosts,
            "elapsed": time.time() - t0,
            "scanner": "nmap" if _have("nmap") else "ip-neigh"}


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
# TOOL CALL PARSING
# ═════════════════════════════════════════════════════════════════════

# Permissive matcher.  Accepts every shape the model has been seen to
# emit:
#   <tool name="X">{json}</tool>          — JSON in the body (canonical)
#   <tool>{json with "name"/"tool"}</tool>
#   <tool name="X" json='{json}'></tool>  — JSON in a json= attribute
#   <tool name="X" json='{json}'/>        — self-closing, JSON in attr
# Group 1 = the name attribute (optional).
# Group 2 = the full attribute blob after the tag word (so we can dig a
#           json='...' out of it when the body is empty).
# Group 3 = the body between > and </tool> (may be empty / absent).
# Tolerates: <\/tool> (escaped slash), smart-quote attrs, whitespace,
# and a missing closing tag (self-close or model dropped it).
TOOL_TAG_RE = re.compile(
    r'<tool'
    r'((?:\s+[a-zA-Z_]+\s*=\s*(?:"[^"]*"|\'[^\']*\'|[\u201c\u201d][^\u201c\u201d]*[\u201c\u201d]))*)'  # attrs
    r'\s*(?:/\s*>|>(.*?)(?:<\\?\s*/\s*tool\s*>|$))',
    re.DOTALL | re.IGNORECASE)

# Pull name="..." out of the attribute blob.
_NAME_ATTR_RE = re.compile(
    r'\bname\s*=\s*["\'\u201c\u201d]([a-zA-Z_]+)["\'\u201c\u201d]')
# Pull json='...' / json="..." out of the attribute blob.
_JSON_ATTR_RE = re.compile(
    r'\bjson\s*=\s*(?:"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\')',
    re.DOTALL)

# Also strip stray <tool> openings that never closed (mid-stream artefacts)
TOOL_PARTIAL_RE = re.compile(
    r'<tool(?:\s[^>]*)?>\s*\{?[^<]*$',
    re.DOTALL | re.IGNORECASE)


@dataclass
class ToolCall:
    name: str
    args: Dict[str, Any]
    raw: str


def parse_tool_calls(text: str) -> List[ToolCall]:
    calls: List[ToolCall] = []
    for m in TOOL_TAG_RE.finditer(text):
        attrs = m.group(1) or ""
        body = (m.group(2) or "").strip()

        # name comes from the name="..." attribute
        name_attr = None
        nm = _NAME_ATTR_RE.search(attrs)
        if nm:
            name_attr = nm.group(1)

        # JSON source: prefer the body; fall back to a json='...' attribute
        # (this is the case that produced the on-screen gibberish — the
        # model put the JSON in an attribute and left the body empty).
        json_src = body
        if not json_src:
            jm = _JSON_ATTR_RE.search(attrs)
            if jm:
                json_src = (jm.group(1) or jm.group(2) or "").strip()
                # the attribute value may carry escaped quotes — unescape
                json_src = json_src.replace('\\"', '"').replace("\\'", "'")

        try:
            parsed = json.loads(json_src) if json_src else {}
        except json.JSONDecodeError:
            parsed = {"_raw": json_src}

        # Resolve tool name
        name = name_attr
        if not name and isinstance(parsed, dict):
            for key in ("name", "tool", "tool_name"):
                if key in parsed:
                    name = parsed.pop(key)
                    break
        # Unwrap common nested arg containers
        if isinstance(parsed, dict):
            for inner_key in ("arguments", "args", "parameters", "params"):
                if isinstance(parsed.get(inner_key), dict):
                    parsed = parsed[inner_key]
                    break
        # Default-to-run when there's a cmd/command and no name
        if not name and isinstance(parsed, dict) and (
                "cmd" in parsed or "command" in parsed):
            name = "run"
        # Normalize cmd → command (and lists → joined string)
        if isinstance(parsed, dict) and "cmd" in parsed and "command" not in parsed:
            v = parsed.pop("cmd")
            parsed["command"] = " ".join(v) if isinstance(v, list) else str(v)
        # Normalize reason aliases
        if isinstance(parsed, dict):
            for alt in ("why", "rationale", "purpose"):
                if alt in parsed and "reason" not in parsed:
                    parsed["reason"] = parsed.pop(alt)

        if not name:
            # Couldn't figure out what tool this was — skip; the matched
            # text still gets stripped from display by strip_tool_calls.
            continue
        args = parsed if isinstance(parsed, dict) else {"_raw": parsed}
        calls.append(ToolCall(name=name, args=args, raw=m.group(0)))
    return calls


def strip_tool_calls(text: str) -> str:
    out = TOOL_TAG_RE.sub("", text)
    # Also remove dangling unclosed <tool ...> ... fragments mid-stream
    out = TOOL_PARTIAL_RE.sub("", out)
    return out.strip()


# ═════════════════════════════════════════════════════════════════════
# BACKGROUND WATCHER — periodic system checks, surfaces to UI
# ═════════════════════════════════════════════════════════════════════

class Watcher:
    """Periodic background system observer.
    Generates events that the UI can pop as toasts."""

    def __init__(self, settings: Dict[str, Any],
                 on_event: Callable[[Dict[str, Any]], None]):
        self.settings = settings
        self.on_event = on_event
        self._thread: Optional[threading.Thread] = None
        # Per-thread stop event.  Each new thread gets its own; toggling
        # the watcher off→on rapidly used to leave the old thread running
        # because we cleared a shared event before the old thread had
        # noticed it was set.
        self._thread_stop: Optional[threading.Event] = None
        self._last_update_check = 0.0
        self._last_download_check = 0.0
        self._known_downloads: set = set()

    def start(self):
        if not self.settings.get("watcher_enabled"):
            return
        # Signal any previous thread to wind down — it owns its own event,
        # so we don't disturb the new thread by doing so.
        if self._thread_stop is not None:
            self._thread_stop.set()
        # Don't bother joining; the old thread will exit on its next sleep
        # tick.  A brief overlap is harmless (events are de-duped by the
        # _known_downloads / _last_update_check state on the new thread).
        new_stop = threading.Event()
        self._thread_stop = new_stop
        self._thread = threading.Thread(
            target=self._loop, args=(new_stop,), daemon=True)
        self._thread.start()
        log("watcher started")

    def stop(self):
        if self._thread_stop is not None:
            self._thread_stop.set()
        log("watcher stopping")

    def _loop(self, stop_event: threading.Event):
        # First pass: prime known downloads so we don't spam on startup
        try:
            r = tool_recent_downloads(50)
            if r.get("ok"):
                self._known_downloads = {f["name"] for f in r["files"]}
        except Exception:
            pass

        while not stop_event.is_set():
            try:
                self._tick()
            except Exception as e:
                log(f"watcher tick error: {e}")
            # Re-read interval each cycle so settings changes take effect
            # without an app restart.
            interval = max(60, int(
                self.settings.get("watcher_interval_minutes", 60)) * 60)
            # sleep in small slices so stop is responsive
            for _ in range(interval):
                if stop_event.is_set():
                    return
                time.sleep(1)

    def _tick(self):
        if self.settings.get("watcher_check_downloads"):
            self._check_downloads()
        if self.settings.get("watcher_check_updates"):
            self._check_updates_periodic()
        if self.settings.get("watcher_check_journal"):
            self._check_journal()

    def _check_downloads(self):
        r = tool_recent_downloads(50)
        if not r.get("ok"):
            return
        new_files = []
        current_names = set()
        for f in r["files"]:
            current_names.add(f["name"])
            if f["name"] not in self._known_downloads and not f["is_dir"]:
                if f["age_seconds"] < 3600:  # only flag new in last hour
                    new_files.append(f)
        self._known_downloads = current_names
        if new_files:
            self.on_event({
                "kind": "downloads",
                "title": f"{len(new_files)} new download(s)",
                "detail": ", ".join(f["name"] for f in new_files[:3]),
                "files": new_files,
            })

    def _check_updates_periodic(self):
        # cheap: just count, no apt update
        now = time.time()
        if now - self._last_update_check < 4 * 3600:
            return
        self._last_update_check = now
        r = tool_check_updates()
        if r.get("ok") and r.get("security_count", 0) > 0:
            self.on_event({
                "kind": "security_updates",
                "title": f"{r['security_count']} security updates pending",
                "detail": "Tell me 'install updates' to apply them",
                "count": r["security_count"],
            })

    def _check_journal(self):
        r = tool_journal_tail(lines=100, since="10 minutes ago")
        if not r.get("ok"):
            return
        interesting = []
        for line in r.get("lines", []):
            if "Failed password" in line:
                interesting.append(line)
            elif "USB disconnect" in line or "new high-speed USB device" in line:
                interesting.append(line)
            elif "Out of memory" in line:
                interesting.append(line)
        if interesting:
            self.on_event({
                "kind": "journal",
                "title": f"{len(interesting)} notable event(s)",
                "detail": interesting[0][-120:],
                "lines": interesting,
            })
