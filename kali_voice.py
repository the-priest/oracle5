#!/usr/bin/env python3
"""
kali_voice — speech in / speech out for Kali.

Two halves, both self-contained (stdlib only, no GTK, no third-party
Python packages required at import time):

  • SpeechToText  — record the mic to a temp WAV with whatever CLI
                    recorder the box has (parecord / arecord / ffmpeg),
                    then transcribe it through Groq's OpenAI-compatible
                    Whisper endpoint (reuses the operator's existing Groq
                    key — fast, accurate, no model download).

  • TextToSpeech  — a queue-backed worker that speaks text out loud.
                    Prefers Piper (local neural voice, sounds good) and
                    falls back to espeak-ng (always-available, robotic).
                    Fully interruptible: stop() drops the queue and kills
                    whatever is mid-sentence.

  • SpeechStreamer — turns a growing stream of assistant tokens into a
                    sequence of complete, speakable sentences while
                    skipping fenced code blocks, so TTS can start talking
                    before the model has finished writing.

Nothing here talks to the rest of the app except through the small
`get_settings` callable handed to the constructors, so it stays easy to
test in isolation and impossible to wedge the UI thread.
"""

from __future__ import annotations

import os
import re
import sys
import json
import queue
import shutil
import signal
import tempfile
import threading
import subprocess
import urllib.request
import urllib.error
from io import BytesIO
from typing import Callable, Dict, List, Optional, Tuple

# ── logging shim ─────────────────────────────────────────────────────
# The app injects kali_core.log; until then we no-op so the module is
# importable and testable on its own.
_LOG: Callable[[str], None] = lambda _m: None


def set_logger(fn: Callable[[str], None]) -> None:
    global _LOG
    if callable(fn):
        _LOG = fn


def _log(msg: str) -> None:
    try:
        _LOG(f"voice: {msg}")
    except Exception:
        pass


GROQ_TRANSCRIBE_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
DEFAULT_STT_MODEL   = "whisper-large-v3-turbo"

# Provider-aware speech-to-text.  Both endpoints are OpenAI-compatible
# multipart POSTs to /audio/transcriptions and return {"text": "..."}.
#
# IMPORTANT: SiliconFlow's SenseVoiceSmall endpoint accepts ONLY `file`
# and `model` — sending Whisper-style extras (response_format, temperature,
# language) makes it reject the request.  Groq's Whisper accepts the extras.
# So each provider declares exactly which optional fields it tolerates.
#
# `url_setting` lets the host derive the endpoint from the operator's
# WORKING chat base_url (api.siliconflow.com vs .cn differ by account/region),
# so transcription rides the same host+key that chat already uses.  If the
# host doesn't supply a base, we fall back to the hardcoded `url`.
STT_PROVIDERS: Dict[str, Dict] = {
    "siliconflow": {
        "label":         "SiliconFlow (SenseVoiceSmall)",
        "url":           "https://api.siliconflow.com/v1/audio/transcriptions",
        "base_setting":  "siliconflow_base_url",  # optional override
        "provider_key":  "siliconflow",            # base_url comes from PROVIDERS
        "key_setting":   "siliconflow_api_key",
        "default_model": "FunAudioLLM/SenseVoiceSmall",
        "model_setting": "stt_model_siliconflow",
        "extra_fields":  [],                       # file + model ONLY
    },
    "groq": {
        "label":         "Groq (Whisper)",
        "url":           GROQ_TRANSCRIBE_URL,
        "provider_key":  "groq",
        "key_setting":   "groq_api_key",
        "default_model": DEFAULT_STT_MODEL,
        "model_setting": "stt_model",
        "extra_fields":  ["response_format", "temperature", "language"],
    },
}
# Preference order when settings say "auto" and the active provider can't
# transcribe: try these in turn, first one with a key wins.
STT_AUTO_ORDER = ["siliconflow", "groq"]


def _stt_url(cfg: Dict, settings: Dict) -> str:
    """Resolve the transcription endpoint.  Prefer a base derived from the
    operator's configured chat base_url for this provider (same host that
    already works for chat), then append /audio/transcriptions.  Fall back
    to the hardcoded url."""
    # 1) explicit per-provider base override in settings, if any
    base = ""
    bset = cfg.get("base_setting")
    if bset:
        base = (settings.get(bset) or "").strip()
    # 2) the provider's chat base_url (e.g. siliconflow_base_url style keys
    #    that some builds store), else the hardcoded fallback url
    if not base:
        pk = cfg.get("provider_key")
        if pk:
            base = (settings.get(f"{pk}_base_url") or "").strip()
    if base:
        return base.rstrip("/") + "/audio/transcriptions"
    return cfg["url"]


# ═════════════════════════════════════════════════════════════════════
# TEXT CLEANING — strip the markup the model writes so the voice reads
# prose, not asterisks, backticks, tool tags, or raw code.
# ═════════════════════════════════════════════════════════════════════

_TOOL_TAG_RE   = re.compile(r"<tool\b[^>]*>.*?</tool\s*>", re.DOTALL | re.IGNORECASE)
_TOOL_FRAG_RE  = re.compile(r"<tool\b[^>]*?>.*?$", re.DOTALL | re.IGNORECASE)
_FENCE_RE      = re.compile(r"```.*?```", re.DOTALL)
_FENCE_OPEN_RE = re.compile(r"```.*$", re.DOTALL)
_INLINE_CODE   = re.compile(r"`([^`]+)`")
_MD_LINK       = re.compile(r"\[([^\]]+)\]\((?:[^)]+)\)")
_BARE_URL      = re.compile(r"https?://\S+")
_EMPHASIS      = re.compile(r"(\*\*|\*|__|_|~~)")
_HEADING       = re.compile(r"^\s{0,3}#{1,6}\s*")
_BLOCKQUOTE    = re.compile(r"^\s{0,3}>\s?")
_LIST_BULLET   = re.compile(r"^\s{0,3}[-*+]\s+")
_LIST_NUM      = re.compile(r"^\s{0,3}\d+[.)]\s+")
_HRULE         = re.compile(r"^\s{0,3}([-*_])\s*(?:\1\s*){2,}$")
_WS            = re.compile(r"[ \t]+")


def _clean_inline(line: str) -> str:
    """Strip inline markdown from a single line, leaving readable words."""
    s = line
    s = _MD_LINK.sub(r"\1", s)            # [text](url) -> text
    s = _BARE_URL.sub(" link ", s)        # don't spell out URLs
    s = _INLINE_CODE.sub(r"\1", s)        # `code` -> code
    s = _HEADING.sub("", s)               # ## Heading -> Heading
    s = _BLOCKQUOTE.sub("", s)
    s = _LIST_BULLET.sub("", s)
    s = _LIST_NUM.sub("", s)
    s = _EMPHASIS.sub("", s)              # **bold** / _italic_ markers
    s = s.replace("`", "")
    s = _WS.sub(" ", s).strip()
    if _HRULE.match(line.strip()):
        return ""
    # A line that's pure punctuation / symbols has nothing to say.
    if s and not re.search(r"[A-Za-z0-9]", s):
        return ""
    return s


def clean_for_speech(text: str) -> str:
    """Full one-shot clean of a complete message for TTS.  Everything collapses
    to a single flowing line — newlines, blank lines and code blocks would each
    otherwise become a long dead pause in the spoken output."""
    if not text:
        return ""
    s = _TOOL_TAG_RE.sub(" ", text)
    s = _TOOL_FRAG_RE.sub(" ", s)
    s = _FENCE_RE.sub(" ", s)             # code blocks: drop, no pause
    s = _FENCE_OPEN_RE.sub(" ", s)        # dangling open fence
    out: List[str] = []
    for ln in s.split("\n"):
        c = _clean_inline(ln)
        if c:
            out.append(c)
    joined = " ".join(out)                # SPACE, not newline — no para pauses
    joined = re.sub(r"\s+", " ", joined)  # collapse every whitespace run
    joined = re.sub(r"([.!?]){2,}", r"\1", joined)  # "..." -> "." (no stacked pause)
    return joined.strip()


# ── sentence segmentation ────────────────────────────────────────────
# Split into chunks short enough to feel responsive and to make stop()
# snappy, but not so short the cadence turns choppy.  We respect sentence
# punctuation, fall back to newlines, and hard-wrap anything very long.

_ABBREV = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc",
    "e.g", "i.e", "no", "fig", "al", "inc", "ltd", "co", "a.m", "p.m",
}
_SENT_BOUNDARY = re.compile(r"([.!?…]+[\"')\]]?)(\s+|$)")
_MAX_CHUNK = 240
_MIN_CHUNK = 8


def _looks_like_abbrev(text: str) -> bool:
    tail = re.split(r"\s+", text.strip())[-1] if text.strip() else ""
    tail = tail.rstrip(".!?…\"')]").lower()
    if tail in _ABBREV:
        return True
    # single capital letter + dot ("A.")  or  a number ("3.14")
    if re.fullmatch(r"[A-Za-z]", tail):
        return True
    if re.fullmatch(r"\d+", tail):
        return True
    return False


def split_sentences(text: str) -> List[str]:
    """Greedy sentence splitter tuned for spoken output."""
    text = text.strip()
    if not text:
        return []
    chunks: List[str] = []
    buf = ""
    i = 0
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            if buf.strip():
                chunks.append(buf.strip())
                buf = ""
            continue
        pos = 0
        for m in _SENT_BOUNDARY.finditer(line):
            seg = line[pos:m.end()]
            cand = (buf + " " + seg).strip() if buf else seg.strip()
            if len(cand) >= _MIN_CHUNK and not _looks_like_abbrev(line[pos:m.start() + 1]):
                chunks.append(cand)
                buf = ""
            else:
                buf = cand
            pos = m.end()
        rest = line[pos:].strip()
        if rest:
            buf = (buf + " " + rest).strip() if buf else rest
        # End of a (non-blank) line: treat as a soft boundary so list
        # items and headings get their own breath.
        if buf and len(buf) >= _MIN_CHUNK:
            chunks.append(buf.strip())
            buf = ""
    if buf.strip():
        chunks.append(buf.strip())

    # Hard-wrap any monster chunk so a single utterance can't run forever.
    wrapped: List[str] = []
    for c in chunks:
        while len(c) > _MAX_CHUNK:
            cut = c.rfind(" ", 0, _MAX_CHUNK)
            if cut <= 0:
                cut = _MAX_CHUNK
            wrapped.append(c[:cut].strip())
            c = c[cut:].strip()
        if c:
            wrapped.append(c)
    return [w for w in wrapped if w]


def merge_for_speech(chunks: List[str], first_max: int = 90,
                     target: int = 600) -> List[str]:
    """Merge sentence-chunks into fewer, larger utterances.

    Speaking each sentence as its own subprocess puts a spawn-latency GAP at
    every period — that's the long stop between sentences.  Merging adjacent
    sentences into one utterance lets the engine handle the (short, natural)
    sentence pauses internally, with no gap.  The FIRST utterance is kept short
    so audio starts talking quickly instead of waiting on a big synth."""
    if not chunks:
        return []
    out: List[str] = []
    buf = ""
    first = True
    for c in chunks:
        cap = first_max if first else target
        if not buf:
            buf = c
        elif len(buf) + 1 + len(c) <= cap:
            buf = buf + " " + c
        else:
            out.append(buf)
            buf = c
            first = False
        if first and len(buf) >= first_max:
            out.append(buf)
            buf = ""
            first = False
    if buf:
        out.append(buf)
    return out


# ═════════════════════════════════════════════════════════════════════
# SPEECH STREAMER — feed growing assistant text, get back complete
# sentences ready to speak, code blocks skipped.
# ═════════════════════════════════════════════════════════════════════

class SpeechStreamer:
    """Stateful: call feed() repeatedly with the *full* assistant content
    so far; it returns any newly-completed sentences (from lines that are
    fully received and outside code fences).  Call flush() at the end to
    drain the final partial line.

    Content grows by appended tokens only, so the committed prefix is
    stable — we just remember how many lines we've folded in and how much
    speakable text we've already emitted."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._committed_lines = 0
        self._in_code = False
        self._pending = ""        # speakable text not yet emitted as sentences

    def _fold(self, lines: List[str]) -> None:
        for ln in lines[self._committed_lines:]:
            stripped = ln.strip()
            if stripped.startswith("```"):
                self._in_code = not self._in_code
                continue
            if self._in_code:
                continue
            c = _clean_inline(ln)
            if c:
                self._pending += c + "\n"
        self._committed_lines = len(lines)

    def _emit(self, final: bool) -> List[str]:
        if not self._pending.strip():
            if final:
                self._pending = ""
            return []
        sentences = split_sentences(self._pending)
        if not sentences:
            return []
        if final:
            self._pending = ""
            return sentences
        # Mid-stream: hold the last fragment back unless the source clearly
        # ended it with sentence punctuation (so we don't speak half a
        # thought).  Heuristic: if pending doesn't end on a boundary, keep
        # the final chunk buffered.
        if re.search(r"[.!?…][\"')\]]?\s*$", self._pending):
            self._pending = ""
            return sentences
        held = sentences[-1]
        self._pending = held + "\n"
        emit = sentences[:-1]
        return emit

    def feed(self, full_content: str) -> List[str]:
        if "\n" not in full_content:
            return []
        completed = full_content.rsplit("\n", 1)[0]
        self._fold(completed.split("\n"))
        return self._emit(final=False)

    def flush(self, full_content: str) -> List[str]:
        self._fold(full_content.split("\n"))
        return self._emit(final=True)


# ═════════════════════════════════════════════════════════════════════
# SPEECH TO TEXT — record + transcribe via Groq Whisper
# ═════════════════════════════════════════════════════════════════════

class SpeechToText:
    """Tap-to-record, tap-to-stop, then transcribe.  Recording is done by
    a CLI tool so we don't drag in PortAudio/sounddevice; transcription
    rides the operator's existing Groq key."""

    def __init__(self, get_settings: Callable[[], Dict]) -> None:
        self.get_settings = get_settings
        self._proc: Optional[subprocess.Popen] = None
        self._wav: Optional[str] = None
        self._errf: Optional[str] = None       # recorder stderr capture file
        self._err_fh = None                     # open handle while recording
        self._last_err: Optional[str] = None    # human reason for last failure
        self._recorder = self._detect_recorder()

    # ── capability ──
    @staticmethod
    def _detect_recorder() -> Optional[str]:
        # Order matters: parecord/pw-record speak to PipeWire/PulseAudio (the
        # modern desktop default and the most likely to Just Work); arecord is
        # raw ALSA; ffmpeg is the last resort.
        for name in ("parecord", "pw-record", "arecord", "ffmpeg"):
            if shutil.which(name):
                return name
        return None

    def recorder_available(self) -> bool:
        return self._recorder is not None

    def recorder_name(self) -> str:
        return self._recorder or "none"

    def _pick_stt(self) -> Optional[Tuple[str, Dict[str, str]]]:
        """Choose an STT provider: explicit setting wins, then the active
        chat provider if it can transcribe, then auto-order by first key
        present.  Returns (provider_id, config) or None if no key anywhere."""
        s = self.get_settings()

        def has_key(pid: str) -> bool:
            cfg = STT_PROVIDERS.get(pid)
            return bool(cfg and (s.get(cfg["key_setting"]) or "").strip())

        choice = (s.get("stt_provider") or "auto").strip().lower()
        if choice in STT_PROVIDERS and has_key(choice):
            return choice, STT_PROVIDERS[choice]
        if choice == "auto":
            active = (s.get("active_provider") or "").strip().lower()
            if active in STT_PROVIDERS and has_key(active):
                return active, STT_PROVIDERS[active]
            for pid in STT_AUTO_ORDER:
                if has_key(pid):
                    return pid, STT_PROVIDERS[pid]
        # Explicit choice but no key for it → still try anything with a key
        for pid in STT_AUTO_ORDER:
            if has_key(pid):
                return pid, STT_PROVIDERS[pid]
        return None

    def has_key(self) -> bool:
        return self._pick_stt() is not None

    def unavailable_reason(self) -> Optional[str]:
        if not self._recorder:
            return ("No microphone recorder found.  Install pulseaudio-utils "
                    "(parecord), pipewire-utils (pw-record), or alsa-utils "
                    "(arecord).")
        if not self.has_key():
            return ("No transcription key set.  Voice input needs a "
                    "SiliconFlow or Groq key — add one in Settings → "
                    "Backends.")
        return None

    # ── recording ──
    def _build_record_cmd(self, path: str) -> List[str]:
        if self._recorder == "parecord":
            return ["parecord", "--channels=1", "--rate=16000",
                    "--format=s16le", "--file-format=wav", path]
        if self._recorder == "pw-record":
            # Native PipeWire recorder — works where parecord can't (no
            # pipewire-pulse shim installed).
            return ["pw-record", "--rate=16000", "--channels=1",
                    "--format=s16", path]
        if self._recorder == "arecord":
            return ["arecord", "-q", "-f", "S16_LE", "-c", "1",
                    "-r", "16000", "-t", "wav", path]
        # ffmpeg: try pulse, the most common desktop source
        return ["ffmpeg", "-hide_banner", "-loglevel", "error",
                "-f", "pulse", "-i", "default",
                "-ac", "1", "-ar", "16000", "-y", path]

    def start(self) -> bool:
        if self._proc is not None:
            return False
        if not self._recorder:
            self._last_err = "no recorder installed"
            return False
        fd, path = tempfile.mkstemp(prefix="kali_rec_", suffix=".wav")
        os.close(fd)
        self._wav = path
        efd, epath = tempfile.mkstemp(prefix="kali_rec_", suffix=".err")
        os.close(efd)
        self._errf = epath
        self._last_err = None
        cmd = self._build_record_cmd(path)
        try:
            # Keep the recorder's stderr — a dead/muted mic, a missing
            # PulseAudio/PipeWire source, or a permission block all show up
            # here.  Discarding it (the old behaviour) made every failure
            # look identical to "no audio captured".
            self._err_fh = open(epath, "wb")
            self._proc = subprocess.Popen(
                cmd, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=self._err_fh)
            _log(f"recording via {self._recorder} -> {path}")
            return True
        except Exception as e:
            _log(f"record start failed: {e}")
            self._last_err = str(e)
            self._proc = None
            self._close_err_fh()
            self._cleanup()
            return False

    def is_recording(self) -> bool:
        return self._proc is not None

    def stop(self) -> Optional[str]:
        """Stop recording; return the WAV path (or None on failure).  On
        failure, self._last_err carries the recorder's own reason."""
        p = self._proc
        self._proc = None
        if p is None:
            return None
        try:
            # SIGINT lets ffmpeg/arecord finalise the WAV header cleanly.
            p.send_signal(signal.SIGINT)
            try:
                p.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                p.terminate()
                try:
                    p.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    p.kill()
        except Exception as e:
            _log(f"record stop hiccup: {e}")
        self._close_err_fh()
        err_txt = self._read_err()
        path = self._wav
        size = os.path.getsize(path) if (path and os.path.exists(path)) else 0
        if size > 44:
            # Real WAV.  Stash any stderr anyway (could explain a silent clip),
            # but hand the file back for transcription.
            self._last_err = err_txt or None
            self._discard_err()
            return path
        # No usable audio — keep the recorder's reason so the caller can show
        # the operator WHY instead of a generic "no audio".
        if err_txt:
            self._last_err = err_txt
        elif size == 0:
            self._last_err = "recorder produced no file"
        else:
            self._last_err = "recorder produced an empty clip"
        _log(f"no audio: {self._last_err}")
        self._discard_err()
        self._cleanup()
        return None

    def cancel(self) -> None:
        """Abort an in-progress recording and bin the file."""
        p = self._proc
        self._proc = None
        if p is not None:
            try:
                p.terminate()
                p.wait(timeout=1.0)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
        self._close_err_fh()
        self._discard_err()
        self._cleanup()

    def _cleanup(self) -> None:
        if self._wav and os.path.exists(self._wav):
            try:
                os.remove(self._wav)
            except Exception:
                pass
        self._wav = None

    # ── recorder-stderr plumbing (so a dead mic isn't a silent mystery) ──
    def _close_err_fh(self) -> None:
        if self._err_fh is not None:
            try:
                self._err_fh.close()
            except Exception:
                pass
            self._err_fh = None

    def _read_err(self) -> str:
        """Read + condense the recorder's stderr into a one-line reason."""
        if not self._errf or not os.path.exists(self._errf):
            return ""
        try:
            with open(self._errf, "rb") as f:
                raw = f.read().decode("utf-8", "replace")
        except Exception:
            return ""
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        if not lines:
            return ""
        # Last non-empty line is usually the actual error; keep it short.
        msg = lines[-1]
        low = raw.lower()
        # Add a plain-English hint for the common culprits.
        if "connection refused" in low or "connect" in low and "refused" in low:
            msg += "  (audio server not reachable — is PipeWire/PulseAudio running in this session?)"
        elif "permission denied" in low or "access denied" in low:
            msg += "  (permission denied — your user may not have audio access)"
        elif "no such" in low and ("device" in low or "file" in low):
            msg += "  (the chosen input source doesn't exist — wrong default device?)"
        elif "busy" in low:
            msg += "  (device busy — another app is holding the mic)"
        return msg[:240]

    def _discard_err(self) -> None:
        if self._errf and os.path.exists(self._errf):
            try:
                os.remove(self._errf)
            except Exception:
                pass
        self._errf = None

    def last_error(self) -> Optional[str]:
        """The reason the last recording produced no audio, if any."""
        return self._last_err

    @staticmethod
    def probe_inputs() -> str:
        """Best-effort list of real capture sources, for diagnostics.  Filters
        out .monitor sources (output loopbacks, not microphones)."""
        if shutil.which("pactl"):
            try:
                out = subprocess.run(
                    ["pactl", "list", "short", "sources"],
                    capture_output=True, text=True, timeout=4)
                names = []
                for ln in out.stdout.splitlines():
                    ln = ln.strip()
                    if not ln or "monitor" in ln.lower():
                        continue
                    parts = ln.split("\t")
                    names.append(parts[1] if len(parts) > 1 else ln)
                if names:
                    return ", ".join(names[:4])
                return ""   # pactl worked but found only monitors / nothing
            except Exception:
                pass
        if shutil.which("arecord"):
            try:
                out = subprocess.run(
                    ["arecord", "-l"], capture_output=True, text=True,
                    timeout=4)
                cards = [ln.strip() for ln in out.stdout.splitlines()
                         if ln.strip().startswith("card ")]
                if cards:
                    return "; ".join(cards[:3])
            except Exception:
                pass
        return ""

    def test_capture(self, seconds: float = 4.0) -> Tuple[str, Optional[str]]:
        """Record for a fixed duration then transcribe, returning
        (text, error).  Used by the Settings 'Test microphone' button so the
        operator sees the EXACT result or failure instead of guessing."""
        if self.is_recording():
            return "", "already recording — stop first"
        if not self.start():
            why = self._last_err or "no recorder?"
            return "", f"couldn't start the microphone ({why})"
        import time as _t
        _t.sleep(max(1.0, min(float(seconds), 15.0)))
        wav = self.stop()
        if not wav:
            reason = self._last_err
            probe = self.probe_inputs()
            msg = "no audio captured — "
            msg += (f"recorder said: {reason}. " if reason
                    else "the recorder produced an empty file. ")
            if probe:
                msg += f"Detected input sources: {probe}. "
                msg += "If one of those is your mic, set it as the default input (or unmute it)."
            else:
                msg += ("No usable input sources detected — your mic isn't "
                        "visible to PipeWire/PulseAudio. Check it's plugged in, "
                        "unmuted, and that this session has audio access.")
            return "", msg
        return self.transcribe(wav)

    # ── transcription ──
    def transcribe(self, wav_path: str) -> Tuple[str, Optional[str]]:
        """Returns (text, error).  Blocks — call from a worker thread.

        Tries the chosen STT provider first (SiliconFlow's SenseVoiceSmall
        or Groq's Whisper).  If that provider fails with an auth/endpoint
        error (401/403/404), a server error, or is unreachable, AND another
        provider has a key set, it falls back to that one automatically —
        SiliconFlow -> Groq, the same fallback chain chat uses.  This is why
        a SiliconFlow key that works for chat but is forbidden (403) on the
        transcription endpoint no longer kills voice: Groq Whisper picks up
        the slack."""
        s = self.get_settings()
        candidates = self._stt_candidates(s)
        if not candidates:
            self._safe_remove(wav_path)
            return "", ("No transcription key set — add a SiliconFlow or "
                        "Groq key in Settings → Backends.")
        # Read the recording ONCE and keep the bytes so every fallback
        # attempt can reuse them; bin the temp file immediately after.
        try:
            with open(wav_path, "rb") as f:
                audio = f.read()
        except Exception as e:
            self._safe_remove(wav_path)
            return "", f"could not read recording: {e}"
        self._safe_remove(wav_path)

        last_err = "transcription failed"
        for provider_id, cfg in candidates:
            text, err, retryable = self._transcribe_attempt(
                provider_id, cfg, audio, s)
            if err is None:
                return text, None
            last_err = err
            if not retryable:
                break          # bad audio/request — another provider won't help
            _log(f"STT: {provider_id} failed ({err}); trying next provider")
        return "", last_err

    def _stt_candidates(self, s: Dict
                        ) -> List[Tuple[str, Dict[str, str]]]:
        """Ordered providers to try: the normally-picked one first, then any
        OTHER provider that also has a key — so an auth/endpoint failure on
        the primary can fall back instead of hard-failing.  With only one
        key set, this returns a single provider and behaviour is unchanged."""
        out: List[Tuple[str, Dict[str, str]]] = []
        seen = set()
        primary = self._pick_stt()
        if primary:
            out.append(primary)
            seen.add(primary[0])
        for pid in STT_AUTO_ORDER:
            if pid in seen:
                continue
            cfg = STT_PROVIDERS.get(pid)
            if cfg and (s.get(cfg["key_setting"]) or "").strip():
                out.append((pid, cfg))
                seen.add(pid)
        return out

    def _transcribe_attempt(self, provider_id: str, cfg: Dict[str, str],
                            audio: bytes, s: Dict
                            ) -> Tuple[str, Optional[str], bool]:
        """One provider attempt.  Returns (text, error, retryable).
        retryable=True means it's worth falling back to another provider
        (auth/endpoint/server/network failure); False means the request
        itself was rejected (e.g. 400) or the response was unparseable, so
        retrying a different provider with the same audio won't help."""
        key = (s.get(cfg["key_setting"]) or "").strip()
        model_setting = cfg.get("model_setting")
        model = ((s.get(model_setting) if model_setting else "") or "").strip()
        if not model:
            model = cfg["default_model"]
        lang = (s.get("stt_language") or "").strip()

        # Only send fields THIS provider tolerates.  SenseVoice rejects the
        # Whisper extras; Groq accepts them.  `file` + `model` always go.
        allowed = set(cfg.get("extra_fields", []))
        fields = {"model": model}
        if "response_format" in allowed:
            fields["response_format"] = "json"
        if "temperature" in allowed:
            fields["temperature"] = "0"
        if "language" in allowed and lang:
            fields["language"] = lang

        url = _stt_url(cfg, s)
        _log(f"transcribe via {provider_id} ({model}) -> {url} "
             f"[fields: {', '.join(sorted(fields))}]")
        try:
            raw = _post_multipart(
                url,
                {"Authorization": f"Bearer {key}"},
                fields, "file", "audio.wav", audio, "audio/wav",
                timeout=90)
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")[:300]
            except Exception:
                pass
            _log(f"transcribe HTTP {e.code} ({provider_id}): {body}")
            hint = ""
            retryable = e.code in (401, 403, 404) or e.code >= 500
            if e.code in (401, 403):
                hint = f" — check your {provider_id} key in Settings"
            elif e.code == 400:
                hint = f" — {provider_id} rejected the request: {body[:120]}"
            return "", f"transcription failed (HTTP {e.code}){hint}", retryable
        except Exception as e:
            _log(f"transcribe error ({provider_id}): {e}")
            # network/timeout/connection — worth trying another provider
            return "", f"transcription failed: {e}", True
        try:
            data = json.loads(raw)
            text = (data.get("text") or "").strip()
            # SenseVoice sometimes wraps output in <|tags|>; strip them.
            text = re.sub(r"<\|[^|]*\|>", "", text).strip()
            return text, None, False
        except Exception as e:
            _log(f"transcribe parse error: {e}; raw={raw[:200]}")
            return "", "could not parse transcription response", False

    @staticmethod
    def _safe_remove(path: str) -> None:
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except Exception:
            pass


def _post_multipart(url: str, headers: Dict[str, str],
                    fields: Dict[str, str], file_field: str,
                    filename: str, file_bytes: bytes,
                    content_type: str = "application/octet-stream",
                    timeout: int = 60) -> str:
    """Minimal multipart/form-data POST built on urllib (no requests dep)."""
    boundary = "----kalivoice" + os.urandom(16).hex()
    crlf = b"\r\n"
    body = BytesIO()
    for k, v in fields.items():
        body.write(b"--" + boundary.encode() + crlf)
        body.write(('Content-Disposition: form-data; name="%s"' % k).encode()
                   + crlf + crlf)
        body.write(str(v).encode() + crlf)
    body.write(b"--" + boundary.encode() + crlf)
    body.write(('Content-Disposition: form-data; name="%s"; filename="%s"'
                % (file_field, filename)).encode() + crlf)
    body.write(("Content-Type: %s" % content_type).encode() + crlf + crlf)
    body.write(file_bytes + crlf)
    body.write(b"--" + boundary.encode() + b"--" + crlf)
    data = body.getvalue()

    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type",
                   "multipart/form-data; boundary=%s" % boundary)
    for k, v in headers.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


# ═════════════════════════════════════════════════════════════════════
# TEXT TO SPEECH — queue worker, Piper preferred, espeak fallback
# ═════════════════════════════════════════════════════════════════════

_PIPER_VOICE_DIRS = [
    "~/.local/share/kali/voices",
    "~/.local/share/piper-voices",
    "~/.local/share/piper",
    "~/.cache/piper",
]
_WAV_PLAYERS = [
    ["paplay"],
    ["aplay", "-q"],
    ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"],
    ["play", "-q"],
]


class TextToSpeech:
    """A background worker that speaks queued text.  speak() enqueues,
    stop() flushes + interrupts.  Engine is chosen once and can be
    re-chosen with reconfigure() when settings change."""

    def __init__(self, get_settings: Callable[[], Dict]) -> None:
        self.get_settings = get_settings
        self._q: "queue.Queue[Tuple[int,str]]" = queue.Queue()
        self._gen = 0
        self._lock = threading.Lock()
        self._cur: Optional[subprocess.Popen] = None
        # Pause/resume: worker waits on _resume between sentences; the
        # currently-playing process is frozen with SIGSTOP and thawed
        # with SIGCONT.  _active tracks whether we're mid-utterance so we
        # can fire an "idle" callback exactly once when the queue drains.
        self._resume = threading.Event()
        self._resume.set()
        self._active = False
        self._on_state: Optional[Callable[[str], None]] = None

        self._engine: Optional[str] = None   # "piper" | "espeak" | None
        self._espeak: Optional[str] = None
        self._piper_cmd: Optional[List[str]] = None
        self._piper_model: Optional[str] = None
        self._piper_modelflag = "--model"
        self._piper_outflag = "--output_file"
        self._piper_silence_flag: Optional[str] = None  # set by probe if build
                                                         # accepts --sentence_silence
        self._piper_probed = False           # probe lazily on first speak
        self._player: Optional[List[str]] = None

        self._detect()

        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    # ── capability detection ──
    def _detect(self) -> None:
        s = self.get_settings()
        pref = (s.get("tts_engine") or "auto").strip().lower()

        self._espeak = shutil.which("espeak-ng") or shutil.which("espeak")
        self._player = self._find_player()

        piper_ok = False
        if pref in ("auto", "piper"):
            cmd = self._find_piper_cmd()
            model = _find_piper_model(s)
            if cmd and model and self._player:
                # Don't probe here — running piper synchronously could
                # stall the UI thread at startup / on settings change.
                # We probe lazily on the first actual speak, in the worker
                # thread, and fall back to espeak if it turns out broken.
                self._piper_cmd = cmd
                self._piper_model = model
                self._piper_probed = False
                piper_ok = True

        if pref == "piper" and piper_ok:
            self._engine = "piper"
        elif pref == "espeak" and self._espeak:
            self._engine = "espeak"
        elif pref == "auto" and piper_ok:
            self._engine = "piper"
        elif pref == "auto" and self._espeak:
            self._engine = "espeak"
        elif self._espeak:               # requested piper but only espeak exists
            self._engine = "espeak"
        else:
            self._engine = None
        _log(f"tts engine = {self._engine} "
             f"(piper={'y' if piper_ok else 'n'}, "
             f"espeak={'y' if self._espeak else 'n'}, "
             f"player={self._player[0] if self._player else 'none'})")

    def reconfigure(self) -> None:
        """Re-run detection (e.g. after the operator changes the engine or
        voice in Settings).  Stops any in-flight speech first."""
        self.stop()
        with self._lock:
            self._piper_cmd = None
            self._piper_model = None
        self._piper_probed = False
        self._detect()

    @staticmethod
    def _find_player() -> Optional[List[str]]:
        for p in _WAV_PLAYERS:
            if shutil.which(p[0]):
                return p
        return None

    @staticmethod
    def _find_piper_cmd() -> Optional[List[str]]:
        if shutil.which("piper"):
            return ["piper"]
        try:
            r = subprocess.run([sys.executable, "-m", "piper", "--help"],
                               capture_output=True, timeout=12)
            blob = (r.stdout or b"") + (r.stderr or b"")
            if r.returncode == 0 or b"piper" in blob.lower():
                return [sys.executable, "-m", "piper"]
        except Exception:
            pass
        return None

    def _probe_piper(self, cmd: List[str], model: str) -> bool:
        """Synthesize one tiny clip to learn which flag spelling this
        build wants, and confirm it actually produces audio."""
        variants = [("--model", "--output_file"),
                    ("-m", "-f"),
                    ("--model", "--output-file")]
        for mflag, oflag in variants:
            fd, wav = tempfile.mkstemp(prefix="kali_tts_probe_", suffix=".wav")
            os.close(fd)
            try:
                full = list(cmd) + [mflag, model, oflag, wav]
                p = subprocess.run(full, input=b"test",
                                   stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, timeout=40)
                ok = (os.path.exists(wav) and os.path.getsize(wav) > 44)
                if ok:
                    self._piper_modelflag = mflag
                    self._piper_outflag = oflag
                    self._piper_silence_flag = self._probe_silence_flag(
                        cmd, model, mflag, oflag)
                    return True
                _ = p
            except Exception as e:
                _log(f"piper probe ({mflag}/{oflag}) failed: {e}")
            finally:
                try:
                    os.remove(wav)
                except Exception:
                    pass
        return False

    def _probe_silence_flag(self, cmd: List[str], model: str,
                            mflag: str, oflag: str) -> Optional[str]:
        """Find which --sentence_silence spelling this piper build accepts (so
        we can set the inter-sentence pause to ~0 and kill the long stop at
        every period).  Returns the working flag, or None if unsupported."""
        for flag in ("--sentence_silence", "--sentence-silence"):
            fd, wav = tempfile.mkstemp(prefix="kali_tts_sp_", suffix=".wav")
            os.close(fd)
            try:
                full = (list(cmd) + [mflag, model, oflag, wav, flag, "0.0"])
                subprocess.run(full, input=b"a. b.",
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=40)
                if os.path.exists(wav) and os.path.getsize(wav) > 44:
                    return flag
            except Exception:
                pass
            finally:
                try:
                    os.remove(wav)
                except Exception:
                    pass
        return None

    # ── status ──
    def available(self) -> bool:
        return self._engine is not None

    def engine_name(self) -> str:
        if self._engine == "piper" and self._piper_model:
            return f"piper ({os.path.basename(self._piper_model)})"
        return self._engine or "none"

    def diagnostics(self) -> Dict[str, object]:
        return {
            "engine": self._engine,
            "espeak": bool(self._espeak),
            "piper": bool(self._piper_cmd and self._piper_model),
            "piper_model": self._piper_model or "",
            "player": self._player[0] if self._player else "",
        }

    # ── queue API ──
    def speak(self, text: str) -> None:
        if not self._engine:
            return
        text = (text or "").strip()
        if not text:
            return
        self._q.put((self._gen, text))

    def speak_all(self, text: str) -> None:
        """Clean a whole message, split it, merge into a few larger utterances
        (so there's no gap at every period), and queue them."""
        sentences = split_sentences(clean_for_speech(text))
        for s in merge_for_speech(sentences):
            self.speak(s)

    def is_speaking(self) -> bool:
        with self._lock:
            return self._cur is not None or not self._q.empty()

    def is_paused(self) -> bool:
        return not self._resume.is_set()

    def set_state_callback(self, fn: Optional[Callable[[str], None]]) -> None:
        """fn(state) is called from the worker thread with one of
        'speaking' | 'paused' | 'idle'.  Marshal to the UI thread yourself."""
        self._on_state = fn

    def _notify(self, state: str) -> None:
        cb = self._on_state
        if cb is not None:
            try:
                cb(state)
            except Exception:
                pass

    def _signal_cur(self, sig: int) -> None:
        with self._lock:
            p = self._cur
        if p is not None and p.poll() is None:
            try:
                p.send_signal(sig)
            except Exception:
                pass

    def pause(self) -> None:
        if not self._engine:
            return
        if not self._active and self._q.empty():
            return
        self._resume.clear()
        self._signal_cur(signal.SIGSTOP)
        self._notify("paused")

    def resume(self) -> None:
        if not self._engine:
            return
        self._signal_cur(signal.SIGCONT)
        self._resume.set()
        self._notify("speaking")

    def stop(self) -> None:
        self._gen += 1
        try:
            while True:
                self._q.get_nowait()
        except queue.Empty:
            pass
        # Make sure a paused process can actually be killed, and that the
        # worker isn't left blocked on a cleared resume gate.
        self._resume.set()
        with self._lock:
            p = self._cur
            self._cur = None
        if p and p.poll() is None:
            try:
                p.send_signal(signal.SIGCONT)
            except Exception:
                pass
            try:
                p.terminate()
            except Exception:
                pass
        self._active = False
        self._notify("idle")

    # ── worker ──
    def _run(self) -> None:
        while True:
            try:
                gen, text = self._q.get(timeout=0.2)
            except queue.Empty:
                # Nothing queued.  If we just finished talking and aren't
                # paused, announce idle exactly once.
                if (self._active and self._resume.is_set()):
                    with self._lock:
                        busy = self._cur is not None
                    if not busy:
                        self._active = False
                        self._notify("idle")
                continue
            if gen != self._gen:
                continue
            # Block here while paused (without burning the item).
            self._resume.wait()
            if gen != self._gen:
                continue
            if not self._active:
                self._active = True
                self._notify("speaking")
            try:
                if self._engine == "piper":
                    self._speak_piper(gen, text)
                elif self._engine == "espeak":
                    self._speak_espeak(gen, text)
            except Exception as e:
                _log(f"speak error: {e}")

    def _register(self, p: subprocess.Popen) -> None:
        with self._lock:
            self._cur = p

    def _clear(self, p: subprocess.Popen) -> None:
        with self._lock:
            if self._cur is p:
                self._cur = None

    def _rate(self) -> float:
        try:
            r = float(self.get_settings().get("tts_rate", 1.0) or 1.0)
        except (TypeError, ValueError):
            r = 1.0
        return max(0.5, min(2.0, r))

    def _sentence_pause(self) -> float:
        """Seconds of silence Piper inserts between sentences.  Default 0.0 —
        no long stop after periods.  Tunable via tts_sentence_pause."""
        try:
            v = float(self.get_settings().get("tts_sentence_pause", 0.0) or 0.0)
        except (TypeError, ValueError):
            v = 0.0
        return max(0.0, min(1.0, v))

    def _speak_piper(self, gen: int, text: str) -> None:
        if gen != self._gen:
            return
        # First real use: confirm piper actually produces audio and learn
        # its flag spelling.  If it's broken, fall back to espeak for good.
        if not self._piper_probed:
            ok = self._probe_piper(self._piper_cmd, self._piper_model)
            self._piper_probed = True
            if not ok:
                _log("piper unusable at first speak; falling back to espeak")
                self._engine = "espeak" if self._espeak else None
                if self._engine == "espeak":
                    self._speak_espeak(gen, text)
                return
        length_scale = max(0.5, min(2.0, 1.0 / self._rate()))
        text = re.sub(r"\s+", " ", text).strip()   # no stray newline pauses
        fd, wav = tempfile.mkstemp(prefix="kali_tts_", suffix=".wav")
        os.close(fd)
        try:
            cmd = list(self._piper_cmd) + [
                self._piper_modelflag, self._piper_model,
                self._piper_outflag, wav]
            if abs(length_scale - 1.0) > 0.01:
                cmd += ["--length_scale", str(round(length_scale, 2))]
            if self._piper_silence_flag:
                # ~0 silence between sentences = no long stop after periods.
                pause = self._sentence_pause()
                cmd += [self._piper_silence_flag, str(pause)]
            p = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
            self._register(p)
            try:
                p.communicate(input=text.encode("utf-8"), timeout=60)
            finally:
                self._clear(p)
            if gen != self._gen:
                return
            if os.path.exists(wav) and os.path.getsize(wav) > 44:
                self._play_wav(gen, wav)
        finally:
            try:
                os.remove(wav)
            except Exception:
                pass

    def _play_wav(self, gen: int, wav: str) -> None:
        if gen != self._gen or not self._player:
            return
        p = subprocess.Popen(list(self._player) + [wav],
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        self._register(p)
        try:
            p.wait()
        finally:
            self._clear(p)

    def _speak_espeak(self, gen: int, text: str) -> None:
        if gen != self._gen:
            return
        s = self.get_settings()
        wpm = int(max(80, min(400, 175 * self._rate())))
        voice = (s.get("tts_voice_espeak") or "").strip()
        text = re.sub(r"\s+", " ", text).strip()   # no stray newline pauses
        # -g 0 = no extra word gap; keeps espeak from dragging between words.
        cmd = [self._espeak, "-s", str(wpm), "-g", "0"]
        if voice:
            cmd += ["-v", voice]
        cmd += ["--", text]
        p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        self._register(p)
        try:
            p.wait()
        finally:
            self._clear(p)


def _find_piper_model(settings: Dict) -> Optional[str]:
    """Resolve a Piper voice .onnx: explicit setting first, then the
    conventional cache/share dirs."""
    explicit = (settings.get("tts_voice") or "").strip()
    if explicit:
        cand = os.path.expanduser(explicit)
        if os.path.isfile(cand) and cand.endswith(".onnx"):
            return cand
        # A directory was given — take the first model in it.
        if os.path.isdir(cand):
            for f in sorted(os.listdir(cand)):
                if f.endswith(".onnx"):
                    return os.path.join(cand, f)
    for d in _PIPER_VOICE_DIRS:
        dd = os.path.expanduser(d)
        if os.path.isdir(dd):
            for root, _dirs, files in os.walk(dd):
                for f in sorted(files):
                    if f.endswith(".onnx"):
                        return os.path.join(root, f)
    return None


# ── tiny self-test when run directly ─────────────────────────────────
if __name__ == "__main__":
    sample = ("Here's the plan.\n\n"
              "First, **scan** the box:\n"
              "```bash\nnmap -sV 10.0.0.1\n```\n"
              "Then check the results. See https://example.com for refs. "
              "Dr. Smith said it's fine, e.g. ports 22 and 80.")
    print("=== clean_for_speech ===")
    print(clean_for_speech(sample))
    print("\n=== split_sentences ===")
    for s in split_sentences(clean_for_speech(sample)):
        print("  •", s)
    print("\n=== streamer ===")
    st = SpeechStreamer()
    acc = ""
    emitted = []
    for tok in re.findall(r"\S+\s*|\n", sample):
        acc += tok
        emitted += st.feed(acc)
    emitted += st.flush(acc)
    for s in emitted:
        print("  >", s)
