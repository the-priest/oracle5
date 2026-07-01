#!/usr/bin/env bash
#
# install.sh — Kali assistant: zero-to-running installer
#
# What it does, in order:
#   1. checks Python 3.10+
#   2. installs GTK4 + libadwaita bindings (apt / pacman / dnf)
#   3. installs the Groq Python library (cloud backend, primary)
#   7. installs the three .py files + dragon icon + launcher + desktop entry + systemd unit
#   8. asks for a Groq API key (optional — skip & set it later in Settings)
#   9. writes settings.json so the app opens straight into a working chat
#   10. (if present) migrates oracle/* chats and settings to kali/*
#
# After this: click "Kali" in your app grid.  That's it.
#
# Estimated time on a OnePlus 6 over WiFi:
#   - first install:  ~1-3 min
#   - subsequent re-runs:  ~5 seconds (skips everything already done)
#
# Usage:
#   ./install.sh                     # install or update
#   ./install.sh --update            # explicit update (same code path)
#   ./install.sh --uninstall         # remove Kali (chat history kept)
#   ./install.sh --remove-oracle     # remove the old Oracle install
#   ./install.sh --no-systemd        # don't install the systemd unit
#   ./install.sh --no-helpers        # skip optional desktop helpers
#   ./install.sh --no-browser        # skip Playwright/Chromium
#   ./install.sh --no-voice          # skip voice setup (espeak/piper/mic)
#   ./install.sh --no-groq           # don't install the groq library / skip key prompt
#   ./install.sh --no-prompt         # skip ALL interactive prompts
#
# Env overrides:
#   KALI_REPO=the-priest/oracle5  KALI_BRANCH=main  ./install.sh
#   GROQ_API_KEY=gsk_...        ./install.sh    # preset key, no prompt
#
# One-liner install from GitHub:
#   curl -fsSL https://raw.githubusercontent.com/the-priest/oracle5/main/install.sh | bash
#

set -eo pipefail   # NOTE: no -u — curl|bash leaves BASH_SOURCE empty

# ── flags ─────────────────────────────────────────────────────────

ACTION="install"
SKIP_SYSTEMD=0
SKIP_HELPERS=0
SKIP_BROWSER=0
SKIP_GROQ=0
SKIP_VOICE=0
NO_PROMPT=0
for arg in "$@"; do
  case "$arg" in
    --uninstall)         ACTION="uninstall" ;;
    --update)            ACTION="install" ;;
    --remove-oracle)     ACTION="remove-oracle" ;;
    --no-systemd)        SKIP_SYSTEMD=1 ;;
    --no-helpers)        SKIP_HELPERS=1 ;;
    --no-browser)        SKIP_BROWSER=1 ;;
    --no-groq)           SKIP_GROQ=1 ;;
    --no-voice)          SKIP_VOICE=1 ;;
    --no-prompt)         NO_PROMPT=1 ;;
    -h|--help)
      sed -n '2,/^$/p' "$0" | sed 's/^# \?//'
      exit 0 ;;
  esac
done

# ── pretty printing ───────────────────────────────────────────────

if [ -t 1 ]; then
  # ANSI-C quoting ($'...') so these hold REAL escape bytes, not the literal
  # text \033.  Literal-text colours only render via printf (which interprets
  # backslash escapes); the banner heredoc and the summary `echo` lines print
  # them verbatim, which is why they used to show "\033[35m" on screen.
  Y=$'\033[33m'; G=$'\033[32m'; R=$'\033[31m'; B=$'\033[36m'; M=$'\033[35m'; D=$'\033[90m'; X=$'\033[0m'
else
  Y=""; G=""; R=""; B=""; M=""; D=""; X=""
fi
say()   { printf "${Y}[*]${X} %s\n" "$*"; }
ok()    { printf "${G}[+]${X} %s\n" "$*"; }
warn()  { printf "${Y}[!]${X} %s\n" "$*"; }
err()   { printf "${R}[!]${X} %s\n" "$*" >&2; }
fatal() { err "$*"; exit 1; }
step()  { printf "\n${M}== %s ==${X}\n" "$*"; }

T_START=$(date +%s)
elapsed() { echo $(( $(date +%s) - T_START )); }

# ── paths & config ────────────────────────────────────────────────

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]:-/dev/null}" )" 2>/dev/null && pwd || echo "" )"
INSTALL_DIR="${HOME}/.local/share/kali"
DATA_DIR="${HOME}/.local/share/kali"
CONFIG_DIR="${HOME}/.config/kali"
BIN_DIR="${HOME}/.local/bin"
DESKTOP_DIR="${HOME}/.local/share/applications"
ICON_DIR="${HOME}/.local/share/icons/hicolor/scalable/apps"
SYSTEMD_DIR="${HOME}/.config/systemd/user"
BACKUP_DIR="${INSTALL_DIR}/backups"

# Old oracle paths (for migration)
OLD_DATA_DIR="${HOME}/.local/share/oracle"
OLD_CONFIG_DIR="${HOME}/.config/oracle"

REQUIRED_FILES=(kali.py kali_core.py kali_safety.py kali_ledger.py kali_persona.py kali_voice.py)
OPTIONAL_FILES=(org.thepriest.kali.svg kali-dragon.svg kali-watermark.png kali-cross.svg kali-avatar.png)
# kali_ext sidecar modules — fetched in remote (curl|bash) mode so phones
# and fresh boxes get the full toolset (headroom / verify / pentest plus the
# memory/skills/foresight extensions), not just the core four files.
EXT_FILES=(__init__.py bench.py codescan.py engage.py extman.py foresight.py headroom.py memory.py mcp.py \
           pentest.py sandbox.py skills.py verify.py worker.py)
GITHUB_REPO="${KALI_REPO:-the-priest/oracle5}"
GITHUB_BRANCH="${KALI_BRANCH:-main}"

# How to re-invoke this installer in the hints we print.  Under `curl|bash`
# $0 is just "bash" (the script came down a pipe, it's not a file on disk),
# so fall back to the canonical one-liner so "Uninstall: …" is copy-pasteable.
_self_src="${BASH_SOURCE[0]:-$0}"
if [ -f "${_self_src}" ] && [ "${_self_src##*/}" != "bash" ] && [ "${_self_src##*/}" != "sh" ]; then
  SELF_CMD="${_self_src}"
else
  SELF_CMD="curl -fsSL https://raw.githubusercontent.com/${GITHUB_REPO}/${GITHUB_BRANCH}/install.sh | bash -s --"
fi

# The desktop entry, the icon theme name, and the Wayland app-id / X11
# WM_CLASS must all share ONE name for the window/taskbar icon to resolve
# reliably — especially on KDE Plasma, which matches a running window to
# its .desktop file by app-id.  GTK4 has no per-window icon API; it loads
# the window icon from the icon theme using this exact name.
APP_ID="org.thepriest.kali"

# ── uninstall path ────────────────────────────────────────────────

uninstall() {
  step "uninstalling Kali"
  systemctl --user stop    kali-ollama.service 2>/dev/null || true
  systemctl --user disable kali-ollama.service 2>/dev/null || true
  rm -f  "${SYSTEMD_DIR}/kali-ollama.service"
  systemctl --user daemon-reload 2>/dev/null || true
  rm -f  "${BIN_DIR}/kali"
  rm -f  "${DESKTOP_DIR}/${APP_ID}.desktop"
  rm -f  "${DESKTOP_DIR}/kali.desktop"          # legacy name
  rm -f  "${ICON_DIR}/${APP_ID}.svg"
  rm -f  "${ICON_DIR}/kali-dragon.svg"          # legacy name
  update-desktop-database "${DESKTOP_DIR}" 2>/dev/null || true
  rm -f "${INSTALL_DIR}"/kali*.py 2>/dev/null || true
  rm -f "${INSTALL_DIR}"/kali-dragon.svg 2>/dev/null || true
  rm -f "${INSTALL_DIR}/${APP_ID}.svg" 2>/dev/null || true
  warn "chat history and settings were NOT removed."
  echo "      To wipe: rm -rf ${DATA_DIR} ${CONFIG_DIR}"
  ok "Kali uninstalled."
  exit 0
}

remove_oracle() {
  step "removing the old Oracle installation"
  systemctl --user stop    oracle-ollama.service 2>/dev/null || true
  systemctl --user disable oracle-ollama.service 2>/dev/null || true
  rm -f  "${SYSTEMD_DIR}/oracle-ollama.service"
  systemctl --user daemon-reload 2>/dev/null || true
  rm -f  "${BIN_DIR}/oracle"
  rm -f  "${DESKTOP_DIR}/oracle.desktop"
  update-desktop-database "${DESKTOP_DIR}" 2>/dev/null || true
  # Migrate any chat history before removing the old data dir, in case
  # Kali doesn't have its own DB yet.
  if [ -f "${OLD_DATA_DIR}/chats.db" ] && [ ! -f "${DATA_DIR}/chats.db" ]; then
    mkdir -p "${DATA_DIR}"
    cp "${OLD_DATA_DIR}/chats.db" "${DATA_DIR}/chats.db"
    ok "migrated chats.db → ${DATA_DIR}"
  fi
  rm -rf "${OLD_DATA_DIR}"
  rm -rf "${OLD_CONFIG_DIR}"
  ok "Oracle fully removed.  (Kali install untouched.)"
  exit 0
}

[ "${ACTION}" = "uninstall" ]     && uninstall
[ "${ACTION}" = "remove-oracle" ] && remove_oracle

# ── intro ─────────────────────────────────────────────────────────

cat <<EOF

${M}╔═══════════════════════════════════════╗${X}
${M}║${X}  ${B}Kali${X} — personal, loyal AI assistant  ${M}║${X}
${M}╚═══════════════════════════════════════╝${X}

  repo:            ${GITHUB_REPO}@${GITHUB_BRANCH}
  install dir:     ${INSTALL_DIR}

  Cloud-only: Groq, SiliconFlow, Novita, GitHub Models, or Google AI
  Studio. Pick a provider and paste its API key in Settings.
EOF

# Detect a stale oracle install and warn (don't auto-remove — let the user decide)
if [ -f "${DESKTOP_DIR}/oracle.desktop" ] || [ -f "${BIN_DIR}/oracle" ] \
   || [ -f "${SYSTEMD_DIR}/oracle-ollama.service" ]; then
  echo
  warn "previous Oracle installation detected"
  echo "      To remove it:  ${SELF_CMD} --remove-oracle"
  echo "      (your chat history will be preserved)"
  echo
fi

# ── 1. Python ─────────────────────────────────────────────────────

step "Python"
command -v python3 >/dev/null || fatal "python3 not installed"
PYV=$(python3 -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')
PYV_MAJ=$(echo "$PYV" | cut -d. -f1)
PYV_MIN=$(echo "$PYV" | cut -d. -f2)
if [ "$PYV_MAJ" -lt 3 ] || { [ "$PYV_MAJ" -eq 3 ] && [ "$PYV_MIN" -lt 10 ]; }; then
  fatal "python ${PYV} too old (need 3.10+)"
fi
ok "python ${PYV}"

# ── 2. GTK4 + libadwaita ──────────────────────────────────────────

step "GTK4 + libadwaita"
if python3 -c "
import gi
gi.require_version('Gtk','4.0')
gi.require_version('Adw','1')
from gi.repository import Gtk, Adw
" 2>/dev/null; then
  ok "GTK4 + libadwaita present"
else
  warn "missing — installing (this may take ~30s on slow mirrors)"
  if command -v apt-get >/dev/null; then
    sudo apt-get update
    sudo apt-get install -y python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 \
      libgtk-4-1 libadwaita-1-0 || fatal "apt install failed"
  elif command -v pacman >/dev/null; then
    sudo pacman -Sy --needed --noconfirm python-gobject gtk4 libadwaita
  elif command -v dnf >/dev/null; then
    sudo dnf install -y python3-gobject gtk4 libadwaita
  else
    fatal "unknown package manager — install python3-gi, GTK 4, libadwaita manually"
  fi
  python3 -c "
import gi
gi.require_version('Gtk','4.0')
gi.require_version('Adw','1')
from gi.repository import Gtk, Adw
" || fatal "GTK4/Adw still not working after install"
  ok "GTK4 + libadwaita installed"
fi

# ── 3. Groq library ───────────────────────────────────────────────

if [ $SKIP_GROQ -eq 0 ]; then
  step "Groq Python library"
  if python3 -c "import groq" 2>/dev/null; then
    ok "groq library already present"
  else
    say "installing groq (~few MB) via pip"
    # `python3 -m pip` works whether the user has `pip` or `pip3` on PATH
    # (or neither — they may need apt to install pip first).
    if python3 -m pip install --user --quiet groq 2>/dev/null; then
      ok "groq installed (pip --user)"
    elif python3 -m pip install --user --break-system-packages --quiet groq 2>/dev/null; then
      ok "groq installed (pip --user --break-system-packages)"
    elif command -v pipx >/dev/null && pipx install groq 2>/dev/null; then
      ok "groq installed (pipx)"
    elif command -v apt-get >/dev/null && sudo apt-get install -y python3-pip 2>/dev/null \
         && python3 -m pip install --user --break-system-packages --quiet groq 2>/dev/null; then
      ok "groq installed (after pip install)"
    else
      warn "could not auto-install groq library — add a SiliconFlow,"
      warn "Novita, GitHub, or Google key in Settings instead, or fix with:"
      warn "   python3 -m pip install --user --break-system-packages groq"
    fi
  fi
else
  warn "skipping groq library (--no-groq)"
fi

# ── 3b. Headroom (optional context compression) ──────────────────
#
# Headroom crushes bulky tool output before it reaches the model, saving
# context and tokens on long sessions.  Fully optional — Kali ships a
# built-in pure-Python fallback compressor, so if this won't install she
# still compresses, just a little less aggressively.

step "Headroom context compression (optional)"
if python3 -c "import headroom" 2>/dev/null; then
  ok "headroom already present"
elif python3 -m pip install --user --quiet headroom-ai 2>/dev/null; then
  ok "headroom installed (pip --user)"
elif python3 -m pip install --user --break-system-packages --quiet headroom-ai 2>/dev/null; then
  ok "headroom installed (pip --user --break-system-packages)"
else
  warn "headroom-ai not installed — Kali falls back to her built-in"
  warn "compressor (still works).  To add it later:"
  warn "   python3 -m pip install --user --break-system-packages headroom-ai"
fi

# ── 4. Optional desktop-control helpers ──────────────────────────
#
# Kali's device-control tools (launch apps, type/click, screenshots,
# screen OCR, browser automation) lean on small system helpers.  They
# all degrade gracefully if absent — each tool reports what's missing —
# but installing them up front means "do anything I ask" works on day
# one.  This step is best-effort: failures here never abort the install.

if [ $SKIP_HELPERS -eq 0 ] && command -v apt-get >/dev/null; then
  step "desktop-control helpers (optional)"
  # Pick input/screenshot helpers by session type.
  SESS="${XDG_SESSION_TYPE:-}"
  DE="${XDG_CURRENT_DESKTOP:-}"
  # libnotify-bin = notify-send (desktop notifications, all DEs)
  COMMON="tesseract-ocr playerctl libnotify-bin"
  if [ "$SESS" = "wayland" ] || [ -n "${WAYLAND_DISPLAY:-}" ]; then
    HELPERS="$COMMON wtype wlrctl grim slurp ydotool"
    say "Wayland session — installing: $HELPERS"
  else
    HELPERS="$COMMON xdotool wmctrl scrot"
    say "X11 session — installing: $HELPERS"
  fi
  # On KDE, add Spectacle (screenshots) — it handles compositor quirks.
  case "$DE" in
    *KDE*|*kde*|*plasma*|*Plasma*)
      HELPERS="$HELPERS kde-spectacle"
      say "KDE Plasma detected — adding Spectacle" ;;
  esac
  # shellcheck disable=SC2086
  if sudo apt-get install -y $HELPERS 2>/dev/null; then
    ok "desktop helpers installed"
  else
    warn "some helpers unavailable on this mirror — Kali still runs;"
    warn "missing tools just report themselves when used"
  fi
  # Browser automation (optional, larger): Playwright + Chromium.
  if [ $SKIP_BROWSER -eq 0 ]; then
    say "browser automation (Playwright + Chromium, ~150MB) — optional"
    if python3 -m pip install --user --break-system-packages --quiet playwright 2>/dev/null \
       && python3 -m playwright install chromium 2>/dev/null; then
      ok "Playwright + Chromium installed"
    else
      warn "Playwright not installed — the browser tool will tell you how"
      warn "to enable it later:  pip install playwright && playwright install chromium"
    fi

    # Brave: Kali's browser tool drives Brave when present (its Shields block
    # ads/trackers, so pages load without consent walls).  Opt in with
    # WITH_BRAVE=1; otherwise we just detect an existing install.
    if command -v brave-browser >/dev/null 2>&1 || [ -x /usr/bin/brave-browser ] \
       || [ -x /opt/brave.com/brave/brave-browser ]; then
      ok "Brave detected — the browser tool will use it"
    elif [ "${WITH_BRAVE:-0}" = "1" ]; then
      say "installing Brave (WITH_BRAVE=1) …"
      if curl -fsS https://dl.brave.com/install.sh | sh >/dev/null 2>&1; then
        ok "Brave installed — browsing will use it (ad/tracker Shields on)"
      else
        warn "Brave install failed — browsing falls back to bundled Chromium"
      fi
    else
      say "tip: for ad/tracker-free browsing, install Brave (re-run with WITH_BRAVE=1)"
    fi
  fi
else
  [ $SKIP_HELPERS -eq 1 ] && warn "skipping desktop helpers (--no-helpers)"
fi

# ── 6c. UI fonts (the theme is literally built on these) ──────────
# The GTK theme is designed around Inter (UI text) and JetBrains Mono
# (branding, headers, code blocks, labels).  Without them installed, GTK
# silently falls back to generic system fonts and the whole look flattens
# out — this is the single biggest reason the UI can read as "unpolished"
# on a fresh box even though the stylesheet is fully tuned.  Best-effort
# and isolated: every branch ends in ok/warn, so a package name that's
# missing on one mirror can never abort the install.
if [ $SKIP_HELPERS -eq 0 ]; then
  step "UI fonts (Inter + JetBrains Mono)"
  if command -v apt-get >/dev/null; then
    # Install each independently so a missing one doesn't drop the others.
    _fok=0
    for _fp in fonts-inter fonts-jetbrains-mono fonts-firacode; do
      sudo apt-get install -y "$_fp" 2>/dev/null && _fok=$((_fok + 1)) || true
    done
    [ $_fok -gt 0 ] \
      && ok "UI fonts installed (${_fok}/3 — Inter / JetBrains Mono / Fira Code)" \
      || warn "font packages unavailable on this mirror — UI falls back to system fonts"
  elif command -v pacman >/dev/null; then
    sudo pacman -Sy --needed --noconfirm inter-font ttf-jetbrains-mono ttf-fira-code 2>/dev/null \
      && ok "UI fonts installed" \
      || warn "font packages unavailable — UI falls back to system fonts"
  elif command -v dnf >/dev/null; then
    sudo dnf install -y rsms-inter-fonts jetbrains-mono-fonts fira-code-fonts 2>/dev/null \
      && ok "UI fonts installed" \
      || warn "font packages unavailable — UI falls back to system fonts"
  fi
  # JetBrains Mono is the branding/header/code font, but it isn't reliably
  # packaged on Kali/Debian rolling (the apt package above is often absent —
  # exactly what happened on this box).  If it still isn't present, fetch the
  # official release straight into the user font dir: works on any distro,
  # needs no root.  Best-effort; every branch ends in ok/warn.
  if fc-list 2>/dev/null | grep -qi "JetBrains Mono"; then
    ok "JetBrains Mono present"
  else
    _fontdir="${HOME}/.local/share/fonts"
    mkdir -p "$_fontdir" 2>/dev/null || true
    _jbmver="2.304"
    _jbmurl="https://github.com/JetBrains/JetBrainsMono/releases/download/v${_jbmver}/JetBrainsMono-${_jbmver}.zip"
    if command -v curl >/dev/null;  then _dl=(curl -fsSL -o)
    elif command -v wget >/dev/null; then _dl=(wget -qO)
    else _dl=(); fi
    if [ ${#_dl[@]} -gt 0 ] && command -v unzip >/dev/null; then
      _jbmzip="$(mktemp --suffix=.zip 2>/dev/null || echo /tmp/jbm.zip)"
      if "${_dl[@]}" "$_jbmzip" "$_jbmurl" 2>/dev/null \
         && unzip -o -j "$_jbmzip" "fonts/ttf/*.ttf" -d "$_fontdir" >/dev/null 2>&1; then
        ok "JetBrains Mono installed from official release → $_fontdir"
      else
        warn "couldn't fetch JetBrains Mono — UI headers use another mono font"
      fi
      rm -f "$_jbmzip" 2>/dev/null || true
    else
      warn "need curl/wget + unzip to fetch JetBrains Mono — skipped"
    fi
  fi
  # Refresh the font cache so GTK sees them on first launch.
  command -v fc-cache >/dev/null 2>&1 && fc-cache -f >/dev/null 2>&1 || true
fi

# ── 6b. Voice (speech in / speech out) ────────────────────────────
# espeak-ng  = guaranteed TTS fallback (always works, robotic)
# recorder/player = parecord/paplay (pulseaudio-utils) or arecord/aplay
# Piper      = local NEURAL voice — sounds pleasant, the real default
# voice model = a natural British voice (~63MB) for Piper
# All best-effort: nothing here aborts the install.  If Piper or the
# model don't land, Kali falls back to espeak; if no recorder lands,
# voice input just stays hidden and you type as normal.
if [ $SKIP_VOICE -eq 0 ]; then
  step "voice (speech in / speech out)"

  if command -v apt-get >/dev/null; then
    sudo apt-get install -y espeak-ng pulseaudio-utils alsa-utils 2>/dev/null \
      && ok "voice packages installed (espeak-ng, recorder, player)" \
      || warn "some voice packages unavailable on this mirror"
  elif command -v pacman >/dev/null; then
    sudo pacman -Sy --needed --noconfirm espeak-ng libpulse alsa-utils 2>/dev/null \
      && ok "voice packages installed" || warn "some voice packages unavailable"
  elif command -v dnf >/dev/null; then
    sudo dnf install -y espeak-ng pulseaudio-utils alsa-utils 2>/dev/null \
      && ok "voice packages installed" || warn "some voice packages unavailable"
  fi

  # PipeWire-native recorder/player (pw-record / pw-play).  On modern
  # PipeWire-only desktops — including Phosh / NetHunter Pro on the phone —
  # this is the capture path most likely to actually work when parecord
  # can't reach the server.  Installed SEPARATELY from the line above, and
  # always ending in ok/warn, so an unknown package name on one mirror can
  # never abort the install or take the core recorders (parecord/arecord)
  # down with it.
  if command -v pw-record >/dev/null 2>&1; then
    ok "PipeWire recorder already present (pw-record)"
  elif command -v apt-get >/dev/null; then
    sudo apt-get install -y pipewire-bin 2>/dev/null \
      && ok "PipeWire tools installed (pw-record / pw-play)" \
      || warn "pipewire-bin not on this mirror — parecord/arecord still cover recording"
  elif command -v pacman >/dev/null; then
    sudo pacman -Sy --needed --noconfirm pipewire 2>/dev/null \
      && ok "PipeWire tools installed" \
      || warn "pipewire unavailable here — parecord/arecord still cover recording"
  elif command -v dnf >/dev/null; then
    sudo dnf install -y pipewire-utils 2>/dev/null \
      && ok "PipeWire tools installed" \
      || warn "pipewire-utils unavailable here — parecord/arecord still cover recording"
  fi

  # Piper neural voice — much nicer than espeak.  Best-effort pip install.
  say "Piper neural voice (optional, sounds better than espeak)…"
  if command -v piper >/dev/null 2>&1 || python3 -c "import piper" >/dev/null 2>&1; then
    ok "piper already present"
  elif python3 -m pip install --user --break-system-packages --quiet piper-tts 2>/dev/null; then
    ok "piper installed (pip)"
  else
    warn "piper not installed — Kali uses espeak until you add it:"
    warn "   python3 -m pip install --user --break-system-packages piper-tts"
  fi

  # A voice model for Piper.  Pleasant British female (jenny), ~63MB.
  VOICE_DIR="${DATA_DIR}/voices"
  mkdir -p "${VOICE_DIR}" 2>/dev/null || true
  if ls "${VOICE_DIR}"/*.onnx >/dev/null 2>&1; then
    ok "piper voice model already present"
  else
    if command -v curl >/dev/null;  then DL=(curl -fsSL -o)
    elif command -v wget >/dev/null; then DL=(wget -qO)
    else DL=(); fi
    if [ ${#DL[@]} -gt 0 ]; then
      say "downloading a voice model (en_GB jenny, ~63MB)…"
      HF="https://huggingface.co/rhasspy/piper-voices/resolve/main/en"
      J="${HF}/en_GB/jenny_dioco/medium/en_GB-jenny_dioco-medium.onnx"
      if "${DL[@]}" "${VOICE_DIR}/en_GB-jenny_dioco-medium.onnx" "${J}" 2>/dev/null \
         && "${DL[@]}" "${VOICE_DIR}/en_GB-jenny_dioco-medium.onnx.json" "${J}.json" 2>/dev/null; then
        ok "voice model installed → ${VOICE_DIR}"
      else
        warn "jenny download failed — trying en_US lessac…"
        L="${HF}/en_US/lessac/medium/en_US-lessac-medium.onnx"
        if "${DL[@]}" "${VOICE_DIR}/en_US-lessac-medium.onnx" "${L}" 2>/dev/null \
           && "${DL[@]}" "${VOICE_DIR}/en_US-lessac-medium.onnx.json" "${L}.json" 2>/dev/null; then
          ok "voice model installed (en_US lessac) → ${VOICE_DIR}"
        else
          warn "no voice model fetched — espeak still works; grab one later from"
          warn "   https://huggingface.co/rhasspy/piper-voices"
        fi
      fi
    else
      warn "neither curl nor wget present — skipped voice model download"
    fi
  fi
  # ── verify what actually landed, so you know before you tap the mic ──
  # Mirror kali_voice.py's own detection order so the report matches what
  # the app will really pick.  Every branch ends in ok/warn (returns 0),
  # and the `|| true` keeps the command-substitution safe under `set -e`.
  REC="$(command -v parecord || command -v pw-record || command -v arecord || command -v ffmpeg || true)"
  PLY="$(command -v paplay || command -v pw-play || command -v aplay || command -v ffplay || command -v play || true)"
  if [ -n "$REC" ]; then
    ok "microphone recording ready → $(basename "$REC")"
  else
    warn "no recorder found — voice INPUT will stay hidden until you install one of:"
    warn "   pulseaudio-utils (parecord) · pipewire-bin (pw-record) · alsa-utils (arecord)"
  fi
  if [ -n "$PLY" ]; then
    ok "audio playback ready → $(basename "$PLY")"
  else
    warn "no audio player found — voice OUTPUT won't play; install pulseaudio-utils or alsa-utils"
  fi

  say "voice input transcribes via SiliconFlow SenseVoice or Groq Whisper (whichever key you've set)"
  say "turn it on per chat with the 🔊 button, or in Settings → Voice"
else
  warn "skipping voice setup (--no-voice)"
fi

# ── 7. Source files ───────────────────────────────────────────────

step "source files"
mkdir -p "${INSTALL_DIR}" "${CONFIG_DIR}" "${BIN_DIR}" "${DESKTOP_DIR}" \
         "${BACKUP_DIR}" "${ICON_DIR}"

HAVE_LOCAL=1
if [ -z "${SCRIPT_DIR}" ]; then
  HAVE_LOCAL=0
else
  for f in "${REQUIRED_FILES[@]}"; do
    [ -f "${SCRIPT_DIR}/${f}" ] || { HAVE_LOCAL=0; break; }
  done
fi

if [ $HAVE_LOCAL -eq 1 ]; then
  ok "using local source from ${SCRIPT_DIR}"
  SRC_DIR="${SCRIPT_DIR}"
else
  say "fetching from github.com/${GITHUB_REPO}@${GITHUB_BRANCH}"
  command -v curl >/dev/null || sudo apt-get install -y curl
  TMP=$(mktemp -d)
  trap "rm -rf ${TMP}" EXIT
  for f in "${REQUIRED_FILES[@]}"; do
    url="https://raw.githubusercontent.com/${GITHUB_REPO}/${GITHUB_BRANCH}/${f}"
    say "fetch ${f}"
    if ! curl -fsSL "$url" -o "${TMP}/${f}"; then
      fatal "could not fetch ${f} from ${url}"
    fi
  done
  for f in "${OPTIONAL_FILES[@]}"; do
    url="https://raw.githubusercontent.com/${GITHUB_REPO}/${GITHUB_BRANCH}/${f}"
    curl -fsSL "$url" -o "${TMP}/${f}" 2>/dev/null || true
  done
  # Sidecar (kali_ext): fetch the whole package so remote installs get the
  # headroom / verify / pentest features and the optional extensions, not
  # just the core.  Best-effort and self-guarding — if the package __init__
  # can't be fetched we skip the directory entirely, which leaves any
  # already-installed sidecar untouched (the copy step below is gated on the
  # directory existing).
  EXT_URL_BASE="https://raw.githubusercontent.com/${GITHUB_REPO}/${GITHUB_BRANCH}/kali_ext"
  if curl -fsSL "${EXT_URL_BASE}/__init__.py" -o "${TMP}/.ext_init_probe" 2>/dev/null; then
    mkdir -p "${TMP}/kali_ext"
    mv "${TMP}/.ext_init_probe" "${TMP}/kali_ext/__init__.py"
    for f in "${EXT_FILES[@]}"; do
      [ "$f" = "__init__.py" ] && continue
      curl -fsSL "${EXT_URL_BASE}/${f}" -o "${TMP}/kali_ext/${f}" 2>/dev/null || true
    done
    # Verify every module arrived non-empty.  A partial sidecar silently
    # disables features, so retry anything missing, and if it still can't be
    # completed, drop the directory so a half-install can't overwrite a good one.
    _ext_missing=""
    for f in "${EXT_FILES[@]}"; do
      [ -s "${TMP}/kali_ext/${f}" ] || _ext_missing="${_ext_missing} ${f}"
    done
    if [ -n "${_ext_missing}" ]; then
      warn "kali_ext incomplete, retrying:${_ext_missing}"
      for f in ${_ext_missing}; do
        curl -fsSL "${EXT_URL_BASE}/${f}" -o "${TMP}/kali_ext/${f}" 2>/dev/null || true
      done
      _ext_missing=""
      for f in "${EXT_FILES[@]}"; do
        [ -s "${TMP}/kali_ext/${f}" ] || _ext_missing="${_ext_missing} ${f}"
      done
    fi
    if [ -n "${_ext_missing}" ]; then
      warn "kali_ext still missing:${_ext_missing} — skipping sidecar (keeping any existing copy)"
      rm -rf "${TMP}/kali_ext"
    else
      ok "fetched kali_ext sidecar (all ${#EXT_FILES[@]} modules present)"
    fi
  else
    rm -f "${TMP}/.ext_init_probe" 2>/dev/null || true
    warn "could not fetch kali_ext sidecar — installing core only"
  fi
  SRC_DIR="${TMP}"
fi

# Migrate from oracle install if present and we don't have a kali DB yet
if [ -f "${OLD_DATA_DIR}/chats.db" ] && [ ! -f "${DATA_DIR}/chats.db" ]; then
  say "migrating chat history from oracle → kali"
  cp "${OLD_DATA_DIR}/chats.db" "${DATA_DIR}/chats.db"
  ok "chats migrated (oracle install left intact)"
fi

# Back up existing chat DB before code change
if [ -f "${DATA_DIR}/chats.db" ]; then
  STAMP=$(date +%Y%m%d-%H%M%S)
  cp "${DATA_DIR}/chats.db" "${BACKUP_DIR}/chats-${STAMP}.db"
  ok "backed up chat DB → backups/chats-${STAMP}.db"
fi

# Parse-check incoming files BEFORE overwriting
for f in "${REQUIRED_FILES[@]}"; do
  python3 -c "import ast; ast.parse(open('${SRC_DIR}/${f}').read())" \
    || fatal "${f} has a syntax error — refusing to install"
done
ok "incoming files parse cleanly"

# Report the version transition (purely informational; never blocks).
_ver_of() {
  grep -oE 'VERSION[[:space:]]*=[[:space:]]*"[^"]+"' "$1" 2>/dev/null \
    | head -1 | sed -E 's/.*"([^"]+)".*/\1/'
}
NEW_VER="$(_ver_of "${SRC_DIR}/kali.py")"
OLD_VER=""
[ -f "${INSTALL_DIR}/kali.py" ] && OLD_VER="$(_ver_of "${INSTALL_DIR}/kali.py")"
if [ -n "${OLD_VER}" ] && [ -n "${NEW_VER}" ] && [ "${OLD_VER}" != "${NEW_VER}" ]; then
  ok "updating Kali ${OLD_VER} → ${NEW_VER}"
elif [ -n "${OLD_VER}" ] && [ "${OLD_VER}" = "${NEW_VER}" ]; then
  say "Kali ${NEW_VER} already current — refreshing files"
elif [ -n "${NEW_VER}" ]; then
  ok "installing Kali ${NEW_VER}"
fi

for f in "${REQUIRED_FILES[@]}"; do
  cp "${SRC_DIR}/${f}" "${INSTALL_DIR}/${f}"
done
# (the icon is installed below from an inline heredoc — guaranteed)
ok "code installed at ${INSTALL_DIR}"

# ── 7a2. Install the optional kali_ext sidecar (memory/skills/foresight) ──
# Additive: if absent, Kali simply runs without the extensions (every hook
# is guarded). If present, parse-check every module before copying so a
# broken sidecar can never overwrite a working one.
if [ -d "${SRC_DIR}/kali_ext" ]; then
  if python3 - "${SRC_DIR}/kali_ext" <<'PYEOF'
import ast, sys, pathlib
root = pathlib.Path(sys.argv[1])
bad = []
for p in root.rglob("*.py"):
    try:
        ast.parse(p.read_text())
    except SyntaxError as e:
        bad.append(f"{p}: {e}")
if bad:
    print("\n".join(bad)); sys.exit(1)
PYEOF
  then
    rm -rf "${INSTALL_DIR}/kali_ext"
    cp -r "${SRC_DIR}/kali_ext" "${INSTALL_DIR}/kali_ext"
    rm -rf "${INSTALL_DIR}/kali_ext/__pycache__"
    ok "kali_ext sidecar installed (extensions are off until enabled in settings)"
  else
    warn "kali_ext has a syntax error — skipping it; Kali will run without extensions"
  fi
fi

# ── 7b. Install the icon (INLINE — guaranteed to exist) ───────────

step "icon"

# Wipe any cached/old icon files first — under BOTH the new app-id name
# and the legacy "kali-dragon" name.  GTK/Phosh/KDE aggressively cache
# icons; stale files here mean the user keeps seeing the old/missing one.
rm -f "${INSTALL_DIR}/kali-dragon.svg" 2>/dev/null || true
rm -f "${INSTALL_DIR}/${APP_ID}.svg"   2>/dev/null || true
for sz in scalable 16x16 22x22 24x24 32x32 48x48 64x64 96x96 128x128 256x256 512x512; do
  for nm in kali-dragon "${APP_ID}"; do
    rm -f "${HOME}/.local/share/icons/hicolor/${sz}/apps/${nm}.svg" 2>/dev/null || true
    rm -f "${HOME}/.local/share/icons/hicolor/${sz}/apps/${nm}.png" 2>/dev/null || true
  done
done

# Write the dragon SVG from an inlined heredoc.  This means the icon
# is ALWAYS installed — no dependency on a successful GitHub fetch.
# It is named after the app-id so GTK4 resolves it as the WINDOW icon
# and KDE associates it with the taskbar entry.
write_dragon_svg() {
  local target="$1"
  mkdir -p "$(dirname "${target}")"
  cat > "${target}" <<'KALI_DRAGON_SVG_EOF'
<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="256" height="256">
  <rect x="8" y="8" width="240" height="240" rx="52" ry="52" fill="#1e1e2e"/>
  <rect x="8" y="8" width="240" height="240" rx="52" ry="52"
        fill="none" stroke="#313244" stroke-width="2"/>
  <g fill="#f2f2f7" fill-rule="evenodd">
    <polygon points="128,28 119,54 137,54"/>
    <path d="M 119,54 L 92,47 L 83,56 L 69,49 L 62,59 L 48,52 L 41,64
             L 30,59 L 27,75 L 37,79 L 30,87 L 42,91 L 37,99 L 51,101
             L 48,110 L 62,108 L 60,119 L 76,113 L 85,104 L 96,92
             L 105,79 L 116,69 Z"/>
    <path d="M 137,54 L 164,47 L 173,56 L 187,49 L 194,59 L 208,52 L 215,64
             L 226,59 L 229,75 L 219,79 L 226,87 L 214,91 L 219,99 L 205,101
             L 208,110 L 194,108 L 196,119 L 180,113 L 171,104 L 160,92
             L 151,79 L 140,69 Z"/>
    <path d="M 88,106 L 76,120 L 83,125 L 92,116 L 96,123 L 103,113 L 99,102 Z"/>
    <path d="M 168,106 L 180,120 L 173,125 L 164,116 L 160,123 L 153,113 L 157,102 Z"/>
    <path d="M 64,126 L 50,144 L 57,153 L 45,158 L 57,167 L 50,177 L 64,172
             L 62,184 L 75,172 L 71,158 L 78,146 L 75,135 Z"/>
    <path d="M 192,126 L 206,144 L 199,153 L 211,158 L 199,167 L 206,177
             L 192,172 L 194,184 L 181,172 L 185,158 L 178,146 L 181,135 Z"/>
    <path d="M 104,79 L 152,79 L 162,103 L 162,117 L 153,133 L 128,147
             L 103,133 L 94,117 L 94,103 Z"/>
  </g>
  <g fill="#1e1e2e">
    <polygon points="128,90 121,104 128,118 135,104"/>
    <path d="M 104,114 L 120,121 L 120,126 L 115,126 L 104,121 Z"/>
    <path d="M 152,114 L 136,121 L 136,126 L 141,126 L 152,121 Z"/>
  </g>
  <g fill="#f2f2f7" fill-rule="evenodd">
    <path d="M 84,126 L 74,140 L 81,150 L 93,145 L 98,135 L 93,128 Z"/>
    <path d="M 172,126 L 182,140 L 175,150 L 163,145 L 158,135 L 163,128 Z"/>
    <path d="M 100,145 L 156,145 L 152,170 L 142,180 L 128,185 L 114,180
             L 104,170 Z"/>
  </g>
  <path fill="#1e1e2e" d="M 116,162 L 140,162 L 137,173 L 128,178 L 119,173 Z"/>
  <g fill="#f2f2f7" fill-rule="evenodd">
    <polygon points="81,150 70,184 84,176 89,156"/>
    <polygon points="95,168 90,194 102,184 104,170"/>
    <polygon points="175,150 186,184 172,176 167,156"/>
    <polygon points="161,168 166,194 154,184 152,170"/>
    <path d="M 113,180 L 104,206 L 116,197 L 120,208 L 124,194 L 128,210
             L 132,194 L 136,208 L 140,197 L 152,206 L 143,180 L 136,184
             L 128,185 L 120,184 Z"/>
    <polygon points="124,194 128,224 132,194"/>
  </g>
</svg>
KALI_DRAGON_SVG_EOF
}

# Icon: prefer the real Kali logo if it shipped with this install (it's in
# SRC_DIR for a local checkout, or was fetched into TMP for a curl|bash
# install — both land in SRC_DIR).  Fall back to the embedded placeholder
# only if the logo isn't there, so the app always has *an* icon.
if [ -s "${SRC_DIR}/${APP_ID}.svg" ]; then
  cp "${SRC_DIR}/${APP_ID}.svg" "${INSTALL_DIR}/${APP_ID}.svg"
  cp "${SRC_DIR}/${APP_ID}.svg" "${ICON_DIR}/${APP_ID}.svg"
  ok "icon installed from ${APP_ID}.svg"
else
  write_dragon_svg "${INSTALL_DIR}/${APP_ID}.svg"
  write_dragon_svg "${ICON_DIR}/${APP_ID}.svg"
fi

# Place the chat-background watermark and the emblem in the install dir so the
# app finds them at runtime (best-effort — the chat simply has no watermark if
# the file isn't there).
for _art in kali-watermark.png kali-dragon.svg kali-cross.svg kali-avatar.png; do
  if [ -s "${SRC_DIR}/${_art}" ]; then
    cp "${SRC_DIR}/${_art}" "${INSTALL_DIR}/${_art}" 2>/dev/null || true
  fi
done

# Sanity check: SVG file exists and isn't empty
if [ ! -s "${ICON_DIR}/${APP_ID}.svg" ]; then
  err "icon write failed — ${APP_ID}.svg is missing or empty in ${ICON_DIR}"
else
  ok "icon installed at ${ICON_DIR}/${APP_ID}.svg"
fi

# ── 8. Launcher + desktop ─────────────────────────────────────────

cat > "${BIN_DIR}/kali" <<EOF
#!/usr/bin/env bash
cd "${INSTALL_DIR}" || exit 1
exec python3 kali.py "\$@"
EOF
chmod +x "${BIN_DIR}/kali"

# Icon name reference (theme lookup), NOT absolute path.  GTK/Phosh/KDE
# icon caches work on theme names; an absolute path bypasses the cache
# and is much less reliable.  The .desktop is named after the app-id so
# KDE Plasma's task manager matches the running window to this entry.
rm -f "${DESKTOP_DIR}/kali.desktop"   # remove legacy entry to avoid a dupe
cat > "${DESKTOP_DIR}/${APP_ID}.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Kali
GenericName=AI Assistant
Comment=Personal, loyal AI assistant with full OS access
Exec=${BIN_DIR}/kali
Icon=${APP_ID}
Terminal=false
Categories=Utility;Network;Development;
Keywords=ai;assistant;groq;chat;jarvis;
StartupWMClass=${APP_ID}
StartupNotify=true
EOF
update-desktop-database "${DESKTOP_DIR}" 2>/dev/null || true

# Force-refresh icon caches so the new dragon shows up immediately.
HICOLOR_DIR="${HOME}/.local/share/icons/hicolor"
if command -v gtk-update-icon-cache >/dev/null; then
  gtk-update-icon-cache -f -t "${HICOLOR_DIR}" 2>/dev/null || true
fi
# Bust GTK's pixmap cache too (some Phosh builds keep a separate one)
rm -f "${HOME}/.cache/icon-cache.kcache" 2>/dev/null || true
rm -rf "${HOME}/.cache/thumbnails/normal" 2>/dev/null || true
# Rebuild KDE Plasma's sycoca so the new .desktop + icon register without
# a logout.  Harmless / no-op on non-KDE desktops.
for kbs in kbuildsycoca6 kbuildsycoca5; do
  command -v "$kbs" >/dev/null && "$kbs" --noincremental 2>/dev/null && break
done

# Touch the desktop entry so file-watchers / Phosh re-scan it
touch "${DESKTOP_DIR}/${APP_ID}.desktop" 2>/dev/null || true

ok "launcher + desktop entry installed"

# ── 9. Groq API key prompt ────────────────────────────────────────

GROQ_KEY_TO_WRITE=""
if [ $SKIP_GROQ -eq 0 ]; then
  step "Groq API key (optional)"
  # Priority: env var > existing settings > prompt
  if [ -n "${GROQ_API_KEY:-}" ]; then
    GROQ_KEY_TO_WRITE="${GROQ_API_KEY}"
    ok "using GROQ_API_KEY from environment"
  elif [ -f "${CONFIG_DIR}/settings.json" ] \
       && python3 -c "import json; d=json.load(open('${CONFIG_DIR}/settings.json')); exit(0 if d.get('groq_api_key') else 1)" 2>/dev/null; then
    ok "existing Groq key preserved in settings"
  elif [ $NO_PROMPT -eq 1 ] || [ ! -t 0 ]; then
    warn "no key set — add one in Settings → Backends to start chatting"
  else
    echo
    echo "  Groq is FREE and FAST.  Sign up at https://console.groq.com"
    echo "  to get a key, then paste it here.  Press ENTER to skip."
    echo "  (You can also use SiliconFlow, Novita, GitHub, or Google —"
    echo "   add any of those keys later in Settings → Backends.)"
    echo
    printf "  Groq API key: "
    read -r USER_GROQ_KEY
    if [ -n "${USER_GROQ_KEY}" ]; then
      GROQ_KEY_TO_WRITE="${USER_GROQ_KEY}"
      ok "key captured"
    else
      warn "no key — add one later in Settings → Backends"
    fi
  fi
fi

# ── 10. Write settings.json ───────────────────────────────────────

step "settings"
SETTINGS_FILE="${CONFIG_DIR}/settings.json"

SETTINGS_FILE_PATH="${SETTINGS_FILE}" \
NEW_GROQ_KEY="${GROQ_KEY_TO_WRITE}" \
INSTALL_DIR_PATH="${INSTALL_DIR}" \
python3 - <<'PYEOF'
import json, os, sys
settings_file = os.environ['SETTINGS_FILE_PATH']
new_groq_key  = os.environ.get('NEW_GROQ_KEY', '')
install_dir   = os.environ.get('INSTALL_DIR_PATH', '')

# Source of truth: kali_core.DEFAULT_SETTINGS from the freshly-installed code.
# Importing it here means the written settings.json can never drift from the
# app's own defaults (active provider, per-provider models, theme, …) — which
# is exactly how the old hardcoded copy fell out of sync.  kali_core is pure
# stdlib (no GTK), so this import is safe at install time.  If it can't be
# imported for any reason, fall back to a minimal set and let the app backfill
# the rest from its own DEFAULT_SETTINGS on first launch.
defaults = None
if install_dir and os.path.isdir(install_dir):
    sys.path.insert(0, install_dir)
    try:
        import kali_core
        defaults = dict(kali_core.DEFAULT_SETTINGS)
    except Exception as e:
        print(f"  (note: kali_core defaults unavailable, using fallback — "
              f"{type(e).__name__})")

if defaults is None:
    # Minimal fallback only.  load_settings() merges the full DEFAULT_SETTINGS
    # over whatever is on disk at launch, so the rest is filled in then.
    providers = {
        "groq":        "llama-3.3-70b-versatile",
        "siliconflow": "deepseek-ai/DeepSeek-V4-Flash",
        "novita":      "qwen/qwen3-coder-480b-a35b-instruct",
        "github":      "openai/gpt-4.1",
        "google":      "gemini-2.5-pro",
    }
    defaults = {
        "active_provider": "siliconflow",
        "temperature": 0.7,
        "top_p": 0.9,
        "max_tokens": 2048,
        "system_prompt": "",
        "agent_mode_default": True,
        "confirm_all_commands": True,
        "theme": "kali",
        "ui_scale": 0,
    }
    for key, model in providers.items():
        defaults[f"{key}_api_key"] = ""
        defaults[f"{key}_model"] = model

if os.path.exists(settings_file):
    try:
        with open(settings_file) as f:
            existing = json.load(f)
        for k, v in defaults.items():
            existing.setdefault(k, v)
        out = existing
    except Exception:
        out = dict(defaults)
else:
    out = dict(defaults)

# Apply Groq key from this installer run if one was captured
if new_groq_key:
    out['groq_api_key'] = new_groq_key

os.makedirs(os.path.dirname(settings_file), exist_ok=True)
with open(settings_file, "w") as f:
    json.dump(out, f, indent=2)

print(f"  active_provider = {out.get('active_provider')}")
print(f"  groq_key        = {'set' if out.get('groq_api_key') else '(not set — add via Settings)'}")
PYEOF
ok "settings written"

# ── 10b. Optional MCP setup (opt-in via WITH_MCP=1) ───────────────
# MCP lets Kali drive external tool servers, but it launches them as
# subprocesses — a real RCE surface (NSA 2026 guidance; CVE-2025-49596).
# So it stays OFF unless you explicitly ask for it, and even then we only
# wire a SAFE read-only default server (web fetch) when a runtime to launch
# it (uvx or npx) is already present.  Heavier servers you add yourself in
# Settings.  Runs AFTER settings.json so it isn't overwritten.
if [ "${WITH_MCP:-0}" = "1" ]; then
  step "mcp"
  _MCP_CMD=""; _MCP_ARGS=""
  if command -v uvx >/dev/null 2>&1; then
    _MCP_CMD="uvx"; _MCP_ARGS='["mcp-server-fetch"]'
  elif command -v npx >/dev/null 2>&1; then
    _MCP_CMD="npx"; _MCP_ARGS='["-y", "@modelcontextprotocol/server-fetch"]'
  fi
  if [ -n "${_MCP_CMD}" ]; then
    SETTINGS_FILE="${SETTINGS_FILE}" MCP_CMD="${_MCP_CMD}" \
    MCP_ARGS="${_MCP_ARGS}" python3 - <<'PYEOF'
import json, os, pathlib
sp = pathlib.Path(os.environ["SETTINGS_FILE"])
cmd = os.environ["MCP_CMD"]; args = json.loads(os.environ["MCP_ARGS"])
s = {}
if sp.exists():
    try: s = json.loads(sp.read_text())
    except Exception: s = {}
servers = s.get("mcp_servers") or []
if not any(x.get("name") == "fetch" for x in servers):
    servers.append({"name": "fetch", "command": cmd, "args": args})
s["mcp_servers"] = servers
s["mcp_enabled"] = True            # explicit opt-in
sp.parent.mkdir(parents=True, exist_ok=True)
sp.write_text(json.dumps(s, indent=2))
print("  configured MCP 'fetch' server via", cmd)
PYEOF
    ok "MCP enabled with a safe 'fetch' server (via ${_MCP_CMD})"
  else
    warn "WITH_MCP=1 but neither uvx nor npx found — install one then re-run; MCP left OFF"
  fi
fi

step "done in $(elapsed)s"
echo
echo "  Open your app grid → click ${G}Kali${X}"
echo "  Or from terminal:  ${G}kali${X}"
echo
echo "  ${Y}If the icon looks wrong (old/missing/generic):${X}"
echo "    Phosh caches icons aggressively.  Force it to reload:"
echo "      ${G}killall phosh${X}     # (it respawns automatically)"
echo "    or log out and back in."
echo

if ! echo ":${PATH}:" | grep -q ":${BIN_DIR}:"; then
  warn "${BIN_DIR} is not in your PATH (only matters for terminal launch)"
  echo "      Add to ~/.bashrc:  export PATH=\"\$HOME/.local/bin:\$PATH\""
  echo
fi

echo "  ${G}New in this version:${X}"
echo "    • Multi-source verification — ask her to ${G}verify${X} a claim and she"
echo "      cross-checks several independent sources and flags propaganda/satire."
echo "    • Pentest support — ask for a ${G}recon plan${X}; she proposes (never auto-runs)."
echo "      Have her run ${G}tooling_check${X} to see which offensive tools are installed"
echo "      and get the apt/go line for any that aren't."
echo "    • Context compression keeps long sessions cheap; click ${G}Thoughts${X} on a"
echo "      reply to see the model's reasoning when it exposes any."
echo

echo "  ${D}Update:    re-run this script${X}"
echo "  ${D}Uninstall: ${SELF_CMD} --uninstall${X}"
echo
