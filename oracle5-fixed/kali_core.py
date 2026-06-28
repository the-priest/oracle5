#!/usr/bin/env python3
"""
kali_core — non-UI logic for Kali.

  · Backend abstraction (multiple cloud providers, OpenAI-compatible)
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
EVIDENCE_DIR      = CONFIG_DIR / "evidence"

DATA_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

# ── Evidence ledger ──
# Every command Kali runs is recorded to a tamper-evident JSONL ledger so an
# engagement produces real evidence, not just a chat transcript.  Lazily
# created so importing kali_core stays cheap and a ledger failure can never
# block startup (kali_ledger itself is fail-safe on every call).
_LEDGER = None  # type: ignore


def get_ledger():
    """The process-wide EvidenceLedger singleton (created on first use)."""
    global _LEDGER
    if _LEDGER is None:
        try:
            from kali_ledger import EvidenceLedger
            _LEDGER = EvidenceLedger(base_dir=EVIDENCE_DIR)
        except Exception:
            _LEDGER = None
    return _LEDGER

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

# Default is DeepSeek-V4-Flash (operator choice): newest DeepSeek MoE, 284B
# total / 13B active, 1M context, fast.  V4 replaced V3 on SiliconFlow in
# Apr 2026 — the old deepseek-chat/reasoner aliases retire Jul 2026.  Pro is
# the heavier sibling kept as the first fallback for harder reasoning.
SILICONFLOW_CHAIN = [
    "deepseek-ai/DeepSeek-V4-Flash",
    "deepseek-ai/DeepSeek-V4-Pro",
    "Qwen/Qwen3-235B-A22B-Instruct-2507",
    "moonshotai/Kimi-K2.5",
    "zai-org/GLM-4.6",
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


# UI display order only.  Groq is listed first for historical familiarity,
# but the DEFAULT active provider is SiliconFlow/DeepSeek-V4-Flash — set in
# DEFAULT_SETTINGS["active_provider"] and locked by tests.  Groq is the
# fallback chain, not the default.
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
    # Which cloud provider to use.  Cloud-only build — no local model.
    # SiliconFlow/DeepSeek is the primary; Groq is the fallback chain.
    "active_provider": "siliconflow",

    # Per-provider API key + selected model.  One pair per registered
    # provider; populated from DEFAULT_SETTINGS so a fresh install has
    # every field present.  (Built programmatically below.)

    # Generation
    "temperature": 0.7,
    "top_p": 0.9,
    "num_ctx": 4096,
    "max_tokens": 2048,

    # Behaviour
    "system_prompt": "",
    "agent_mode_default": True,        # Kali defaults to agent on
    # Off by default: a command Kali decides to run executes without a card
    # click.  The hard catastrophic-command backstop (is_catastrophic_command)
    # still forces an explicit confirm for system-destroying commands even
    # when this is off, so "no friction" never means "no floor".
    "confirm_all_commands": False,

    # Watcher
    "watcher_enabled": False,
    "watcher_check_updates": True,
    "watcher_check_downloads": True,
    "watcher_check_journal": False,
    "watcher_interval_minutes": 60,

    # UI
    "theme": "kali",
    "ui_scale": 0,  # 0 = auto-detect; manual values 0.3 to 3.0
    "show_token_count": False,
    "show_provider_pill": True,

    # ── kali_ext sidecar (memory / skills / foresight / headless worker) ──
    # Everything here is OFF by default.  With all of these false, the sidecar
    # injects nothing, spawns no threads, runs no background work, and Kali
    # behaves exactly as a stock build.  Flip them on per feature when you
    # want them — nothing here runs in the background unless you enable it.
    "memory_enabled":          False,   # persistent cross-session recall
    "memory_recall_k":         6,       # how many memories to inject per turn
    "memory_consolidate":      False,   # model-based fact extraction (costs a call)
    "skills_enabled":          False,   # self-written, sandbox-tested skills
    "foresight_enabled":       False,   # predict consequences before acting
    "foresight_model":         False,   # add a model pass on top of the rules
    "mcp_enabled":             False,   # connect external MCP tool servers (OFF
                                        # by default — MCP is an RCE surface;
                                        # tool args are safety-screened + logged)
    "mcp_servers":             [],      # list of {name, command, args, env, cwd}
    "chat_render_images":      True,    # fetch & show images inline in chat
                                        # (off → image links shown as text;
                                        # turn off for OPSEC / no host contact)
    "worker_enabled":          False,   # the headless systemd --user companion
    "worker_interval_seconds": 300,     # worker poll cadence (when enabled)
    "one_command_at_a_time":   True,    # never propose/run >1 command per message
    # ── Self-improvement behaviours ──
    "warn_duplicate_commands": False,   # warn when re-running the same cmd <10m
    "auto_fallback_on_degraded": False, # hop provider if a reply comes back junk
    "urgency_fast_path":       True,    # skip preamble when the operator is urgent
    "auto_sudo_when_cached":   True,    # silently use sudo if already authenticated

    # ── Voice (speech in / speech out) ──
    # Voice input transcribes through Groq's Whisper endpoint (reuses the
    # Groq key).  Voice output prefers Piper (local neural voice) and
    # falls back to espeak-ng.  All optional; off until you turn it on.
    "tts_enabled":      False,          # read assistant replies aloud
    "tts_engine":       "auto",         # auto | piper | espeak
    "tts_voice":        "",             # path to a Piper .onnx (blank = auto-find)
    "tts_voice_espeak": "",             # espeak voice id, e.g. "en-gb" (blank = default)
    "tts_rate":         1.0,            # 0.5 (slow) .. 2.0 (fast); 1.0 = normal
    "voice_autosend":   True,           # auto-send after a voice message transcribes
    "stt_model":        "whisper-large-v3-turbo",
    "stt_language":     "",             # ISO-639-1 hint (blank = auto-detect)
    # Which cloud transcribes voice input.  "auto" = use your active chat
    # provider if it supports speech (SiliconFlow→SenseVoiceSmall,
    # Groq→Whisper), else fall back to whichever key you have set.
    "stt_provider":     "auto",         # auto | siliconflow | groq
    "stt_model_siliconflow": "",         # blank = FunAudioLLM/SenseVoiceSmall

    # ── Chat history / retention ──
    # Ephemeral by default: start fresh each launch, roll off stale chats,
    # and never keep abandoned empty placeholders.  Pinned chats are always
    # exempt from auto-deletion.
    "ephemeral_new_chat_on_launch": True,   # open a new chat at every launch
    "chat_retention_hours":         24,     # delete chats idle > N hours (0 = keep)
    "discard_empty_chats":          True,   # bin unused 'New chat' placeholders

    # ── GitHub ──
    # Optional Personal Access Token for the `github` tool.  Blank = public,
    # unauthenticated access (60 req/hr, public repos only).  Set a token to
    # reach your private repos and raise the limit to 5000 req/hr.  Also read
    # from the GITHUB_TOKEN env var if this is blank.
    "github_token": "",

    # ── Headroom context compression ──
    # Crush big <tool_result> dumps (nmap, recon, journal, web reads, JSON)
    # before they go to the model — same answers, a fraction of the tokens.
    # Uses the real `headroom-ai` package if installed, else a built-in
    # stdlib fallback (so it works on every device).  System prompt and your
    # own messages are NEVER touched; the most-recent N tool results stay
    # full.  On by default; harmless when there's nothing big to compress.
    "headroom_enabled":        True,    # master switch for compression
    "headroom_min_chars":      1200,    # don't compress a block under this size
    "headroom_keep_recent":    2,       # leave the last N tool results full
    "headroom_target_ratio":   0.35,    # fallback engine: keep ~this fraction

    # ── Verification / anti-propaganda ──
    # When she looks something up with web_verify, how many INDEPENDENT
    # sources to gather and cross-check before answering.
    "verify_max_sources":      5,

    # Click-to-open "Thoughts" panel on a reply, shown when the model
    # exposes its reasoning (a reasoning_content stream or inline <think>).
    "show_thoughts":           True,
}

# Add a key + model slot for every registered provider so the schema is
# always complete (e.g. "groq_api_key", "groq_model", "novita_api_key"…).
# Also record each provider's base_url — voice transcription derives its
# endpoint from this, so STT always rides the same host chat uses.
for _p in PROVIDERS:
    DEFAULT_SETTINGS.setdefault(f"{_p.key}_api_key", "")
    DEFAULT_SETTINGS.setdefault(f"{_p.key}_model", _p.default_model)
    DEFAULT_SETTINGS.setdefault(f"{_p.key}_base_url", _p.base_url)


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
    # Older builds may carry prefer_groq / prefer_cloud / local-model keys;
    # they're harmless leftovers now (cloud-only) and simply ignored.
    # If active_provider is missing entirely, this is a pre-multi-provider
    # (Groq-only) install — keep Groq so the operator's working setup isn't
    # disrupted on upgrade.  A genuinely fresh install never reaches here; it
    # gets the SiliconFlow default straight from DEFAULT_SETTINGS.
    if "active_provider" not in raw:
        merged["active_provider"] = "groq"
    # Guard against an active_provider that no longer exists in the
    # registry (e.g. a renamed/removed provider) — fall back to the locked
    # primary, SiliconFlow.
    if merged.get("active_provider") not in PROVIDERS_BY_KEY:
        merged["active_provider"] = "siliconflow"


def save_settings(settings: Dict[str, Any]) -> None:
    # Atomic write: temp file in same directory, then os.replace.  Without
    # this, a crash mid-write would leave settings.json truncated or empty
    # and the next load would silently fall back to defaults — wiping the
    # operator's API keys, model selection, etc.
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
    # Try DNS (53) first, then HTTPS (443) on the same resolvers — some
    # restrictive networks block outbound 53 but allow 443, and a 53-only
    # check would wrongly report "offline" there.
    for host, port in (("1.1.1.1", 53), ("8.8.8.8", 53),
                       ("1.1.1.1", 443), ("8.8.8.8", 443)):
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
# BACKENDS — cloud providers (OpenAI-compatible) with a router
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
                    cancel_event: Optional[threading.Event] = None,
                    on_reasoning: Optional[Callable[[str], None]] = None
                    ) -> None: ...


class GroqBackend:
    name = "groq"

    def __init__(self, api_key: str = "",
                 fallback_chain: List[str] = None):
        self.api_key = (api_key or "").strip()
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
        self.api_key = (key or "").strip()
        self._build_client()

    def is_available(self) -> bool:
        return GROQ_LIB_OK and bool(self._client) and is_online()

    def list_models(self) -> List[Dict[str, Any]]:
        return [{"name": m} for m in self.fallback_chain]

    def stream_chat(self, model, messages, on_token, on_done, on_error,
                    options=None, cancel_event=None, on_reasoning=None) -> None:
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
                    rtok = (getattr(delta, "reasoning_content", None)
                            or getattr(delta, "reasoning", None) or "")
                    if rtok and on_reasoning:
                        on_reasoning(rtok)
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
    just urllib + Server-Sent-Events parsing, no extra dependencies.
    Mirrors GroqBackend's behaviour: biggest-model-first fallback chain,
    and a hard stop on mid-stream fallback so two models' output never
    gets spliced together on screen.
    """

    def __init__(self, spec: "ProviderSpec", api_key: str = ""):
        self.spec = spec
        self.name = spec.key
        self.api_key = (api_key or "").strip()
        self.base_url = spec.base_url
        self.fallback_chain = list(spec.chain)
        self.extra_headers = dict(spec.extra_headers or {})

    def set_api_key(self, key: str) -> None:
        # Strip whitespace/newlines — pasting a key on mobile often appends
        # a trailing space or newline, which then rides along in the
        # Authorization header and makes the provider reject a key that
        # looks correct in the Settings field.
        self.api_key = (key or "").strip()

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
                    options=None, cancel_event=None, on_reasoning=None) -> None:
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
                        rtok = (delta.get("reasoning_content")
                                or delta.get("reasoning") or "")
                        if rtok and on_reasoning:
                            on_reasoning(rtok)
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

                # AUTH FIRST.  A missing/invalid key must stop immediately —
                # never walk the model chain (that produced the bogus
                # "exhausted all models" message).  Some providers signal a
                # bad key with 401/403; others (GitHub, Google) use 400/404
                # with an auth message in the body — catch those too.
                low = (detail or "").lower()
                auth_words = ("api key", "api_key", "apikey", "unauthorized",
                              "permission", "invalid authentication",
                              "invalid key", "forbidden", "credential",
                              "token", "must provide")
                if e.code in (401, 403) or (
                        e.code in (400, 404) and any(w in low for w in auth_words)):
                    on_error(f"{self.name}: authentication failed "
                             f"(HTTP {e.code}). Check the API key for this "
                             f"provider in Settings → Backends.")
                    return

                # 400/404 with no auth hint → maybe a stale model id.  Pull
                # the live catalogue ONCE and retry with real models.
                if e.code in (404, 400) and not recovered_live:
                    recovered_live = True
                    live = self.list_models_live()
                    new = [m for m in live if m not in order]
                    if new:
                        log(f"{self.name} {attempt_model} -> {e.code}; "
                            f"recovered {len(new)} live models")
                        order.extend(new)
                        continue
                    # No live models came back either — almost always the
                    # key is bad/empty.  Stop, don't churn the chain.
                    on_error(f"{self.name}: request rejected (HTTP {e.code}) "
                             f"and no models could be listed — the API key is "
                             f"probably missing or invalid. Check Settings → "
                             f"Backends.")
                    return

                # 429 = rate limit on THIS model → genuinely worth the next.
                if e.code == 429:
                    log(f"{self.name} {attempt_model} -> 429 rate-limit, next")
                    continue
                if e.code in (502, 503):
                    log(f"{self.name} {attempt_model} -> {e.code}, next")
                    continue

                # Anything else: report and stop.
                on_error(f"{self.name}: {last_err}")
                return
            except urllib.error.URLError as e:
                # Network/DNS/SSL failure — applies to every model equally,
                # so retrying the chain is pointless.  Stop and report.
                reason = getattr(e, "reason", e)
                on_error(f"{self.name}: connection failed ({reason}). "
                         f"Check your internet connection.")
                return
            except Exception as e:
                # Unexpected error (parse, SSL, library bug).  Do NOT silently
                # walk the rest of the chain — that hid the real cause and
                # produced the false 'exhausted all models'.  Report and stop.
                on_error(f"{self.name}: {type(e).__name__}: {str(e)[:200]}")
                return

        # We only reach here if every model in the chain returned 429/5xx.
        on_error(f"{self.name}: all models are rate-limited or unavailable "
                 f"right now ({last_err}). Try again shortly or switch "
                 f"provider in Settings.")


class BackendRouter:
    """Routes to the active cloud provider.  Cloud-only — there is no
    local backend.  Holds one backend per registered cloud provider and
    picks the one named by settings['active_provider']."""

    def __init__(self, cloud: Dict[str, Backend], settings: Dict[str, Any]):
        self.cloud = cloud            # {provider_key: backend}
        self.settings = settings
        # Back-compat alias.
        self.groq = cloud.get("groq")

    def active_cloud(self) -> Tuple[Optional[Backend], str]:
        """Return (backend, provider_key) for the configured active
        provider, falling back to the locked primary (SiliconFlow) if the
        configured one is missing."""
        key = self.settings.get("active_provider", "siliconflow")
        backend = self.cloud.get(key)
        if backend is None:
            key = "siliconflow"
            backend = self.cloud.get(key)
            if backend is None:        # SiliconFlow somehow absent — last resort
                backend = self.cloud.get("groq")
                key = "groq"
        return backend, key

    def pick(self) -> Tuple[Optional[Backend], str]:
        """Returns (backend, model_name).  backend may be None if the
        active provider has no key configured."""
        backend, key = self.active_cloud()
        model = self.settings.get(
            f"{key}_model",
            PROVIDERS_BY_KEY[key].default_model
            if key in PROVIDERS_BY_KEY else "")
        return backend, model

    def any_available(self) -> bool:
        """True if at least the active provider is usable right now."""
        backend, _ = self.active_cloud()
        return backend is not None and backend.is_available()

    def stream_chat(self, messages, on_token, on_done, on_error,
                    cancel_event=None, on_reasoning=None) -> Tuple[str, str]:
        backend, model = self.pick()
        opts = {
            "temperature": self.settings.get("temperature", 0.7),
            "top_p": self.settings.get("top_p", 0.9),
            "max_tokens": self.settings.get("max_tokens", 2048),
        }
        if backend is None:
            on_error("No provider configured. Add an API key in Settings.")
            return "none", ""
        # ── Headroom: compress bulky tool-result envelopes before they hit
        #    the model. Fully optional, fail-open: any error => original list.
        #    The module does its own logging of how much it saved.
        if self.settings.get("headroom_enabled", True):
            try:
                from kali_ext import headroom as _headroom
                messages, _ = _headroom.compress_messages(
                    messages, self.settings, log)
            except Exception as _e:
                log(f"headroom: skipped ({_e})")
        backend.stream_chat(model, messages, on_token, on_done, on_error,
                            opts, cancel_event, on_reasoning=on_reasoning)
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
CREATE INDEX IF NOT EXISTS idx_chats_pinned_updated ON chats(pinned, updated_at);
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

    def update_message_meta(self, msg_id: int,
                            meta: Optional[Dict[str, Any]]) -> None:
        """Replace the JSON meta blob for one message (used to attach the
        model's captured reasoning/'thoughts' once a turn finishes)."""
        meta_s = json.dumps(meta) if meta else None
        with self._lock:
            self._db.execute("UPDATE messages SET meta=? WHERE id=?",
                             (meta_s, msg_id))

    def count_messages_by_role(self, chat_id: int, role: str) -> int:
        """Cheap count for first-message detection — avoids re-fetching all."""
        with self._lock:
            row = self._db.execute(
                "SELECT COUNT(*) FROM messages WHERE chat_id=? AND role=?",
                (chat_id, role)).fetchone()
        return row[0] if row else 0

    def count_messages(self, chat_id: int) -> int:
        """Total message count for a chat — used to detect unused chats
        without allocating every row."""
        with self._lock:
            row = self._db.execute(
                "SELECT COUNT(*) FROM messages WHERE chat_id=?",
                (chat_id,)).fetchone()
        return row[0] if row else 0

    def purge_old_chats(self, max_age_seconds: float,
                        keep_chat_id: Optional[int] = None) -> int:
        """Delete unpinned chats idle longer than the cutoff (by last
        activity).  Never touches pinned chats or `keep_chat_id`.
        Cascades to their messages.  Returns how many were removed."""
        if max_age_seconds <= 0:
            return 0
        cutoff = time.time() - max_age_seconds
        keep = keep_chat_id if keep_chat_id is not None else -1
        with self._lock:
            cur = self._db.execute(
                "DELETE FROM chats WHERE pinned=0 AND updated_at < ? "
                "AND id != ?", (cutoff, keep))
            return cur.rowcount or 0

    def purge_empty_chats(self, keep_chat_id: Optional[int] = None) -> int:
        """Delete unpinned chats that hold no messages at all (abandoned
        'New chat' placeholders).  Returns how many were removed."""
        keep = keep_chat_id if keep_chat_id is not None else -1
        with self._lock:
            cur = self._db.execute(
                "DELETE FROM chats WHERE pinned=0 AND id != ? AND id NOT IN "
                "(SELECT DISTINCT chat_id FROM messages)", (keep,))
            return cur.rowcount or 0


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
        # Decide text-vs-binary by content, not by whether a strict UTF-8
        # decode happens to succeed.  Reading a capped prefix can slice a
        # multi-byte character at the boundary, which would make a perfectly
        # ordinary text file raise UnicodeDecodeError and get mislabelled as
        # binary.  A NUL byte is the reliable binary signal; for text we decode
        # leniently so a clipped trailing character becomes one replacement
        # char instead of losing the whole file.
        if b"\x00" in raw:
            text = raw[:1024].hex()
            kind = "binary (hex preview)"
        else:
            text = raw.decode("utf-8", errors="replace")
            kind = "text"
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


# ── Catastrophic-command & self-tamper backstops ─────────────────────
# These two hard, setting-independent floors on the auto-run gate now live in
# kali_safety.py, where they are *structural* (shlex-tokenised, $IFS/quote
# normalised, recursing into `sh -c` / eval payloads) rather than a raw-string
# regex — so trivial obfuscation (rm '-rf' /, rm${IFS}-rf${IFS}/, cd / && rm
# -rf *, find / -delete, bash -c "...", base64|sh) can't slip a system-
# destroying or guardrail-stripping command through.  They are imported and
# re-exported here so every existing `from kali_core import ...` keeps working.
# Both stay deliberately narrow: normal offensive-security work (nmap, nuclei,
# sqlmap, hydra) and file ops in your own dirs do not trip them.  See the full
# catch/ignore matrix in tests/test_kali.py.
from kali_safety import (              # noqa: E402
    is_catastrophic_command,
    command_tampers_self,
)


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
                   max_results: int = 50,
                   min_size_kb: float = 0,
                   max_size_kb: float = 0,
                   modified_within_days: float = 0) -> Dict[str, Any]:
    """Find files by name pattern, with optional size and modified-time
    filters.  min_size_kb/max_size_kb bound file size; modified_within_days
    limits to files changed in the last N days.  Returns each hit with its
    size and mtime so callers can summarise rather than dump raw paths."""
    if not _have("find"):
        return {"ok": False, "error": "find not available"}
    rp = os.path.expanduser(search_path)
    if not os.path.isdir(rp):
        return {"ok": False, "error": f"not a directory: {search_path}"}
    cmd = ["find", rp, "-type", "f", "-name", pattern]
    try:
        if min_size_kb and float(min_size_kb) > 0:
            cmd += ["-size", f"+{int(float(min_size_kb))}k"]
        if max_size_kb and float(max_size_kb) > 0:
            cmd += ["-size", f"-{int(float(max_size_kb))}k"]
        if modified_within_days and float(modified_within_days) > 0:
            # -mtime -N = modified within the last N*24h
            cmd += ["-mtime", f"-{int(float(modified_within_days))}"]
    except (TypeError, ValueError):
        pass
    rc, out, err = _ro(cmd, timeout=30)
    if rc == 124:
        return {"ok": False, "error": "find timed out after 30s — "
                                       "narrow the search path or pattern",
                "partial": out.splitlines()[:max_results]}
    all_lines = [ln for ln in out.splitlines() if ln]
    paths = all_lines[:max_results]
    found = []
    for p in paths:
        info = {"path": p}
        try:
            st = os.stat(p)
            info["size"] = st.st_size
            info["mtime"] = datetime.datetime.fromtimestamp(
                st.st_mtime).isoformat(timespec="seconds")
        except Exception:
            pass
        found.append(info)
    return {"ok": True, "pattern": pattern, "search_path": rp,
            "filters": {"min_size_kb": min_size_kb,
                        "max_size_kb": max_size_kb,
                        "modified_within_days": modified_within_days},
            "found": found, "count": len(found),
            "truncated": len(all_lines) > max_results}


# ═════════════════════════════════════════════════════════════════════
# SELF-IMPROVEMENT HELPERS
# Small, pure, dependency-free utilities backing the operator's backlog:
# cached system facts, sudo-state detection, urgency parsing, degraded-
# response detection, and command de-duplication.  Kept here (not the GUI)
# so they're unit-testable and reusable by the background worker too.
# ═════════════════════════════════════════════════════════════════════

# ── (#2) Cache common system facts for a short TTL so back-to-back
#         questions ("what's my IP / uptime / free space") don't re-scan. ──
_FACTS_CACHE: Dict[str, Any] = {"ts": 0.0, "data": None}
FACTS_TTL_S = 60


def quick_facts(force: bool = False) -> Dict[str, Any]:
    """Cheap, cached snapshot: hostname, primary IP, uptime, load, and
    root-filesystem free space.  Cached for FACTS_TTL_S seconds."""
    now = time.time()
    if (not force and _FACTS_CACHE["data"] is not None
            and now - _FACTS_CACHE["ts"] < FACTS_TTL_S):
        cached = dict(_FACTS_CACHE["data"])
        cached["cached"] = True
        cached["age_s"] = round(now - _FACTS_CACHE["ts"], 1)
        return cached

    data: Dict[str, Any] = {"ok": True, "cached": False, "age_s": 0.0}
    try:
        data["hostname"] = socket.gethostname()
    except Exception:
        data["hostname"] = ""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("10.255.255.255", 1))
            data["ip"] = s.getsockname()[0]
        finally:
            s.close()
    except Exception:
        data["ip"] = ""
    try:
        with open("/proc/uptime") as f:
            up = float(f.read().split()[0])
        h, rem = divmod(int(up), 3600)
        data["uptime"] = f"{h}h {rem // 60}m"
    except Exception:
        data["uptime"] = ""
    try:
        data["load"] = os.getloadavg()
    except Exception:
        data["load"] = None
    try:
        du = shutil.disk_usage("/")
        data["disk_free_gb"] = round(du.free / 1e9, 1)
        data["disk_total_gb"] = round(du.total / 1e9, 1)
        data["disk_pct_used"] = round(
            100 * (du.total - du.free) / du.total, 1)
    except Exception:
        pass

    _FACTS_CACHE["ts"] = now
    _FACTS_CACHE["data"] = {k: v for k, v in data.items()
                            if k not in ("cached", "age_s")}
    return data


# ── (#9) Is a sudo credential already cached this session? ──
def sudo_cached() -> bool:
    """True if `sudo` would run without prompting (a fresh timestamp exists).
    Lets the host auto-prepend sudo when already authenticated, or warn
    'will need your password' when not.  Never itself prompts."""
    if not _have("sudo"):
        return False
    try:
        r = subprocess.run(["sudo", "-n", "true"],
                           stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=3)
        return r.returncode == 0
    except Exception:
        return False


# ── (#3) Urgency detection on the operator's message ──
_URGENCY_WORDS = ("urgent", "asap", "immediately", "emergency",
                  "fix this", "right now", " now!", "hurry", "stop",
                  "broken", "is down", "crashed", "not working")


def detect_urgency(message: str) -> Dict[str, Any]:
    """Scan the start of a message for urgency markers.  Returns
    {urgent, score, markers} so the host can skip preamble and go straight
    to the most likely fix."""
    head = (message or "")[:80]
    low = head.lower()
    markers = []
    score = 0
    for w in _URGENCY_WORDS:
        if w in low:
            markers.append(w)
            score += 2
    letters = [c for c in head if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) > 0.7 \
            and len(letters) >= 4:
        markers.append("ALLCAPS")
        score += 2
    if head.count("!") >= 1:
        markers.append("exclamation")
        score += 1
    return {"urgent": score >= 2, "score": score, "markers": markers}


# ── (#7) Detect a degraded / junk model response ──
def looks_degraded(text: str) -> bool:
    """Heuristic: is this assistant turn empty, near-empty, or stuck
    repeating?  Used to trigger a provider fallback for the NEXT turn."""
    t = (text or "").strip()
    if len(t) < 2:
        return True
    words = t.split()
    if len(words) >= 8:
        uniq = len(set(w.lower() for w in words))
        if uniq <= max(2, len(words) // 10):
            return True
        if len(set(words[-6:])) == 1:
            return True
    if len(t) >= 12 and len(set(t)) <= 2:
        return True
    return False


# ── (#4) Command de-duplication ──
_CMD_LOG: List[Tuple[str, float]] = []


def note_command(cmd: str) -> None:
    """Record that a command was approved/run, for duplicate detection."""
    c = (cmd or "").strip()
    if not c:
        return
    _CMD_LOG.append((c, time.time()))
    if len(_CMD_LOG) > 50:
        del _CMD_LOG[:-50]


def recent_duplicate(cmd: str, window_s: float = 600) -> bool:
    """True if this exact command was already approved within window_s."""
    c = (cmd or "").strip()
    if not c:
        return False
    now = time.time()
    return any(prev == c and (now - ts) <= window_s
               for prev, ts in _CMD_LOG)


# ═════════════════════════════════════════════════════════════════════
# DESKTOP CONTROL — launch apps, list/focus/close windows, type & click
#
# These give Kali hands on the running desktop.  They degrade based on
# what's installed: app launching works anywhere with gtk-launch / the
# binary on PATH; window + input control needs a helper for the active
# session type.  We detect Wayland vs X11 and pick the right backend:
#   • Wayland + Phosh/wlroots → wtype, wlrctl (and ydotool if present)
#   • X11                     → xdotool, wmctrl
# Each tool reports clearly when the needed helper is missing rather
# than silently doing nothing.
# ═════════════════════════════════════════════════════════════════════

def _session_type() -> str:
    """Return 'wayland', 'x11', or 'unknown' for the current session."""
    st = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if st in ("wayland", "x11"):
        return st
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    return "unknown"


def _desktop_env() -> str:
    """Return a lowercase desktop-environment hint: 'kde', 'gnome',
    'phosh', 'xfce', etc., or '' if unknown.  Used to pick the most
    native helper (e.g. Spectacle/kdialog on KDE)."""
    for var in ("XDG_CURRENT_DESKTOP", "XDG_SESSION_DESKTOP",
                "DESKTOP_SESSION"):
        v = os.environ.get(var, "").lower()
        if not v:
            continue
        if "kde" in v or "plasma" in v:
            return "kde"
        if "gnome" in v:
            return "gnome"
        if "phosh" in v:
            return "phosh"
        if "xfce" in v:
            return "xfce"
        if v:
            return v.split(":")[0]
    return ""


def tool_desktop_info() -> Dict[str, Any]:
    """Report what desktop-control capabilities are available so the
    model can choose tools that will actually work on this box."""
    sess = _session_type()
    de = _desktop_env()
    helpers = {
        "gtk-launch": _have("gtk-launch"),
        "xdg-open": _have("xdg-open"),
        "xdotool": _have("xdotool"),
        "wmctrl": _have("wmctrl"),
        "wtype": _have("wtype"),
        "wlrctl": _have("wlrctl"),
        "ydotool": _have("ydotool"),
        "grim": _have("grim"),
        "slurp": _have("slurp"),
        "scrot": _have("scrot"),
        "import": _have("import"),       # ImageMagick screenshot
        "spectacle": _have("spectacle"),  # KDE screenshot
        "tesseract": _have("tesseract"),  # OCR for screen reading
        "playerctl": _have("playerctl"),
        "kdialog": _have("kdialog"),      # KDE native dialogs
        "qdbus": _have("qdbus") or _have("qdbus6") or _have("qdbus-qt6"),
        "kreadconfig5": _have("kreadconfig5") or _have("kreadconfig6"),
    }
    can_type = (sess == "wayland" and (helpers["wtype"] or helpers["ydotool"])) \
        or (sess == "x11" and helpers["xdotool"])
    can_window = (sess == "wayland" and helpers["wlrctl"]) \
        or (sess == "x11" and (helpers["wmctrl"] or helpers["xdotool"]))
    can_shot = (helpers["grim"] or helpers["scrot"] or helpers["import"]
                or helpers["spectacle"])
    return {
        "ok": True,
        "session": sess,
        "desktop": de or "unknown",
        "helpers": helpers,
        "can_launch_apps": helpers["gtk-launch"] or helpers["xdg-open"],
        "can_type_and_click": can_type,
        "can_control_windows": can_window,
        "can_screenshot": can_shot,
        "can_read_screen": can_shot and helpers["tesseract"],
        "notes": ("KDE Plasma on X11 detected — full desktop control "
                  "available via xdotool/wmctrl; Spectacle/kdialog used "
                  "where they're better." if de == "kde" and sess == "x11"
                  else ""),
    }


def tool_list_apps(filter_text: str = "") -> Dict[str, Any]:
    """List installed GUI applications (from .desktop files).  Optional
    case-insensitive substring filter on name or desktop-id."""
    seen: Dict[str, Dict[str, str]] = {}
    search_dirs = [
        os.path.expanduser("~/.local/share/applications"),
        "/usr/share/applications",
        "/usr/local/share/applications",
        "/var/lib/flatpak/exports/share/applications",
        os.path.expanduser(
            "~/.local/share/flatpak/exports/share/applications"),
    ]
    ft = filter_text.lower().strip()
    for d in search_dirs:
        if not os.path.isdir(d):
            continue
        try:
            for fn in os.listdir(d):
                if not fn.endswith(".desktop"):
                    continue
                desktop_id = fn[:-len(".desktop")]
                if desktop_id in seen:
                    continue
                name, no_display = desktop_id, False
                try:
                    with open(os.path.join(d, fn), "r",
                              encoding="utf-8", errors="replace") as f:
                        for line in f:
                            if line.startswith("Name=") and name == desktop_id:
                                name = line[5:].strip()
                            elif line.strip() == "NoDisplay=true":
                                no_display = True
                except Exception:
                    pass
                if no_display:
                    continue
                if ft and ft not in name.lower() and ft not in desktop_id.lower():
                    continue
                seen[desktop_id] = {"id": desktop_id, "name": name}
        except Exception:
            continue
    apps = sorted(seen.values(), key=lambda a: a["name"].lower())
    return {"ok": True, "count": len(apps), "apps": apps[:200],
            "truncated": len(apps) > 200}


def tool_launch_app(app: str, args: str = "") -> Dict[str, Any]:
    """Launch a desktop application by .desktop id, binary name, or URI.

    Detached from Kali (start_new_session) so closing Kali doesn't kill
    it.  Tries, in order: gtk-launch with a desktop id, the binary on
    PATH, then xdg-open (handles URLs, files, and mime-typed targets).
    """
    app = (app or "").strip()
    if not app:
        return {"ok": False, "error": "no app specified"}
    extra = args.split() if args else []

    def _spawn(argv):
        env = dict(os.environ)
        subprocess.Popen(argv, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True, env=env)

    # URL or existing path → xdg-open is the most reliable route
    is_uri = "://" in app or app.startswith(("mailto:", "tel:"))
    is_path = os.path.exists(os.path.expanduser(app))
    try:
        if is_uri or is_path:
            target = os.path.expanduser(app) if is_path else app
            if _have("xdg-open"):
                _spawn(["xdg-open", target])
                return {"ok": True, "launched": target, "via": "xdg-open"}
            return {"ok": False, "error": "xdg-open not available"}

        # desktop id (strip a trailing .desktop if the model included it)
        desktop_id = app[:-8] if app.endswith(".desktop") else app
        if _have("gtk-launch"):
            # gtk-launch only works for known desktop ids; verify-ish by
            # trying and catching the immediate failure.
            rc, _o, err = _ro(["gtk-launch", desktop_id], timeout=4)
            # gtk-launch returns 0 even when it forks the app; a clearly
            # unknown id prints an error and returns non-zero quickly.
            if rc == 0:
                return {"ok": True, "launched": desktop_id, "via": "gtk-launch"}

        # fall back to treating it as a binary on PATH
        binary = app.split()[0]
        if _have(binary):
            _spawn([binary] + extra)
            return {"ok": True, "launched": binary, "via": "exec"}

        # last resort: xdg-open the bare string (may resolve a protocol)
        if _have("xdg-open"):
            _spawn(["xdg-open", app])
            return {"ok": True, "launched": app, "via": "xdg-open"}

        return {"ok": False,
                "error": f"could not launch '{app}': no matching desktop "
                         f"entry, binary on PATH, or opener"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def tool_list_windows() -> Dict[str, Any]:
    """List open windows (title + app id) for focusing/closing.

    X11 uses wmctrl; Wayland uses wlrctl (wlroots/Phosh).  Returns a
    clear error if neither helper is present."""
    sess = _session_type()
    if sess == "x11" and _have("wmctrl"):
        rc, out, _ = _ro(["wmctrl", "-l"], timeout=5)
        wins = []
        for line in out.splitlines():
            parts = line.split(None, 3)
            if len(parts) >= 4:
                wins.append({"id": parts[0], "title": parts[3]})
        return {"ok": True, "session": sess, "windows": wins}
    if sess == "wayland" and _have("wlrctl"):
        rc, out, _ = _ro(["wlrctl", "window", "list"], timeout=5)
        wins = [{"title": ln.strip()} for ln in out.splitlines() if ln.strip()]
        return {"ok": True, "session": sess, "windows": wins}
    return {"ok": False,
            "error": f"no window-list helper for {sess} session "
                     f"(install wmctrl on X11, or wlrctl on Wayland)"}


def tool_focus_window(title: str) -> Dict[str, Any]:
    """Bring a window matching `title` (substring) to the front."""
    sess = _session_type()
    if sess == "x11" and _have("wmctrl"):
        rc, _o, err = _ro(["wmctrl", "-a", title], timeout=5)
        if rc == 0:
            return {"ok": True, "focused": title}
        return {"ok": False, "error": err or f"no window matching '{title}'"}
    if sess == "wayland" and _have("wlrctl"):
        rc, _o, err = _ro(["wlrctl", "window", "focus", title], timeout=5)
        if rc == 0:
            return {"ok": True, "focused": title}
        return {"ok": False, "error": err or f"no window matching '{title}'"}
    return {"ok": False,
            "error": f"no window-control helper for {sess} session"}


def tool_close_window(title: str) -> Dict[str, Any]:
    """Gracefully close a window matching `title` (substring)."""
    sess = _session_type()
    if sess == "x11" and _have("wmctrl"):
        rc, _o, err = _ro(["wmctrl", "-c", title], timeout=5)
        if rc == 0:
            return {"ok": True, "closed": title}
        return {"ok": False, "error": err or f"no window matching '{title}'"}
    if sess == "wayland" and _have("wlrctl"):
        rc, _o, err = _ro(["wlrctl", "window", "close", title], timeout=5)
        return {"ok": rc == 0, "closed": title if rc == 0 else None,
                "error": err if rc else None}
    return {"ok": False,
            "error": f"no window-control helper for {sess} session"}


def tool_notify(message: str, title: str = "Kali") -> Dict[str, Any]:
    """Pop a desktop notification — useful to ping the operator when a
    long task finishes.  Prefers notify-send (works on KDE/GNOME/etc.),
    falls back to kdialog --passivepopup on KDE."""
    if not message:
        return {"ok": False, "error": "no message"}
    if _have("notify-send"):
        rc, _o, err = _ro(["notify-send", title, message], timeout=5)
        if rc == 0:
            return {"ok": True, "notified": message, "via": "notify-send"}
    if _have("kdialog"):
        rc, _o, err = _ro(
            ["kdialog", "--title", title, "--passivepopup", message, "6"],
            timeout=5)
        if rc == 0:
            return {"ok": True, "notified": message, "via": "kdialog"}
    return {"ok": False,
            "error": "no notifier (install libnotify-bin for notify-send)"}


def tool_type_text(text: str) -> Dict[str, Any]:
    """Type a string into the focused window as synthetic keystrokes.

    Wayland: wtype (or ydotool).  X11: xdotool.  This is how Kali fills
    fields in apps that aren't a browser (the browser has its own tool).
    """
    if not text:
        return {"ok": False, "error": "no text"}
    sess = _session_type()
    if sess == "wayland":
        if _have("wtype"):
            rc, _o, err = _ro(["wtype", text], timeout=15)
            return {"ok": rc == 0, "typed": len(text),
                    "error": err if rc else None}
        if _have("ydotool"):
            rc, _o, err = _ro(["ydotool", "type", text], timeout=15)
            return {"ok": rc == 0, "typed": len(text),
                    "error": err if rc else None}
        return {"ok": False, "error": "install wtype or ydotool to type "
                                       "on Wayland"}
    if sess == "x11" and _have("xdotool"):
        rc, _o, err = _ro(["xdotool", "type", "--clearmodifiers", text],
                          timeout=15)
        return {"ok": rc == 0, "typed": len(text), "error": err if rc else None}
    return {"ok": False, "error": f"no input helper for {sess} session"}


def tool_press_key(keys: str) -> Dict[str, Any]:
    """Send a key or chord, e.g. 'Return', 'ctrl+s', 'alt+Tab', 'Escape'.
    Accepts xdotool-style names; translated for wtype on Wayland."""
    if not keys:
        return {"ok": False, "error": "no key"}
    sess = _session_type()
    if sess == "x11" and _have("xdotool"):
        rc, _o, err = _ro(["xdotool", "key", "--clearmodifiers", keys],
                          timeout=8)
        return {"ok": rc == 0, "pressed": keys, "error": err if rc else None}
    if sess == "wayland":
        if _have("wtype"):
            # wtype uses -M/-m for modifiers and -k for keysyms
            parts = keys.split("+")
            mods, key = parts[:-1], parts[-1]
            argv = ["wtype"]
            for m in mods:
                argv += ["-M", m]
            argv += ["-k", key]
            for m in reversed(mods):
                argv += ["-m", m]
            rc, _o, err = _ro(argv, timeout=8)
            return {"ok": rc == 0, "pressed": keys, "error": err if rc else None}
        if _have("ydotool"):
            rc, _o, err = _ro(["ydotool", "key", keys], timeout=8)
            return {"ok": rc == 0, "pressed": keys, "error": err if rc else None}
        return {"ok": False, "error": "install wtype or ydotool"}
    return {"ok": False, "error": f"no input helper for {sess} session"}


def tool_media_control(action: str) -> Dict[str, Any]:
    """Control media playback via playerctl: play, pause, play-pause,
    next, previous, stop, or status."""
    if not _have("playerctl"):
        return {"ok": False, "error": "playerctl not installed"}
    action = (action or "status").strip()
    allowed = {"play", "pause", "play-pause", "next", "previous", "stop",
               "status"}
    if action not in allowed:
        return {"ok": False, "error": f"action must be one of {sorted(allowed)}"}
    rc, out, err = _ro(["playerctl", action], timeout=5)
    return {"ok": rc == 0, "action": action,
            "output": out.strip(), "error": err if rc else None}


# ═════════════════════════════════════════════════════════════════════
# SCREENSHOTS & SCREEN READING (OCR)
# ═════════════════════════════════════════════════════════════════════

def _screenshot_to(path: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Capture the screen to `path` (PNG).  region = 'x,y,w,h' for a
    sub-rectangle (X11 via scrot/import).  Order of preference:
      • Wayland  → grim
      • X11      → scrot, then ImageMagick import
      • KDE any  → Spectacle as a fallback (handles compositor quirks)
    """
    sess = _session_type()
    try:
        # Wayland: grim (full screen; region needs interactive slurp)
        if sess == "wayland" and _have("grim"):
            rc, _o, err = _ro(["grim", path], timeout=15)
            if rc == 0:
                return {"ok": True, "path": path, "tool": "grim"}

        # X11: scrot is fastest and supports an exact region rectangle
        if sess != "wayland" and _have("scrot"):
            if region:
                # scrot autoselect rectangle: x,y,w,h
                argv = ["scrot", "-o", "-a", region, path]
            else:
                argv = ["scrot", "-o", path]
            rc, _o, err = _ro(argv, timeout=15)
            if rc == 0:
                return {"ok": True, "path": path, "tool": "scrot"}

        # X11: ImageMagick import on the root window, optional crop
        if sess != "wayland" and _have("import"):
            argv = ["import", "-window", "root"]
            if region:
                # region x,y,w,h → ImageMagick geometry WxH+X+Y
                try:
                    x, y, w, h = region.split(",")
                    argv += ["-crop", f"{w}x{h}+{x}+{y}"]
                except ValueError:
                    pass
            argv.append(path)
            rc, _o, err = _ro(argv, timeout=15)
            if rc == 0:
                return {"ok": True, "path": path, "tool": "import"}

        # KDE: Spectacle in background full-screen mode (-b -f -n -o)
        if _have("spectacle"):
            rc, _o, err = _ro(
                ["spectacle", "-b", "-n", "-f", "-o", path], timeout=20)
            if rc == 0 and os.path.exists(path):
                return {"ok": True, "path": path, "tool": "spectacle"}

        return {"ok": False,
                "error": f"no working screenshot tool for {sess} session "
                         f"(tried grim/scrot/import/spectacle)"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def tool_screenshot(save_path: str = "") -> Dict[str, Any]:
    """Take a screenshot and save it as a PNG.  Defaults to a timestamped
    file in ~/Pictures (or DATA_DIR if that's missing)."""
    if save_path:
        path = os.path.expanduser(save_path)
    else:
        pics = os.path.expanduser("~/Pictures")
        base = pics if os.path.isdir(pics) else str(DATA_DIR)
        ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        path = os.path.join(base, f"kali-shot-{ts}.png")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    res = _screenshot_to(path)
    if res.get("ok"):
        try:
            res["size_bytes"] = os.path.getsize(path)
        except Exception:
            pass
    return res


def tool_read_screen(region: str = "") -> Dict[str, Any]:
    """Screenshot the screen and OCR it to text — lets Kali 'read' what's
    on screen.  Needs a screenshot tool + tesseract.  Returns extracted
    text."""
    if not _have("tesseract"):
        return {"ok": False, "error": "tesseract not installed (needed for "
                                       "screen OCR: apt install tesseract-ocr)"}
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    shot = os.path.join(str(DATA_DIR), f"ocr-{ts}.png")
    cap = _screenshot_to(shot, region or None)
    if not cap.get("ok"):
        return cap
    try:
        rc, out, err = _ro(["tesseract", shot, "stdout"], timeout=30)
        text = out.strip()
        # clean up the temp capture
        try:
            os.remove(shot)
        except Exception:
            pass
        if rc != 0:
            return {"ok": False, "error": err or "tesseract failed"}
        return {"ok": True, "text": text, "chars": len(text)}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# ═════════════════════════════════════════════════════════════════════
# FILESYSTEM OPERATIONS — copy, move, delete, mkdir, rename
#
# Real filesystem manipulation beyond read/write.  Every destructive op
# (delete, overwrite-on-move) is guarded: refuses sensitive paths
# (is_sensitive_path) and refuses obviously catastrophic targets ($HOME
# itself, /, and the like).  Moves/copies into existing files are
# reported so the model/operator can decide.
# ═════════════════════════════════════════════════════════════════════

def _fs_guard(path: str) -> Optional[str]:
    """Return an error string if `path` is too dangerous to modify, else
    None."""
    rp = os.path.realpath(os.path.expanduser(path))
    if is_sensitive_path(rp):
        return f"refused: '{path}' is a protected/sensitive path"
    catastrophic = {"/", os.path.realpath(os.path.expanduser("~")),
                    "/etc", "/usr", "/bin", "/boot", "/lib", "/sys",
                    "/proc", "/dev", "/var"}
    if rp in catastrophic:
        return f"refused: '{path}' is a critical system path"
    return None


def tool_make_dir(path: str) -> Dict[str, Any]:
    """Create a directory (and parents)."""
    try:
        rp = os.path.expanduser(path)
        os.makedirs(rp, exist_ok=True)
        return {"ok": True, "created": rp}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def tool_copy_path(src: str, dst: str) -> Dict[str, Any]:
    """Copy a file or directory tree from src to dst."""
    try:
        rsrc = os.path.expanduser(src)
        rdst = os.path.expanduser(dst)
        if not os.path.exists(rsrc):
            return {"ok": False, "error": f"source not found: {src}"}
        if os.path.isdir(rsrc):
            shutil.copytree(rsrc, rdst, dirs_exist_ok=True)
        else:
            os.makedirs(os.path.dirname(rdst) or ".", exist_ok=True)
            shutil.copy2(rsrc, rdst)
        return {"ok": True, "copied": rsrc, "to": rdst}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def tool_move_path(src: str, dst: str) -> Dict[str, Any]:
    """Move or rename a file or directory."""
    guard = _fs_guard(src)
    if guard:
        return {"ok": False, "error": guard}
    try:
        rsrc = os.path.expanduser(src)
        rdst = os.path.expanduser(dst)
        if not os.path.exists(rsrc):
            return {"ok": False, "error": f"source not found: {src}"}
        os.makedirs(os.path.dirname(rdst) or ".", exist_ok=True)
        overwrote = os.path.exists(rdst)
        shutil.move(rsrc, rdst)
        return {"ok": True, "moved": rsrc, "to": rdst, "overwrote": overwrote}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def tool_delete_path(path: str, recursive: bool = False) -> Dict[str, Any]:
    """Delete a file, or a directory (recursive=True for non-empty dirs).

    Guarded against sensitive/critical paths.  This is destructive — the
    UI confirmation flow still applies before it runs in confirm mode."""
    guard = _fs_guard(path)
    if guard:
        return {"ok": False, "error": guard}
    try:
        rp = os.path.expanduser(path)
        if not os.path.exists(rp):
            return {"ok": False, "error": f"not found: {path}"}
        if os.path.isdir(rp):
            if recursive:
                shutil.rmtree(rp)
            else:
                os.rmdir(rp)   # fails if non-empty — intentional safety
        else:
            os.remove(rp)
        return {"ok": True, "deleted": rp}
    except OSError as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e} "
                                       f"(use recursive=true for non-empty "
                                       f"directories)"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def tool_path_info(path: str) -> Dict[str, Any]:
    """Stat a path: type, size, permissions, mtime — without reading it."""
    try:
        rp = os.path.expanduser(path)
        if not os.path.exists(rp):
            return {"ok": False, "error": f"not found: {path}"}
        st = os.stat(rp)
        return {
            "ok": True, "path": rp,
            "type": "dir" if os.path.isdir(rp) else "file",
            "size": st.st_size, "size_human": _human_bytes(st.st_size),
            "mode": oct(st.st_mode & 0o777),
            "mtime": datetime.datetime.fromtimestamp(
                st.st_mtime).isoformat(timespec="seconds"),
        }
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# ═════════════════════════════════════════════════════════════════════
# BROWSER AUTOMATION — open URLs, and (when Playwright is present) drive
# a real browser: navigate, read text, click, fill, screenshot.
#
# Two tiers:
#   • tool_open_url — always works (xdg-open), opens in the user's
#     default browser.  No automation, just "open this".
#   • tool_browser  — full automation via Playwright if installed.  One
#     persistent headed Chromium context is reused across calls so a
#     login/session carries between steps.  If Playwright isn't
#     installed, returns a clear, actionable error telling the operator
#     exactly how to enable it.
# ═════════════════════════════════════════════════════════════════════

def tool_open_url(url: str) -> Dict[str, Any]:
    """Open a URL in the default browser (no automation)."""
    url = (url or "").strip()
    if not url:
        return {"ok": False, "error": "no url"}
    if "://" not in url:
        url = "https://" + url
    if not _have("xdg-open"):
        return {"ok": False, "error": "xdg-open not available"}
    try:
        subprocess.Popen(["xdg-open", url], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        return {"ok": True, "opened": url}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# Persistent Playwright browser state, lazily created and reused.
_browser_state: Dict[str, Any] = {"pw": None, "browser": None, "page": None}
_browser_lock = threading.Lock()


def _browser_available() -> bool:
    import importlib.util
    return importlib.util.find_spec("playwright") is not None


def _ensure_browser() -> Tuple[Optional[Any], Optional[str]]:
    """Return (page, None) on success or (None, error) if Playwright is
    missing or the browser couldn't launch."""
    if not _browser_available():
        return None, ("Playwright not installed. Enable browser automation "
                      "with:  pip install playwright  &&  playwright install "
                      "chromium")
    with _browser_lock:
        if _browser_state["page"] is not None:
            return _browser_state["page"], None
        try:
            from playwright.sync_api import sync_playwright
            pw = sync_playwright().start()
            browser = pw.chromium.launch(headless=False)
            page = browser.new_page()
            _browser_state.update({"pw": pw, "browser": browser, "page": page})
            return page, None
        except Exception as e:
            return None, f"browser launch failed: {type(e).__name__}: {e}"


def tool_browser(action: str, target: str = "",
                 value: str = "") -> Dict[str, Any]:
    """Drive a real browser for automation.  Actions:
      • goto      target=URL                  — navigate
      • read      (no target)                 — return visible page text
      • click     target=CSS-or-text          — click an element
      • fill      target=CSS  value=TEXT       — type into a field
      • screenshot target=optional save path   — capture the page
      • title / url                            — page metadata
      • close                                  — shut the browser down
    A single browser session persists across calls so logins stick.
    Requires Playwright (clear error returned if absent)."""
    action = (action or "").strip().lower()
    if action == "close":
        with _browser_lock:
            try:
                if _browser_state["browser"]:
                    _browser_state["browser"].close()
                if _browser_state["pw"]:
                    _browser_state["pw"].stop()
            except Exception:
                pass
            _browser_state.update({"pw": None, "browser": None, "page": None})
        return {"ok": True, "closed": True}

    page, err = _ensure_browser()
    if err:
        return {"ok": False, "error": err}
    try:
        if action == "goto":
            url = target.strip()
            if "://" not in url:
                url = "https://" + url
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            return {"ok": True, "url": page.url, "title": page.title()}
        if action == "read":
            text = page.inner_text("body")[:8000]
            return {"ok": True, "text": text, "url": page.url}
        if action == "click":
            # try CSS first, then visible text
            try:
                page.click(target, timeout=8000)
            except Exception:
                page.get_by_text(target, exact=False).first.click(timeout=8000)
            return {"ok": True, "clicked": target, "url": page.url}
        if action == "fill":
            page.fill(target, value, timeout=8000)
            return {"ok": True, "filled": target, "chars": len(value)}
        if action == "screenshot":
            ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            path = (os.path.expanduser(target) if target
                    else os.path.join(str(DATA_DIR), f"page-{ts}.png"))
            page.screenshot(path=path, full_page=True)
            return {"ok": True, "path": path}
        if action == "title":
            return {"ok": True, "title": page.title()}
        if action == "url":
            return {"ok": True, "url": page.url}
        return {"ok": False, "error": f"unknown browser action '{action}'"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}


# ═════════════════════════════════════════════════════════════════════
# WEB SEARCH & READ  — headless, no browser, no API key, no Playwright
# ═════════════════════════════════════════════════════════════════════
# Two fast tools that let the model actually look things up and read
# pages without launching a GUI browser:
#   • tool_web_search — query a search engine over HTTP, return ranked
#     results (title / url / snippet) as text the model can read.
#   • tool_web_read   — fetch one URL and return its readable text with
#     scripts/markup stripped.
# Both use only urllib (stdlib).  The GUI browser tool stays for
# interactive / login-gated automation; these are for "search and read",
# which is what 90% of "look this up" requests actually need.
# ═════════════════════════════════════════════════════════════════════

_WEB_UA = ("Mozilla/5.0 (X11; Linux x86_64; rv:124.0) "
           "Gecko/20100101 Firefox/124.0")
_WEB_TIMEOUT = 15
# A public reader that fetches a page server-side and hands back clean text.
# Used as a fallback when a site blocks a plain fetch, serves JS-only
# content, or hides the text behind a dismissible "log in" overlay.  No key,
# best-effort.  The text we want is public; this just renders it for us.
_READER_PREFIX = "https://r.jina.ai/"


def _decompress(raw: bytes, encoding: str) -> bytes:
    """Inflate a response body per its Content-Encoding (gzip/deflate/br)."""
    enc = (encoding or "").lower()
    try:
        if "gzip" in enc:
            import gzip
            return gzip.decompress(raw)
        if "deflate" in enc:
            import zlib
            try:
                return zlib.decompress(raw)
            except zlib.error:
                return zlib.decompress(raw, -zlib.MAX_WBITS)
        if "br" in enc:
            try:
                import brotli  # type: ignore
                return brotli.decompress(raw)
            except Exception:
                return raw
    except Exception:
        return raw
    return raw


def _web_get(url: str, timeout: int = _WEB_TIMEOUT,
             data: Optional[bytes] = None,
             extra_headers: Optional[Dict[str, str]] = None,
             ) -> Tuple[int, str, str]:
    """HTTP GET/POST returning (status, text, final_url).  Decodes the body
    (gzip/deflate aware, lenient utf-8) and follows redirects.  On an HTTP
    error status the body is STILL returned — many 403/404 pages carry the
    text we actually want — so callers decide what to do with it."""
    import urllib.parse  # noqa: F401  (ensures submodule is loaded)
    headers = {
        "User-Agent": _WEB_UA,
        "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
                   "application/json;q=0.8,*/*;q=0.7"),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Upgrade-Insecure-Requests": "1",
    }
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST" if data else "GET")

    def _read(resp) -> Tuple[int, str, str]:
        raw = resp.read(3_000_000)  # 3 MB hard cap
        try:
            raw = _decompress(raw, resp.headers.get("Content-Encoding", ""))
        except Exception:
            pass
        charset = "utf-8"
        try:
            charset = resp.headers.get_content_charset() or "utf-8"
        except Exception:
            pass
        return resp.getcode(), raw.decode(charset, "replace"), resp.geturl()

    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return _read(r)
    except urllib.error.HTTPError as e:
        # The error response is itself a file-like object with a body.
        try:
            return _read(e)
        except Exception:
            return e.code, "", url


def _wayback_url(url: str) -> Optional[str]:
    """Ask the Wayback Machine for the latest archived snapshot of a URL,
    returning the raw-content variant (no archive chrome) or None."""
    import urllib.parse
    try:
        api = ("https://archive.org/wayback/available?url="
               + urllib.parse.quote(url, safe=""))
        _, body, _ = _web_get(api, timeout=12)
        data = json.loads(body)
        snap = (data.get("archived_snapshots") or {}).get("closest") or {}
        if snap.get("available") and snap.get("url"):
            return snap["url"].replace("/http", "if_/http", 1)
    except Exception:
        return None
    return None


def _reader_fetch(url: str, timeout: int = 25) -> Tuple[int, str, str]:
    """Fetch a page through the reader proxy (renders JS server-side, returns
    clean text).  Sidesteps JS-only pages and many soft blocks."""
    try:
        status, body, _ = _web_get(_READER_PREFIX + url, timeout=timeout,
                                   extra_headers={"X-Return-Format": "text"})
        return status, body, url
    except Exception as e:
        return 0, f"reader error: {type(e).__name__}: {e}", url


def _fetch_readable(url: str, timeout: int = 20) -> Tuple[str, str, str, str]:
    """Best-effort 'give me the readable text of this page', trying routes in
    order and stopping at the first that yields real content:
      1. direct fetch — raw pre-JS HTML.  This alone already gets past most
         soft 'please log in' overlays, because the text sits in the markup
         and only a script hides it visually.
      2. reader proxy — executes JS, dodges many blocks.
      3. Wayback Machine — the public archived copy.
    Returns (text, source_label, final_url, title).  Empty text => every
    route failed (a genuine hard login wall, or offline)."""
    def _title(h: str) -> str:
        tm = re.search(r"(?is)<title[^>]*>(.*?)</title>", h)
        return _html_to_text(tm.group(1))[:200] if tm else ""

    body = ""
    final = url
    try:
        status, body, final = _web_get(url, timeout=timeout)
        if status == 200 and body:
            txt = _readable_from_html(body)
            if len(txt) >= 200:
                return txt, "direct", final, _title(body)
    except Exception:
        body = ""
        final = url

    rstatus, rbody, _ = _reader_fetch(url, timeout=timeout + 8)
    if rstatus == 200 and rbody and len(rbody.strip()) >= 200:
        return rbody.strip(), "reader", url, ""

    wb = _wayback_url(url)
    if wb:
        try:
            status, wbody, _ = _web_get(wb, timeout=timeout)
            if status == 200 and wbody:
                txt = _readable_from_html(wbody)
                if len(txt) >= 200:
                    return txt, "wayback", wb, _title(wbody)
        except Exception:
            pass

    if body:  # thin, but better than nothing
        return _readable_from_html(body), "direct-thin", final, _title(body)
    return "", "none", url, ""


def _ddg_unwrap(href: str) -> str:
    """DuckDuckGo wraps result links as //duckduckgo.com/l/?uddg=ENC.
    Return the real destination URL."""
    import urllib.parse
    if "uddg=" in href:
        try:
            q = urllib.parse.urlparse(
                href if "://" in href else "https:" + href).query
            uddg = urllib.parse.parse_qs(q).get("uddg")
            if uddg:
                return urllib.parse.unquote(uddg[0])
        except Exception:
            pass
    if href.startswith("//"):
        return "https:" + href
    return href


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t\u00a0]+")
_NL_RE = re.compile(r"\n\s*\n\s*\n+")


def _html_to_text(html_src: str) -> str:
    """Strip a chunk of HTML down to readable plain text."""
    import html as _h
    s = html_src
    s = re.sub(r"(?is)<script.*?</script>", " ", s)
    s = re.sub(r"(?is)<style.*?</style>", " ", s)
    s = re.sub(r"(?is)<noscript.*?</noscript>", " ", s)
    s = re.sub(r"(?s)<!--.*?-->", " ", s)
    # Block elements → newlines so paragraphs survive.
    s = re.sub(r"(?i)<(br|/p|/div|/li|/h[1-6]|/tr|/section|/article)\s*/?>",
               "\n", s)
    s = re.sub(r"(?i)<(p|div|li|h[1-6]|tr|section|article)(\s[^>]*)?>",
               "\n", s)
    s = _TAG_RE.sub("", s)
    s = _h.unescape(s)
    s = _WS_RE.sub(" ", s)
    s = "\n".join(ln.strip() for ln in s.splitlines())
    s = _NL_RE.sub("\n\n", s)
    return s.strip()


def _readable_from_html(html_src: str) -> str:
    """Like _html_to_text but first drops nav/header/footer/aside/forms and
    narrows to the <article>/<main> region when present, so we keep the body
    text and shed the boilerplate.  Falls back to the whole document."""
    s = html_src
    for tag in ("script", "style", "noscript", "nav", "header", "footer",
                "aside", "form", "svg"):
        s = re.sub(rf"(?is)<{tag}\b.*?</{tag}>", " ", s)
    pick = None
    for pat in (r"(?is)<article\b[^>]*>(.*?)</article>",
                r"(?is)<main\b[^>]*>(.*?)</main>"):
        m = re.search(pat, s)
        if m and len(m.group(1)) > 400:
            pick = m.group(1)
            break
    return _html_to_text(pick if pick else s)


def _parse_ddg_html(html_src: str, limit: int) -> List[Dict[str, str]]:
    """Parse results from html.duckduckgo.com/html/."""
    import html as _h
    out: List[Dict[str, str]] = []
    # Each result anchor: <a ... class="result__a" href="...">Title</a>
    for m in re.finditer(
            r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
            html_src, re.IGNORECASE | re.DOTALL):
        url = _ddg_unwrap(_h.unescape(m.group(1)))
        title = _html_to_text(m.group(2))
        if not url or not title:
            continue
        out.append({"title": title, "url": url, "snippet": ""})
        if len(out) >= limit:
            break
    # Attach snippets in document order (best-effort alignment).
    snips = [
        _html_to_text(s.group(1))
        for s in re.finditer(
            r'<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>',
            html_src, re.IGNORECASE | re.DOTALL)
    ]
    for i, r in enumerate(out):
        if i < len(snips):
            r["snippet"] = snips[i]
    return out


def _parse_ddg_lite(html_src: str, limit: int) -> List[Dict[str, str]]:
    """Parse results from lite.duckduckgo.com/lite/ (fallback)."""
    import html as _h
    out: List[Dict[str, str]] = []
    for m in re.finditer(
            r'<a[^>]+class=[\'"]result-link[\'"][^>]+href="([^"]+)"[^>]*>(.*?)</a>',
            html_src, re.IGNORECASE | re.DOTALL):
        url = _ddg_unwrap(_h.unescape(m.group(1)))
        title = _html_to_text(m.group(2))
        if url and title:
            out.append({"title": title, "url": url, "snippet": ""})
        if len(out) >= limit:
            break
    return out


def _ddg_instant(query: str) -> Optional[str]:
    """DuckDuckGo Instant-Answer API — a direct answer when one exists."""
    import urllib.parse
    try:
        url = ("https://api.duckduckgo.com/?q="
               + urllib.parse.quote(query)
               + "&format=json&no_html=1&no_redirect=1&t=kali")
        _, body, _ = _web_get(url)
        data = json.loads(body)
    except Exception:
        return None
    abstract = (data.get("AbstractText") or "").strip()
    if abstract:
        src = (data.get("AbstractSource") or "").strip()
        u = (data.get("AbstractURL") or "").strip()
        tail = f"  ({src} — {u})" if u else ""
        return abstract + tail
    ans = (data.get("Answer") or "").strip()
    if ans:
        return ans
    defn = (data.get("Definition") or "").strip()
    if defn:
        return defn
    return None


def _generic_uddg_links(html_src: str, limit: int) -> List[Dict[str, str]]:
    """Markup-agnostic DDG extractor: pull every result link DDG wraps as
    /l/?uddg=… with its anchor text.  Survives result class-name churn,
    which is the usual reason the strict parser suddenly returns nothing."""
    import html as _h
    out: List[Dict[str, str]] = []
    seen = set()
    for m in re.finditer(
            r'<a\b[^>]+href="((?://duckduckgo\.com)?/l/\?[^"]*uddg=[^"]+)"[^>]*>(.*?)</a>',
            html_src, re.IGNORECASE | re.DOTALL):
        url = _ddg_unwrap(_h.unescape(m.group(1)))
        title = _html_to_text(m.group(2))
        if not url or not title or url in seen or "duckduckgo.com" in url:
            continue
        seen.add(url)
        out.append({"title": title, "url": url, "snippet": ""})
        if len(out) >= limit:
            break
    return out


def _parse_mojeek(html_src: str, limit: int) -> List[Dict[str, str]]:
    """Lenient Mojeek parser (independent index — good when DDG rate-limits).
    Grabs external result links + titles from the results region."""
    import html as _h
    out: List[Dict[str, str]] = []
    seen = set()
    region = html_src
    mi = re.search(r'(?is)<ul[^>]+class="results[^"]*">(.*?)</ul>', html_src)
    if mi:
        region = mi.group(1)
    for m in re.finditer(r'<a\b[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>',
                         region, re.IGNORECASE | re.DOTALL):
        url = _h.unescape(m.group(1))
        title = _html_to_text(m.group(2))
        host = url.split("/")[2] if "://" in url else ""
        if (not title or len(title) < 3 or "mojeek.com" in host
                or url in seen):
            continue
        seen.add(url)
        out.append({"title": title, "url": url, "snippet": ""})
        if len(out) >= limit:
            break
    return out


def tool_web_search(query: str, max_results: int = 6,
                    site: str = "") -> Dict[str, Any]:
    """Search the web over HTTP and return ranked results as text.  No
    browser, no API key.  Tries DuckDuckGo (HTML then Lite, GET then POST),
    falls back to Mojeek (a separate index), and always folds in a DDG
    Instant Answer when one exists.  Pass `site` to restrict to one domain
    (e.g. site='reddit.com'), or just put 'site:domain' in the query."""
    import urllib.parse
    query = (query or "").strip()
    site = (site or "").strip().lstrip("@")
    if site and f"site:{site}" not in query:
        query = f"{query} site:{site}".strip()
    if not query:
        return {"ok": False, "error": "no query"}

    max_results = max(1, min(int(max_results or 6), 20))
    q = urllib.parse.quote(query)
    form = urllib.parse.urlencode({"q": query}).encode()
    results: List[Dict[str, str]] = []
    errors: List[str] = []
    engine_used = ""

    attempts = [
        ("ddg-html", f"https://html.duckduckgo.com/html/?q={q}", None,
         _parse_ddg_html),
        ("ddg-html-post", "https://html.duckduckgo.com/html/", form,
         _parse_ddg_html),
        ("ddg-lite", f"https://lite.duckduckgo.com/lite/?q={q}", None,
         _parse_ddg_lite),
        ("ddg-lite-post", "https://lite.duckduckgo.com/lite/", form,
         _parse_ddg_lite),
        ("mojeek", f"https://www.mojeek.com/search?q={q}", None,
         _parse_mojeek),
    ]
    for name, endpoint, data, parser in attempts:
        if len(results) >= max_results:
            break
        try:
            status, body, _ = _web_get(endpoint, data=data)
            if status == 200 and body:
                got = parser(body, max_results)
                if not got and name.startswith("ddg"):
                    got = _generic_uddg_links(body, max_results)
                have = {r["url"] for r in results}
                for r in got:
                    if r["url"] not in have:
                        results.append(r)
                        have.add(r["url"])
                if got and not engine_used:
                    engine_used = name
        except Exception as e:
            errors.append(f"{name}: {type(e).__name__}: {str(e)[:80]}")

    instant = _ddg_instant(query)

    if not results and not instant:
        err = "no results"
        if errors:
            joined = "; ".join(errors[:3])
            err += f" ({joined})"
            if any(t in joined for t in ("URLError", "timed out",
                                         "Connection", "Name or service")):
                err = f"search failed — likely offline or DNS issue ({joined})"
        return {"ok": False, "error": err, "query": query}

    results = results[:max_results]
    lines: List[str] = [f"Search results for: {query}"]
    if instant:
        lines.append(f"\nDirect answer: {instant}")
    if results:
        lines.append("")
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r['title']}")
            lines.append(f"   {r['url']}")
            if r.get("snippet"):
                lines.append(f"   {r['snippet'][:300]}")
    return {
        "ok": True,
        "query": query,
        "engine": engine_used or ("instant" if instant else ""),
        "instant_answer": instant or "",
        "results": results,
        "text": "\n".join(lines),
    }


def _img_openverse(q: str, n: int) -> List[Dict[str, Any]]:
    """Openverse (openverse.org) — a real Creative-Commons image API returning
    direct image URLs as JSON.  No key needed for modest use.  Best for generic
    real-world subjects (a chair, a Raspberry Pi, a dog)."""
    import urllib.parse, json as _json
    url = (f"https://api.openverse.org/v1/images/"
           f"?q={urllib.parse.quote(q)}&page_size={n}&mature=false")
    _, body, _ = _web_get(url, timeout=_WEB_TIMEOUT,
                          extra_headers={"Accept": "application/json"})
    data = _json.loads(body)
    out: List[Dict[str, Any]] = []
    for it in (data.get("results") or [])[:n]:
        img = it.get("url") or ""
        if img.startswith("http"):
            out.append({"title": (it.get("title") or "").strip(),
                        "image": img,
                        "thumbnail": it.get("thumbnail") or img,
                        "source": it.get("foreign_landing_url") or "",
                        "width": it.get("width"), "height": it.get("height")})
    return out


def _img_wikimedia(q: str, n: int) -> List[Dict[str, Any]]:
    """Wikimedia Commons via the MediaWiki API — rock-solid, keyless JSON,
    returns the direct upload.wikimedia.org URL.  Excellent encyclopedic
    coverage and never blocks a polite request."""
    import urllib.parse, json as _json
    url = ("https://commons.wikimedia.org/w/api.php?action=query"
           "&generator=search&gsrsearch=" + urllib.parse.quote(q) +
           "&gsrnamespace=6&gsrlimit=" + str(n) +
           "&prop=imageinfo&iiprop=url%7Csize%7Cmime&format=json")
    _, body, _ = _web_get(url, timeout=_WEB_TIMEOUT,
                          extra_headers={"Accept": "application/json"})
    data = _json.loads(body)
    pages = ((data.get("query") or {}).get("pages") or {})
    out: List[Dict[str, Any]] = []
    for _pid, page in pages.items():
        ii = page.get("imageinfo") or []
        if not ii:
            continue
        info = ii[0]
        img = info.get("url") or ""
        mime = info.get("mime") or ""
        if img.startswith("http") and mime.startswith("image/"):
            out.append({"title": (page.get("title") or "").replace("File:", ""),
                        "image": img,
                        "thumbnail": info.get("thumburl") or img,
                        "source": info.get("descriptionurl") or "",
                        "width": info.get("width"), "height": info.get("height")})
    return out[:n]


def _img_duckduckgo(q: str, n: int) -> List[Dict[str, Any]]:
    """DuckDuckGo image scrape (vqd token → i.js).  Broadest coverage but the
    least reliable — DDG actively fights scrapers — so it's the last resort."""
    import urllib.parse, json as _json
    qe = urllib.parse.quote(q)
    _, html, _ = _web_get(f"https://duckduckgo.com/?q={qe}&iax=images&ia=images",
                          timeout=_WEB_TIMEOUT)
    m = (re.search(r'vqd=["\']([\w-]+)["\']', html)
         or re.search(r'vqd=([\w-]+)&', html)
         or re.search(r'"vqd":"([\w-]+)"', html))
    if not m:
        return []
    iu = (f"https://duckduckgo.com/i.js?l=us-en&o=json&q={qe}"
          f"&vqd={m.group(1)}&f=,,,,,&p=1")
    _, body, _ = _web_get(iu, timeout=_WEB_TIMEOUT, extra_headers={
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Referer": "https://duckduckgo.com/",
        "X-Requested-With": "XMLHttpRequest"})
    data = _json.loads(body)
    out: List[Dict[str, Any]] = []
    for it in (data.get("results") or [])[:n]:
        img = it.get("image") or ""
        if img.startswith("http"):
            out.append({"title": (it.get("title") or "").strip(),
                        "image": img, "thumbnail": it.get("thumbnail") or "",
                        "source": it.get("url") or "",
                        "width": it.get("width"), "height": it.get("height")})
    return out


def tool_image_search(query: str, max_results: int = 4) -> Dict[str, Any]:
    """Find images on the web and return DIRECT image URLs so Kali can show
    pictures inline in chat.  No API key.

    It tries three keyless sources in order of reliability and STOPS at the
    first that returns results: Openverse (a real CC image API), then Wikimedia
    Commons (the MediaWiki API), then DuckDuckGo images (a scrape, least
    reliable).  Because the first two are real JSON APIs, this is robust — it
    does not depend on scraping a single anti-bot endpoint.

    To DISPLAY a result, embed its image URL in your reply as markdown —
    ![short description](image_url) — and the chat renders it as a picture.
    Just call this once; do not hand-scrape stock-photo sites or guess file
    names if it comes back empty — say you couldn't find one instead."""
    query = (query or "").strip()
    if not query:
        return {"ok": False, "error": "no query"}
    max_results = max(1, min(int(max_results or 4), 10))

    results: List[Dict[str, Any]] = []
    used = ""
    errors: List[str] = []
    for name, fn in (("openverse", _img_openverse),
                     ("wikimedia", _img_wikimedia),
                     ("duckduckgo", _img_duckduckgo)):
        try:
            got = fn(query, max_results)
            if got:
                results = got
                used = name
                break
        except Exception as e:
            errors.append(f"{name}: {type(e).__name__}")
            continue

    if not results:
        detail = (" (" + "; ".join(errors) + ")") if errors else ""
        return {"ok": True, "query": query, "results": [], "source": "",
                "text": f"No images found for '{query}'{detail}. Tell the "
                        f"operator you couldn't find a picture rather than "
                        f"guessing a URL."}

    lines = [f"{len(results)} image(s) for '{query}' (via {used}) — embed any "
             f"as ![desc](url) to show it:"]
    for r in results:
        dim = (f" ({r['width']}x{r['height']})"
               if r.get("width") and r.get("height") else "")
        lines.append(f"  • {r['title'] or 'image'}{dim}: {r['image']}")
    return {"ok": True, "query": query, "source": used,
            "results": results, "text": "\n".join(lines)}


def tool_web_read(url: str, max_chars: int = 6000) -> Dict[str, Any]:
    """Fetch one URL and return its readable text (markup stripped).  Tries a
    direct fetch first, then a reader proxy, then the Wayback Machine, so a
    blocked, JS-only, or soft-login-gated page still yields its public text.
    The reported `source` tells you which route produced the text.
    Pairs with web_search: search → pick a result → read it."""
    url = (url or "").strip()
    if not url:
        return {"ok": False, "error": "no url"}
    if "://" not in url:
        url = "https://" + url
    max_chars = max(500, min(int(max_chars or 6000), 30000))

    text, source, final_url, title = _fetch_readable(url, timeout=20)
    if not text:
        return {"ok": False,
                "error": ("could not retrieve readable content — the page is "
                          "likely behind a hard login wall or offline. Tried "
                          "direct fetch, reader proxy, and web archive."),
                "url": url}

    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars].rsplit(" ", 1)[0] + " …"
    head = f"[via {source}] {final_url}"
    if title:
        head = f"{title}\n{head}"
    return {
        "ok": True,
        "url": final_url,
        "title": title,
        "source": source,
        "truncated": truncated,
        "text": f"{head}\n\n{text}",
    }


# ═════════════════════════════════════════════════════════════════════
# VERIFICATION & PENTEST  — thin wrappers over the kali_ext sidecar.  They
#   let the agent (a) cross-check a claim across several INDEPENDENT sources
#   and flag propaganda / satire before asserting it, and (b) plan recon,
#   inventory modern offensive tooling, and look up CVEs from NVD.  All are
#   optional and fail-open: if the sidecar isn't present the tool reports
#   that cleanly instead of crashing the agent loop.  Nothing here executes
#   an attack — pentest_plan only *proposes* commands for the normal gate.
# ═════════════════════════════════════════════════════════════════════

def tool_web_verify(query: str, max_sources: int = 5,
                    settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Cross-check a factual / current / security claim across several
    INDEPENDENT sources before answering.  Gathers diverse domains, scores
    each for credibility (primary / reputable / community / state-media /
    satire), checks whether they corroborate one another, and returns a
    confidence label plus a briefing that tells the model to cite domains and
    flag any propaganda or satire.  Use whenever being wrong would matter."""
    try:
        from kali_ext import verify as _verify
    except Exception as e:
        return {"ok": False,
                "error": f"verification module unavailable: {e}"}
    try:
        return _verify.verify(
            query, tool_web_search, tool_web_read,
            settings or {},
            max_sources=max(2, min(int(max_sources or 5), 8)),
            log=log)
    except Exception as e:
        return {"ok": False, "error": f"verification failed: {e}"}


def tool_tooling_check() -> Dict[str, Any]:
    """Inventory the modern offensive-security toolchain on this box (recon,
    probing, ports, fuzzing, vuln scanning, creds, AD).  Reports which tools
    are present and the install line for the ones that aren't.  Read-only —
    runs nothing but `which`."""
    try:
        from kali_ext import pentest as _pentest
    except Exception as e:
        return {"ok": False, "error": f"pentest module unavailable: {e}"}
    try:
        return _pentest.tooling_check()
    except Exception as e:
        return {"ok": False, "error": f"tooling_check failed: {e}"}


def tool_pentest_plan(target: str, profile: str = "web",
                      intensity: str = "normal") -> Dict[str, Any]:
    """Build an ordered reconnaissance PLAN for a target (profile = web |
    network | ad | api | full | quick).  `intensity` = stealth | normal |
    aggressive tunes scan timing / rate-limits / thread counts.  Returns each
    step as a *proposed* command with its risk level and notes — it does NOT
    run anything; every command still goes through the normal approve-before-
    run gate.  Marks any step whose tool isn't installed.  Read-only
    enumeration first; nothing offensive is auto-executed."""
    try:
        from kali_ext import pentest as _pentest
    except Exception as e:
        return {"ok": False, "error": f"pentest module unavailable: {e}"}
    try:
        return _pentest.plan_recon((target or "").strip(),
                                   (profile or "web").strip().lower(),
                                   (intensity or "normal").strip().lower())
    except Exception as e:
        return {"ok": False, "error": f"pentest_plan failed: {e}"}


def tool_cve_lookup(product: str, version: str = "",
                    limit: int = 8, enrich: bool = True) -> Dict[str, Any]:
    """Look up known CVEs for a product (optionally a specific version) from
    NVD, the authoritative source, then enrich each hit with CISA KEV (is it
    exploited in the wild?) and EPSS (exploit-probability score) and rank by
    real-world risk — KEV first, then EPSS, then CVSS.  Returns findings with
    a trust caveat.  Use this AFTER a banner / version has been confirmed by
    a tool — never guess a version from memory.  `enrich=False` skips the
    KEV/EPSS calls for a quick NVD-only lookup."""
    try:
        from kali_ext import pentest as _pentest
    except Exception as e:
        return {"ok": False, "error": f"pentest module unavailable: {e}"}

    def _fetch_json(url: str) -> Any:
        status, text, _ = _web_get(url, timeout=25)
        if not text:
            raise RuntimeError(f"empty response (HTTP {status})")
        return json.loads(text)

    try:
        return _pentest.cve_lookup((product or "").strip(),
                                   (version or "").strip(),
                                   fetch_json=_fetch_json,
                                   limit=max(1, min(int(limit or 8), 20)),
                                   enrich=bool(enrich))
    except Exception as e:
        return {"ok": False, "error": f"cve_lookup failed: {e}"}


def tool_parse_output(tool: str, raw: str,
                      enrich_cves: bool = False) -> Dict[str, Any]:
    """Turn raw scanner output into clean structured data.  Feed it the tool
    name (nmap, httpx, nuclei, naabu, masscan, subfinder, ffuf, feroxbuster,
    gobuster, katana, gau, whatweb, wpscan, sslscan, testssl, smbmap, netexec,
    nikto, gitleaks, trufflehog, dalfox, arjun, …) and the stdout you captured,
    and it returns a normalised list of hosts / ports / endpoints / findings.

    Set enrich_cves=true to AUTO-CHAIN into CVE intel: every confirmed
    product+version in the output (e.g. an nmap banner like 'OpenSSH 9.6') is
    looked up via NVD + CISA KEV + EPSS and a consolidated, severity-ranked
    'cve_enrichment' block is attached — so a scan paste comes back already
    telling you which services have exploitable, known-in-the-wild CVEs.
    (That one path touches the network; plain parsing is read-only/offline.)"""
    try:
        from kali_ext import pentest as _pentest
    except Exception as e:
        return {"ok": False, "error": f"pentest module unavailable: {e}"}
    try:
        parsed = _pentest.parse_output((tool or "").strip().lower(), raw or "")
    except Exception as e:
        return {"ok": False, "error": f"parse_output failed: {e}"}
    if enrich_cves and isinstance(parsed, dict) and parsed.get("ok", True):
        def _fetch_json(url: str) -> Any:
            status, text, _ = _web_get(url, timeout=25)
            if not text:
                raise RuntimeError(f"empty response (HTTP {status})")
            return json.loads(text)
        try:
            parsed = _pentest.enrich_with_cves(parsed, fetch_json=_fetch_json)
        except Exception as e:
            parsed["cve_enrichment"] = {"ok": False,
                                        "error": f"CVE enrichment failed: {e}"}
    return parsed


def tool_methodology(area: str = "", phase: str = "") -> Dict[str, Any]:
    """Return a phased testing checklist for an engagement area (web, network,
    ad, api, mobile, wifi, recon, priv-esc, cloud).  Grounded in PTES / OWASP
    WSTG / the AD kill-chain.  Optionally narrow to one `phase`.  Reference
    knowledge only — proposes no commands and runs nothing; use it to make
    sure a test is methodical and nothing gets skipped.  Call with no args to
    list the areas."""
    try:
        from kali_ext import pentest as _pentest
    except Exception as e:
        return {"ok": False, "error": f"pentest module unavailable: {e}"}
    try:
        return _pentest.methodology((area or "").strip().lower(),
                                    (phase or "").strip().lower())
    except Exception as e:
        return {"ok": False, "error": f"methodology failed: {e}"}


def tool_wordlist_find(kind: str = "") -> Dict[str, Any]:
    """Locate wordlists actually installed on this box (dir, subdomain,
    password, api, param, username, lfi, …) under /usr/share/wordlists,
    seclists and /opt/SecLists.  Returns a canonical pick plus alternatives,
    and an install hint if nothing matching is present.  Read-only — only
    looks at the filesystem.  Call with no args to list the kinds."""
    try:
        from kali_ext import pentest as _pentest
    except Exception as e:
        return {"ok": False, "error": f"pentest module unavailable: {e}"}
    try:
        return _pentest.wordlist_find((kind or "").strip().lower())
    except Exception as e:
        return {"ok": False, "error": f"wordlist_find failed: {e}"}


def tool_cheatsheet(topic: str = "") -> Dict[str, Any]:
    """Return correct command-line *syntax* for a tool (nmap, ffuf, nuclei,
    httpx, netexec, hydra, hashcat, john, sqlmap, smbmap, kerbrute, ssh-tunnel,
    curl, …) — the flags and invocation patterns you actually use, as a quick
    reference.  Documentation only: no exploit code or payloads, runs nothing.
    Call with no args to list the topics."""
    try:
        from kali_ext import pentest as _pentest
    except Exception as e:
        return {"ok": False, "error": f"pentest module unavailable: {e}"}
    try:
        return _pentest.cheatsheet((topic or "").strip().lower())
    except Exception as e:
        return {"ok": False, "error": f"cheatsheet failed: {e}"}


def tool_report_findings(findings: Any, target: str = "",
                         scope_note: str = "",
                         title: str = "") -> Dict[str, Any]:
    """Aggregate a list of structured findings into a clean markdown
    engagement report — severity rollup, a sorted findings table, and a
    per-finding detail section.  Each finding can carry title, severity,
    host/url, description, evidence and remediation; missing fields are
    handled gracefully.  Read-only — formats text, runs nothing."""
    try:
        from kali_ext import pentest as _pentest
    except Exception as e:
        return {"ok": False, "error": f"pentest module unavailable: {e}"}
    try:
        return _pentest.report_findings(findings,
                                        (target or "").strip(),
                                        (scope_note or "").strip(),
                                        (title or "").strip())
    except Exception as e:
        return {"ok": False, "error": f"report_findings failed: {e}"}


def tool_nuclei_template(spec: Any = None, mode: str = "build",
                         yaml_text: str = "") -> Dict[str, Any]:
    """Generate a structurally-correct Nuclei template from a simple spec, or
    validate an existing one.  build: pass a spec dict (id/name/severity/
    protocol/path/matchers…) → returns runnable YAML.  validate: pass the YAML
    as `yaml_text` (or `mode="validate"`) → returns the list of structural
    problems.  Produces/checks templates; runs nothing (the operator runs
    `nuclei -t` themselves).  This exists because Nuclei's YAML is easy to get
    subtly wrong, which only surfaces as a cryptic error at scan time."""
    try:
        from kali_ext import pentest as _pentest
    except Exception as e:
        return {"ok": False, "error": f"pentest module unavailable: {e}"}
    try:
        return _pentest.nuclei_template(spec, (mode or "build").strip().lower(),
                                        yaml_text or "")
    except Exception as e:
        return {"ok": False, "error": f"nuclei_template failed: {e}"}


def tool_reflect_findings(findings: Any) -> Dict[str, Any]:
    """Self-reflection / false-positive check: critique a set of findings before
    they go in a report.  Flags findings with no evidence, a high/critical
    rating that isn't backed up, hedging language ('maybe', 'possibly'), no
    affected host, or duplicates — so weak findings get fixed or dropped instead
    of shipped.  Pure heuristics, no model call, runs nothing."""
    try:
        from kali_ext import pentest as _pentest
    except Exception as e:
        return {"ok": False, "error": f"pentest module unavailable: {e}"}
    try:
        return _pentest.reflect_findings(findings)
    except Exception as e:
        return {"ok": False, "error": f"reflect_findings failed: {e}"}


# ═════════════════════════════════════════════════════════════════════
# OSINT  — footprint / username discovery across public profile sites,
#          plus platform-aware public readers.  Read-only; touches only
#          public pages and public APIs (no login, no scraping of gated
#          data).  Built for auditing your own footprint and open-source
#          research on a name.  A hit means a public page exists at that
#          handle — NOT that it is the same person; always confirm.
# ═════════════════════════════════════════════════════════════════════

# (name, url template with {u}, kind, marker)
#   kind="status"  → 200 means found, 404/410 means absent
#   kind="present" → 200 body containing marker means found
#   kind="absent"  → 200 body containing marker means NOT found
_OSINT_SITES: List[Tuple[str, str, str, str]] = [
    ("GitHub",     "https://github.com/{u}",                          "status",  ""),
    ("GitLab",     "https://gitlab.com/{u}",                          "status",  ""),
    ("TikTok",     "https://www.tiktok.com/@{u}",                     "status",  ""),
    ("YouTube",    "https://www.youtube.com/@{u}",                    "status",  ""),
    ("Instagram",  "https://www.instagram.com/{u}/",                  "status",  ""),
    ("Pinterest",  "https://www.pinterest.com/{u}/",                  "status",  ""),
    ("SoundCloud", "https://soundcloud.com/{u}",                      "status",  ""),
    ("Vimeo",      "https://vimeo.com/{u}",                           "status",  ""),
    ("Flickr",     "https://www.flickr.com/people/{u}",               "status",  ""),
    ("Dribbble",   "https://dribbble.com/{u}",                        "status",  ""),
    ("Behance",    "https://www.behance.net/{u}",                     "status",  ""),
    ("DeviantArt", "https://www.deviantart.com/{u}",                  "status",  ""),
    ("Medium",     "https://medium.com/@{u}",                         "status",  ""),
    ("Keybase",    "https://keybase.io/{u}",                          "status",  ""),
    ("Replit",     "https://replit.com/@{u}",                         "status",  ""),
    ("PyPI",       "https://pypi.org/user/{u}/",                      "status",  ""),
    ("npm",        "https://www.npmjs.com/~{u}",                      "status",  ""),
    ("DockerHub",  "https://hub.docker.com/u/{u}",                    "status",  ""),
    ("HackerOne",  "https://hackerone.com/{u}",                       "status",  ""),
    ("Bugcrowd",   "https://bugcrowd.com/{u}",                        "status",  ""),
    ("Kaggle",     "https://www.kaggle.com/{u}",                      "status",  ""),
    ("LastFM",     "https://www.last.fm/user/{u}",                    "status",  ""),
    ("Lichess",    "https://lichess.org/@/{u}",                       "status",  ""),
    ("ChessCom",   "https://www.chess.com/member/{u}",                "status",  ""),
    ("Codepen",    "https://codepen.io/{u}",                          "status",  ""),
    ("AboutMe",    "https://about.me/{u}",                            "status",  ""),
    ("Linktree",   "https://linktr.ee/{u}",                           "status",  ""),
    ("Gravatar",   "https://en.gravatar.com/{u}",                     "status",  ""),
    ("Mastodon",   "https://mastodon.social/@{u}",                    "status",  ""),
    ("Snapchat",   "https://www.snapchat.com/add/{u}",                "status",  ""),
    ("Wordpress",  "https://{u}.wordpress.com",                       "status",  ""),
    ("Tumblr",     "https://{u}.tumblr.com",                          "status",  ""),
    ("Blogspot",   "https://{u}.blogspot.com",                        "status",  ""),
    ("ItchIo",     "https://itch.io/profile/{u}",                     "status",  ""),
    ("Trello",     "https://trello.com/{u}",                          "status",  ""),
    ("Spotify",    "https://open.spotify.com/user/{u}",               "status",  ""),
    ("Reddit",     "https://www.reddit.com/user/{u}/about.json",      "status",  ""),
    ("Bluesky",    "https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile?actor={u}.bsky.app", "status", ""),
    ("Twitch",     "https://www.twitch.tv/{u}",                       "status",  ""),
    ("Telegram",   "https://t.me/{u}",                                "present", "tgme_page_title"),
    ("Steam",      "https://steamcommunity.com/id/{u}",               "absent",  "could not be found"),
    ("HackerNews", "https://news.ycombinator.com/user?id={u}",        "absent",  "No such user."),
    ("Pastebin",   "https://pastebin.com/u/{u}",                      "absent",  "Not Found"),
]


def _extract_og_image(body: str, base_url: str = "") -> str:
    """Pull a profile/preview image URL from a page's social meta tags
    (og:image, twitter:image).  Most profile pages set og:image to the user's
    avatar, so this gives Kali a picture to show for a found OSINT hit."""
    if not body:
        return ""
    for pat in (
        r'<meta[^>]+property=["\']og:image(?::secure_url)?["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
        r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
    ):
        m = re.search(pat, body, re.IGNORECASE)
        if m:
            u = m.group(1).strip()
            if u.startswith("//"):
                u = "https:" + u
            elif u.startswith("/") and base_url:
                try:
                    from urllib.parse import urljoin
                    u = urljoin(base_url, u)
                except Exception:
                    pass
            if u.startswith("http"):
                return u
    return ""


def _osint_check_one(entry: Tuple[str, str, str, str], username: str,
                     timeout: int) -> Dict[str, str]:
    name, tmpl, kind, marker = entry
    url = tmpl.format(u=username)
    try:
        status, body, _ = _web_get(url, timeout=timeout)
    except Exception as e:
        return {"site": name, "url": url, "status": "error",
                "detail": type(e).__name__}
    if kind == "status":
        if status == 200:
            return {"site": name, "url": url, "status": "found",
                    "image": _extract_og_image(body, url)}
        if status in (404, 410):
            return {"site": name, "url": url, "status": "absent"}
        return {"site": name, "url": url, "status": "unknown",
                "detail": f"HTTP {status}"}
    if kind == "present":
        if status == 200 and marker.lower() in body.lower():
            return {"site": name, "url": url, "status": "found",
                    "image": _extract_og_image(body, url)}
        return {"site": name, "url": url, "status": "absent"}
    if kind == "absent":
        if status != 200:
            return {"site": name, "url": url, "status": "absent",
                    "detail": f"HTTP {status}"}
        if marker.lower() in body.lower():
            return {"site": name, "url": url, "status": "absent"}
        return {"site": name, "url": url, "status": "found",
                "image": _extract_og_image(body, url)}
    return {"site": name, "url": url, "status": "unknown"}


def tool_osint_username(username: str, sites: str = "",
                        timeout: int = 12) -> Dict[str, Any]:
    """Check where a username exists across ~43 public profile sites (a
    Sherlock-style sweep), concurrently.  Requests each site's public profile
    URL and reports found / absent / inconclusive.  Read-only — only public
    pages are touched.  `sites` optionally narrows to a comma-list of site
    names (e.g. 'GitHub,Reddit,Mastodon')."""
    username = (username or "").strip().lstrip("@")
    if not username:
        return {"ok": False, "error": "no username"}
    if not re.match(r"^[A-Za-z0-9._\-]{1,40}$", username):
        return {"ok": False,
                "error": "username has unusual characters; expected letters, "
                         "digits, dot, underscore or hyphen"}
    timeout = max(4, min(int(timeout or 12), 25))
    wanted = {s.strip().lower() for s in sites.split(",") if s.strip()}
    entries = [e for e in _OSINT_SITES
               if not wanted or e[0].lower() in wanted]

    found: List[Dict[str, str]] = []
    absent: List[Dict[str, str]] = []
    unknown: List[Dict[str, str]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
        futs = {ex.submit(_osint_check_one, e, username, timeout): e
                for e in entries}
        try:
            for fut in concurrent.futures.as_completed(
                    futs, timeout=timeout + 25):
                try:
                    r = fut.result()
                except Exception:
                    continue
                bucket = (found if r["status"] == "found"
                          else absent if r["status"] == "absent"
                          else unknown)
                bucket.append(r)
        except concurrent.futures.TimeoutError:
            pass

    found.sort(key=lambda r: r["site"].lower())
    unknown.sort(key=lambda r: r["site"].lower())

    lines = [f"Username sweep for: {username}",
             f"Found on {len(found)} site(s); {len(unknown)} inconclusive; "
             f"checked {len(entries)}."]
    if found:
        lines.append("\nFOUND:")
        for r in found:
            img = f"  [avatar: {r['image']}]" if r.get("image") else ""
            lines.append(f"  • {r['site']}: {r['url']}{img}")
    if any(r.get("image") for r in found):
        lines.append("\n(To show an avatar, embed it as ![name](avatar_url).)")
    if unknown:
        lines.append("\nINCONCLUSIVE (these sites cloak missing profiles — "
                     "open by hand to confirm):")
        for r in unknown:
            d = f" ({r.get('detail')})" if r.get("detail") else ""
            lines.append(f"  • {r['site']}: {r['url']}{d}")
    lines.append("\nA hit means a public page exists at that handle, not that "
                 "it's the same person. Read the profiles to confirm.")
    return {
        "ok": True,
        "username": username,
        "found": found,
        "inconclusive": unknown,
        "checked": len(entries),
        "text": "\n".join(lines),
    }


def tool_osint_lookup(target: str, full_name: str = "") -> Dict[str, Any]:
    """Footprint lookup for a person or handle.  If `target` looks like a
    username it runs a username sweep; in all cases it runs targeted web
    searches (profiles, mentions, the major platforms) and aggregates what's
    publicly findable into one report.  Read-only, public sources only —
    built for auditing your own footprint or open-source research on a name.
    Pass `full_name` to search a real name alongside a handle."""
    target = (target or "").strip()
    if not target:
        return {"ok": False, "error": "no target"}
    handle = target.lstrip("@")
    is_handle = (" " not in target
                 and bool(re.match(r"^@?[A-Za-z0-9._\-]{1,40}$", target)))

    head = f"OSINT lookup: {target}"
    if full_name:
        head += f"  (name: {full_name})"
    sections = [head]

    sweep = None
    if is_handle:
        sweep = tool_osint_username(handle)
        if sweep.get("ok"):
            sections.append("\n=== USERNAME SWEEP ===\n" + sweep["text"])

    name_q = (full_name.strip() or target)
    quoted = f'"{name_q}"' if " " in name_q else name_q
    queries = [
        quoted,
        f'{quoted} profile',
        f'{quoted} (site:linkedin.com OR site:github.com OR site:twitter.com OR site:x.com)',
        f'{quoted} (site:reddit.com OR site:medium.com OR site:facebook.com)',
        f'{handle} (site:github.com OR site:gitlab.com OR site:keybase.io)',
        f'{quoted} contact OR email',
    ]
    seen = set()
    hits: List[Dict[str, str]] = []
    for qq in queries:
        try:
            r = tool_web_search(qq, max_results=6)
        except Exception:
            continue
        if r.get("ok"):
            for res in r.get("results", []):
                u = res.get("url", "")
                if u and u not in seen:
                    seen.add(u)
                    hits.append(res)

    if hits:
        sections.append("\n=== WEB MENTIONS / PROFILES ===")
        for i, r in enumerate(hits[:25], 1):
            line = f"{i}. {r.get('title', '')}\n   {r.get('url', '')}"
            if r.get("snippet"):
                line += f"\n   {r['snippet'][:200]}"
            sections.append(line)

    sections.append("\nAggregates only public, open-source results. Verify "
                    "identity by reading the actual pages — name and handle "
                    "collisions are common.")
    return {
        "ok": True,
        "target": target,
        "sweep": sweep,
        "web_hits": hits[:25],
        "text": "\n".join(sections),
    }


def _reddit_json_to_text(body: str, max_chars: int) -> str:
    try:
        data = json.loads(body)
    except Exception:
        return ""
    out: List[str] = []

    def walk(node):
        if isinstance(node, dict):
            kind = node.get("kind")
            d = node.get("data", {}) if isinstance(node.get("data"), dict) else {}
            if kind == "t3":
                out.append(f"POST: {d.get('title', '')}\n  r/"
                           f"{d.get('subreddit', '')} · u/{d.get('author', '')}"
                           f" · score {d.get('score', '')}")
                if d.get("selftext"):
                    out.append("  " + d["selftext"][:800])
                if d.get("url") and not d.get("is_self"):
                    out.append("  link: " + d["url"])
            elif kind == "t1":
                out.append(f"COMMENT by u/{d.get('author', '')} "
                           f"(score {d.get('score', '')}):\n  "
                           f"{(d.get('body') or '')[:600]}")
            if isinstance(d.get("children"), list):
                for c in d["children"]:
                    walk(c)
        elif isinstance(node, list):
            for c in node:
                walk(c)

    walk(data)
    txt = "\n\n".join(out)
    return txt[:max_chars] if txt else ""


def _bsky_public(handle: str, max_chars: int) -> str:
    import urllib.parse
    handle = handle.lstrip("@")
    base = "https://public.api.bsky.app/xrpc/"
    try:
        _, pj, _ = _web_get(base + "app.bsky.actor.getProfile?actor="
                            + urllib.parse.quote(handle), timeout=15)
        prof = json.loads(pj)
        if prof.get("error"):
            return ""
        head = (f"BLUESKY @{prof.get('handle', '')}  "
                f"({prof.get('displayName', '')})\n"
                f"  followers {prof.get('followersCount', '?')} · "
                f"following {prof.get('followsCount', '?')} · "
                f"posts {prof.get('postsCount', '?')}\n"
                f"  {prof.get('description', '') or ''}")
        _, fj, _ = _web_get(
            base + "app.bsky.feed.getAuthorFeed?limit=15&actor="
            + urllib.parse.quote(handle), timeout=15)
        feed = json.loads(fj).get("feed", [])
        posts = []
        for item in feed:
            rec = (item.get("post", {}).get("record", {}) or {})
            t = rec.get("text", "")
            if t:
                posts.append("• " + t.replace("\n", " ")[:280])
        body = "\n".join(posts)
        txt = head + ("\n\nRecent posts:\n" + body if body else "")
        return txt[:max_chars]
    except Exception:
        return ""


def _mastodon_public(instance: str, user: str, max_chars: int) -> str:
    import urllib.parse
    base = f"https://{instance}/api/v1/"
    try:
        _, lj, _ = _web_get(base + "accounts/lookup?acct="
                            + urllib.parse.quote(user), timeout=15)
        acct = json.loads(lj)
        aid = acct.get("id")
        if not aid:
            return ""
        head = (f"MASTODON @{acct.get('acct', '')}@{instance} "
                f"({acct.get('display_name', '')})\n"
                f"  followers {acct.get('followers_count', '?')} · "
                f"following {acct.get('following_count', '?')} · "
                f"posts {acct.get('statuses_count', '?')}\n"
                f"  {_html_to_text(acct.get('note', '') or '')}")
        _, sj, _ = _web_get(base + f"accounts/{aid}/statuses?limit=15",
                            timeout=15)
        toots = []
        for st in json.loads(sj):
            t = _html_to_text(st.get("content", "") or "")
            if t:
                toots.append("• " + t.replace("\n", " ")[:280])
        body = "\n".join(toots)
        txt = head + ("\n\nRecent posts:\n" + body if body else "")
        return txt[:max_chars]
    except Exception:
        return ""


def tool_social_read(url_or_handle: str,
                     max_chars: int = 6000) -> Dict[str, Any]:
    """Read public content from social platforms via each one's public,
    no-login path where it exists:
      • Reddit  — appends .json (public)
      • Bluesky — public AppView API (no auth)
      • Mastodon/Fediverse (@user@instance) — instance public API
      • everything else — falls back to web_read (direct→reader→archive)
    For platforms with a hard login wall (Instagram, X, LinkedIn, Facebook)
    it returns the public/archived view and says plainly when that's all
    that's available.  Read-only, public data only."""
    s = (url_or_handle or "").strip()
    if not s:
        return {"ok": False, "error": "no url or handle"}
    low = s.lower()

    # Reddit → .json
    if "reddit.com" in low:
        ju = s.split("?")[0].rstrip("/")
        if not ju.endswith(".json"):
            ju += ".json"
        try:
            status, body, _ = _web_get(ju, timeout=18)
            if status == 200:
                txt = _reddit_json_to_text(body, max_chars)
                if txt:
                    return {"ok": True, "platform": "reddit", "url": s,
                            "text": txt}
        except Exception:
            pass  # fall through to generic

    # Bluesky handle or profile URL
    bsky_handle = ""
    if "bsky.app/profile/" in low:
        bsky_handle = s.split("profile/")[1].split("/")[0].split("?")[0]
    elif re.match(r"^@?[a-z0-9.\-]+\.bsky\.social$", low):
        bsky_handle = s.lstrip("@")
    if bsky_handle:
        out = _bsky_public(bsky_handle, max_chars)
        if out:
            return {"ok": True, "platform": "bluesky", "url": s, "text": out}

    # Mastodon / fediverse @user@instance
    m = re.match(r"^@?([A-Za-z0-9_]+)@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})$", s)
    if m:
        out = _mastodon_public(m.group(2), m.group(1), max_chars)
        if out:
            return {"ok": True, "platform": "mastodon", "url": s, "text": out}

    # Generic / hard-wall platforms: read public or archived copy.
    hard = any(h in low for h in ("instagram.com", "x.com", "twitter.com",
                                  "linkedin.com", "facebook.com"))
    rd = tool_web_read(s, max_chars=max_chars)
    if rd.get("ok"):
        if hard and rd.get("source") in ("reader", "wayback", "direct-thin"):
            rd["text"] = ("[note: this platform gates live content behind a "
                          "login; below is the public / archived view, which "
                          "may be partial]\n\n" + rd["text"])
        rd["platform"] = "generic"
        return rd
    return {"ok": False, "platform": "generic",
            "error": rd.get("error", "could not read"), "url": s}


# ═════════════════════════════════════════════════════════════════════
# GITHUB  — browse and read any public repo (and your own private ones
#           if a token is set).  Built on the public REST API + raw file
#           host; no git clone needed to just look around.
# ═════════════════════════════════════════════════════════════════════

def _gh_token() -> str:
    """PAT from settings, then GITHUB_TOKEN env.  Blank = unauthenticated."""
    tok = ""
    try:
        tok = (load_settings().get("github_token") or "").strip()
    except Exception:
        tok = ""
    return tok or os.environ.get("GITHUB_TOKEN", "").strip()


def _gh_get(path: str, params: Optional[Dict[str, str]] = None,
            raw_accept: bool = False) -> Tuple[int, Any, Dict[str, str]]:
    """GET the GitHub REST API.  Returns (status, parsed-json-or-text, headers).
    `path` is either a full URL or an api path like '/repos/owner/name'."""
    import urllib.parse
    if path.startswith("http"):
        url = path
    else:
        url = "https://api.github.com" + path
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    headers = {
        "User-Agent": "oracle5-kali",
        "Accept": ("application/vnd.github.raw+json" if raw_accept
                   else "application/vnd.github+json"),
        "X-GitHub-Api-Version": "2022-11-28",
    }
    tok = _gh_token()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read(3_000_000).decode("utf-8", "replace")
            hdrs = {k.lower(): v for k, v in r.headers.items()}
            try:
                return r.getcode(), json.loads(body), hdrs
            except Exception:
                return r.getcode(), body, hdrs
    except urllib.error.HTTPError as e:
        hdrs = {k.lower(): v for k, v in (e.headers or {}).items()}
        detail = ""
        try:
            detail = json.loads(e.read().decode("utf-8", "replace")).get(
                "message", "")
        except Exception:
            pass
        return e.code, {"error": detail or str(e)}, hdrs


def _gh_ratelimit_hint(status: int, hdrs: Dict[str, str]) -> str:
    if status == 403 and hdrs.get("x-ratelimit-remaining") == "0":
        return ("GitHub rate limit hit. Set a Personal Access Token in "
                "Settings (github_token) or the GITHUB_TOKEN env var to raise "
                "the limit from 60 to 5000 requests/hour.")
    if status == 401:
        return "GitHub rejected the token (401). Check github_token in Settings."
    return ""


def _gh_split_repo(repo: str) -> Tuple[str, str]:
    """Accept 'owner/name' or a github URL; return (owner, name)."""
    repo = (repo or "").strip()
    repo = re.sub(r"^https?://github\.com/", "", repo)
    repo = repo.rstrip("/").removesuffix(".git")
    parts = [p for p in repo.split("/") if p]
    if len(parts) >= 2:
        return parts[0], parts[1]
    return (parts[0] if parts else ""), ""


def tool_github(action: str, query: str = "", repo: str = "",
                user: str = "", path: str = "", ref: str = "",
                limit: int = 10) -> Dict[str, Any]:
    """Browse and read GitHub without cloning.  Actions:
      • search_repos  query=…              — top repos matching a query
      • search_code   query=…  repo=opt    — code search (token recommended)
      • user_repos    user=…               — a user's repositories
      • repo_info     repo=owner/name      — description, stars, language, …
      • tree          repo=…  path=opt     — list files/dirs in the repo
      • read          repo=…  path=file    — read one file's contents
      • readme        repo=…               — the repo README, decoded
      • releases      repo=…               — recent releases
      • issues        repo=…               — recent open issues
    Public by default; set github_token to reach private repos."""
    action = (action or "").strip().lower()
    limit = max(1, min(int(limit or 10), 30))

    def fail(status, payload, hdrs):
        msg = payload.get("error") if isinstance(payload, dict) else str(payload)
        hint = _gh_ratelimit_hint(status, hdrs)
        return {"ok": False, "error": f"GitHub {status}: {msg or 'request failed'}"
                + (f" — {hint}" if hint else "")}

    try:
        if action == "search_repos":
            if not query:
                return {"ok": False, "error": "no query"}
            st, data, h = _gh_get("/search/repositories",
                                  {"q": query, "sort": "stars",
                                   "order": "desc", "per_page": str(limit)})
            if st != 200:
                return fail(st, data, h)
            items = data.get("items", [])[:limit]
            lines = [f"GitHub repos for: {query}"]
            out = []
            for it in items:
                full = it.get("full_name", "")
                stars = it.get("stargazers_count", 0)
                lang = it.get("language") or "—"
                desc = (it.get("description") or "").strip()
                lines.append(f"\n★ {stars}  {full}  [{lang}]")
                if desc:
                    lines.append(f"  {desc[:200]}")
                lines.append(f"  https://github.com/{full}")
                out.append({"full_name": full, "stars": stars,
                            "language": lang, "description": desc,
                            "url": f"https://github.com/{full}"})
            return {"ok": True, "results": out, "text": "\n".join(lines)}

        if action == "search_code":
            if not query:
                return {"ok": False, "error": "no query"}
            q = query + (f" repo:{repo}" if repo else "")
            st, data, h = _gh_get("/search/code",
                                  {"q": q, "per_page": str(limit)})
            if st != 200:
                return fail(st, data, h)
            items = data.get("items", [])[:limit]
            lines = [f"Code matches for: {q}"]
            out = []
            for it in items:
                full = it.get("repository", {}).get("full_name", "")
                p = it.get("path", "")
                url = it.get("html_url", "")
                lines.append(f"\n{full} :: {p}\n  {url}")
                out.append({"repo": full, "path": p, "url": url})
            return {"ok": True, "results": out, "text": "\n".join(lines)}

        if action == "user_repos":
            u = (user or query).strip()
            if not u:
                return {"ok": False, "error": "no user"}
            st, data, h = _gh_get(f"/users/{u}/repos",
                                  {"sort": "updated", "per_page": str(limit)})
            if st != 200:
                return fail(st, data, h)
            lines = [f"Repositories for {u}:"]
            out = []
            for it in (data if isinstance(data, list) else [])[:limit]:
                name = it.get("name", "")
                stars = it.get("stargazers_count", 0)
                lang = it.get("language") or "—"
                desc = (it.get("description") or "").strip()
                lines.append(f"\n★ {stars}  {name}  [{lang}]")
                if desc:
                    lines.append(f"  {desc[:160]}")
                out.append({"name": name, "stars": stars, "language": lang,
                            "description": desc,
                            "url": it.get("html_url", "")})
            return {"ok": True, "results": out, "text": "\n".join(lines)}

        if action == "repo_info":
            owner, name = _gh_split_repo(repo)
            if not (owner and name):
                return {"ok": False, "error": "repo must be 'owner/name'"}
            st, d, h = _gh_get(f"/repos/{owner}/{name}")
            if st != 200:
                return fail(st, d, h)
            txt = (f"{d.get('full_name')}\n"
                   f"{(d.get('description') or '').strip()}\n\n"
                   f"★ {d.get('stargazers_count',0)}  "
                   f"⑂ {d.get('forks_count',0)}  "
                   f"language: {d.get('language') or '—'}  "
                   f"default branch: {d.get('default_branch')}\n"
                   f"open issues: {d.get('open_issues_count',0)}  "
                   f"updated: {d.get('updated_at','')}\n"
                   f"{d.get('html_url','')}")
            return {"ok": True, "info": {
                "full_name": d.get("full_name"),
                "description": d.get("description"),
                "stars": d.get("stargazers_count"),
                "forks": d.get("forks_count"),
                "language": d.get("language"),
                "default_branch": d.get("default_branch"),
                "open_issues": d.get("open_issues_count"),
                "url": d.get("html_url")}, "text": txt}

        if action == "tree":
            owner, name = _gh_split_repo(repo)
            if not (owner and name):
                return {"ok": False, "error": "repo must be 'owner/name'"}
            branch = ref
            if not branch:
                st, info, h = _gh_get(f"/repos/{owner}/{name}")
                if st != 200:
                    return fail(st, info, h)
                branch = info.get("default_branch", "main")
            st, d, h = _gh_get(
                f"/repos/{owner}/{name}/git/trees/{branch}",
                {"recursive": "1"})
            if st != 200:
                return fail(st, d, h)
            entries = d.get("tree", [])
            sub = (path or "").strip("/")
            if sub:
                entries = [e for e in entries
                           if e.get("path", "").startswith(sub)]
            entries = entries[:300]
            lines = [f"{owner}/{name} @ {branch}"
                     + (f"  (under {sub}/)" if sub else "")]
            out = []
            for e in entries:
                mark = "📁" if e.get("type") == "tree" else "  "
                lines.append(f"{mark} {e.get('path')}")
                out.append({"path": e.get("path"), "type": e.get("type")})
            if d.get("truncated"):
                lines.append("… (tree truncated by GitHub)")
            return {"ok": True, "branch": branch, "entries": out,
                    "text": "\n".join(lines)}

        if action == "read":
            owner, name = _gh_split_repo(repo)
            if not (owner and name and path):
                return {"ok": False,
                        "error": "need repo='owner/name' and path='file'"}
            branch = ref
            if not branch:
                st, info, h = _gh_get(f"/repos/{owner}/{name}")
                if st != 200:
                    return fail(st, info, h)
                branch = info.get("default_branch", "main")
            raw_url = (f"https://raw.githubusercontent.com/{owner}/{name}/"
                       f"{branch}/{path.lstrip('/')}")
            try:
                status, body, _ = _web_get(raw_url, timeout=20)
            except Exception as e:
                return {"ok": False,
                        "error": f"read failed: {type(e).__name__}: {e}"}
            if status != 200:
                return {"ok": False, "error": f"HTTP {status} reading {path}"}
            truncated = len(body) > 40000
            shown = body[:40000] + ("\n… (truncated)" if truncated else "")
            return {"ok": True, "repo": f"{owner}/{name}", "path": path,
                    "branch": branch, "truncated": truncated,
                    "text": f"{owner}/{name}@{branch}:{path}\n\n{shown}"}

        if action == "readme":
            owner, name = _gh_split_repo(repo)
            if not (owner and name):
                return {"ok": False, "error": "repo must be 'owner/name'"}
            st, d, h = _gh_get(f"/repos/{owner}/{name}/readme",
                               raw_accept=True)
            if st != 200:
                return fail(st, d, h)
            if isinstance(d, dict) and d.get("content"):
                import base64
                try:
                    d = base64.b64decode(d["content"]).decode(
                        "utf-8", "replace")
                except Exception:
                    d = ""
            text = d if isinstance(d, str) else ""
            truncated = len(text) > 20000
            if truncated:
                text = text[:20000] + "\n… (truncated)"
            return {"ok": True, "repo": f"{owner}/{name}",
                    "truncated": truncated,
                    "text": f"README — {owner}/{name}\n\n{text}"}

        if action == "releases":
            owner, name = _gh_split_repo(repo)
            if not (owner and name):
                return {"ok": False, "error": "repo must be 'owner/name'"}
            st, d, h = _gh_get(f"/repos/{owner}/{name}/releases",
                               {"per_page": str(limit)})
            if st != 200:
                return fail(st, d, h)
            lines = [f"Releases — {owner}/{name}"]
            out = []
            for r in (d if isinstance(d, list) else [])[:limit]:
                tag = r.get("tag_name", "")
                nm = r.get("name") or tag
                when = (r.get("published_at") or "")[:10]
                lines.append(f"\n{tag}  {nm}  ({when})")
                out.append({"tag": tag, "name": nm, "published": when,
                            "url": r.get("html_url", "")})
            return {"ok": True, "results": out, "text": "\n".join(lines)}

        if action == "issues":
            owner, name = _gh_split_repo(repo)
            if not (owner and name):
                return {"ok": False, "error": "repo must be 'owner/name'"}
            st, d, h = _gh_get(f"/repos/{owner}/{name}/issues",
                               {"state": "open", "per_page": str(limit)})
            if st != 200:
                return fail(st, d, h)
            lines = [f"Open issues — {owner}/{name}"]
            out = []
            for it in (d if isinstance(d, list) else [])[:limit]:
                if it.get("pull_request"):
                    continue  # issues endpoint also returns PRs
                num = it.get("number")
                title = (it.get("title") or "").strip()
                lines.append(f"\n#{num}  {title[:160]}")
                out.append({"number": num, "title": title,
                            "url": it.get("html_url", "")})
            return {"ok": True, "results": out, "text": "\n".join(lines)}

        return {"ok": False, "error": f"unknown github action '{action}'"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}


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
    # Attribute blob.  Each whitespace-separated token is EITHER a proper
    # key="value" pair OR a bare word — the latter tolerates the quirk where
    # a model emits `<tool tool name="run">` (a stray duplicate "tool") or
    # `<tool run>`.  Without the bare-word alternative the whole tag fails to
    # match, so it neither executes NOR gets stripped and leaks into the chat
    # as raw text.  name="..."/json=... are still pulled out of this blob by
    # the dedicated regexes below, so a stray word changes nothing else.
    r'((?:\s+(?:[a-zA-Z_]+\s*=\s*(?:"[^"]*"|\'[^\']*\'|[\u201c\u201d][^\u201c\u201d]*[\u201c\u201d])'
    r'|[^\s=>"\']+))*)'  # attrs (key="value" pairs and/or bare words)
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


def _escape_raw_ctrl_in_strings(s: str) -> str:
    """Escape raw control characters (newlines, tabs, CRs) that appear INSIDE
    a JSON string literal.

    This is the single biggest reason a model-emitted tool call fails to
    parse: a multi-line value — most often a `content` field holding a whole
    document or a block of code — is written with literal newlines instead of
    \\n.  Strict json.loads rejects that, the call collapses to {"_raw": ...},
    and a propose_edit / write_file then renders NO diff card while the model
    believes one is waiting.  Walk the text tracking string state and
    backslash escapes, and rewrite only the control chars that sit inside a
    string; structural whitespace between tokens is left exactly as-is."""
    out: List[str] = []
    in_str = False
    esc = False
    for ch in s:
        if in_str:
            if esc:
                out.append(ch)
                esc = False
            elif ch == "\\":
                out.append(ch)
                esc = True
            elif ch == '"':
                out.append(ch)
                in_str = False
            elif ch == "\n":
                out.append("\\n")
            elif ch == "\r":
                out.append("\\r")
            elif ch == "\t":
                out.append("\\t")
            elif ch < " ":
                out.append("\\u%04x" % ord(ch))
            else:
                out.append(ch)
        else:
            out.append(ch)
            if ch == '"':
                in_str = True
    return "".join(out)


def _loads_lenient(json_src: str) -> Any:
    """json.loads, but forgiving of the one mistake models make most: literal
    control characters inside string values.  Tries a strict parse first, then
    one repaired parse.  Returns the parsed object, or None if it still can't
    be made sense of (caller falls back to {"_raw": ...})."""
    if not json_src:
        return {}
    try:
        return json.loads(json_src)
    except json.JSONDecodeError:
        pass
    try:
        return json.loads(_escape_raw_ctrl_in_strings(json_src))
    except json.JSONDecodeError:
        return None


# Models sometimes hallucinate a tool name for writing a file (the classic is
# "write_text_file", which exists nowhere) — or pick a reasonable-but-wrong
# synonym.  Route every one of them to the real write path so the diff card
# actually renders instead of silently vanishing as an unknown tool.  All of
# these render as a propose-style diff card and write nothing until Apply.
_TOOL_NAME_ALIASES = {
    "write_text_file": "write_file",
    "writetextfile":   "write_file",
    "writefile":       "write_file",
    "save_file":       "write_file",
    "savefile":        "write_file",
    "save_text_file":  "write_file",
    "create_file":     "write_file",
    "createfile":      "write_file",
    "new_file":        "write_file",
    "write_to_file":   "write_file",
    "save_to_file":    "write_file",
    "save":            "write_file",
    "save_document":   "write_file",
    "make_file":       "write_file",
    "edit_file":       "propose_edit",
    "editfile":        "propose_edit",
    "propose_file":    "propose_edit",
    "propose_write":   "propose_edit",
    "apply_edit":      "propose_edit",
}

# Field aliases for the write path: the model may put the body under any of
# these instead of "content".  Fold them in so the card never comes up empty.
_CONTENT_FIELD_ALIASES = ("text", "body", "contents", "data",
                          "file_text", "file_content", "filecontent")


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
            # Literal newlines / unescaped control chars in a string value are
            # the usual cause (a multi-line `content` for propose_edit).  Try
            # a repaired parse before giving up so the call still carries real
            # path/content and its diff card actually renders.
            recovered = _loads_lenient(json_src)
            parsed = recovered if recovered is not None else {"_raw": json_src}

        # Resolve tool name
        name = name_attr
        if not name and isinstance(parsed, dict):
            for key in ("name", "tool", "tool_name"):
                if key in parsed:
                    name = parsed.pop(key)
                    break
        # Map invented / synonym tool names to their real handler (e.g. the
        # hallucinated "write_text_file" → "write_file") so the proposal still
        # renders instead of being dropped as unknown.
        if name:
            name = _TOOL_NAME_ALIASES.get(str(name).strip().lower(), name)
        # Unwrap common nested arg containers
        if isinstance(parsed, dict):
            for inner_key in ("arguments", "args", "parameters", "params"):
                if isinstance(parsed.get(inner_key), dict):
                    parsed = parsed[inner_key]
                    break
        # For the write path, accept the body under a few aliases too, so a
        # propose_edit/write_file never renders empty just because the model
        # called the field "text" or "body" instead of "content".
        if isinstance(parsed, dict) and name in ("propose_edit", "write_file") \
                and "content" not in parsed:
            for alt in _CONTENT_FIELD_ALIASES:
                if alt in parsed:
                    parsed["content"] = parsed.pop(alt)
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
    # LAST-RESORT belt-and-suspenders.  The parser above is liberal, but a
    # model can always invent a tag shape we didn't anticipate.  The execution
    # side can't run a tag it couldn't parse — but the one thing that must
    # NEVER happen is a raw <tool …> tag being shown to the operator as chat
    # text (the bug that made Kali look like it was "typing" commands instead
    # of running them).  So whatever shape slipped through, scrub any residual
    # <tool …>…</tool> block and any leftover bare <tool …> opener from the
    # DISPLAY string.  This only affects what's rendered, never what executed.
    if re.search(r'<\s*\\?\s*/?\s*tool\b', out, re.IGNORECASE):
        out = re.sub(r'<tool\b[^>]*>.*?<\\?\s*/\s*tool\s*>', '', out,
                     flags=re.DOTALL | re.IGNORECASE)
        # any leftover opener or orphaned closer remnant
        out = re.sub(r'<\\?\s*/?\s*tool\b[^>]*>?', '', out, flags=re.IGNORECASE)
    return out.strip()


# ── Reasoning / "thoughts" blocks ──
# Some models (DeepSeek reasoners) put their chain-of-thought inline as
# <think>...</think> in the content stream.  These regexes pull it out so
# the visible reply stays clean and the reasoning can live in a collapsible
# panel instead.  (Other models send it in a separate reasoning_content
# delta field, captured in the backend.)
THINK_RE = re.compile(
    r'<think\b[^>]*>(.*?)</think\s*>', re.DOTALL | re.IGNORECASE)
# A think block opened but not yet closed (still streaming).
THINK_PARTIAL_RE = re.compile(
    r'<think\b[^>]*>(.*)$', re.DOTALL | re.IGNORECASE)


def extract_think_blocks(text: str) -> Tuple[str, str]:
    """Split content into (visible_text, reasoning_text).  Pulls every
    complete <think>…</think> block out and concatenates their bodies as the
    reasoning; an unclosed trailing <think>… (mid-stream) is also moved to
    reasoning so it never flashes in the reply."""
    thoughts: List[str] = []

    def _grab(m: "re.Match[str]") -> str:
        thoughts.append((m.group(1) or "").strip())
        return ""

    visible = THINK_RE.sub(_grab, text)
    pm = THINK_PARTIAL_RE.search(visible)
    if pm:
        thoughts.append((pm.group(1) or "").strip())
        visible = visible[:pm.start()]
    reasoning = "\n".join(t for t in thoughts if t).strip()
    return visible, reasoning


def strip_think_blocks(text: str) -> str:
    """Just the visible text, with all <think> reasoning removed."""
    return extract_think_blocks(text)[0]


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
