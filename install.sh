#!/usr/bin/env bash
#
# install.sh — Kali assistant: zero-to-running installer
#
# What it does, in order:
#   1. checks Python 3.10+
#   2. installs GTK4 + libadwaita bindings (apt / pacman / dnf)
#   3. installs the Groq Python library (cloud backend, primary)
#   4. installs Ollama if missing (local fallback backend)
#   5. starts `ollama serve` if not already running (systemd --user, or detached)
#   6. pulls a small chat model (default: llama3.2:1b, ~1.3 GB)
#   7. installs the three .py files + dragon icon + launcher + desktop entry + systemd unit
#   8. asks for a Groq API key (optional — skip & set it later in Settings)
#   9. writes settings.json so the app opens straight into a working chat
#   10. (if present) migrates oracle/* chats and settings to kali/*
#
# After this: click "Kali" in your app grid.  That's it.
#
# Estimated time on a OnePlus 6 over WiFi:
#   - first install:  ~3-8 min (most of it is the model download)
#   - subsequent re-runs:  ~5 seconds (skips everything already done)
#
# Usage:
#   ./install.sh                     # install or update
#   ./install.sh --update            # explicit update (same code path)
#   ./install.sh --uninstall         # remove Kali (chat history kept)
#   ./install.sh --remove-oracle     # remove the old Oracle install
#   ./install.sh --refresh-ollama    # also re-run the ollama installer
#   ./install.sh --no-systemd        # don't install the systemd unit
#   ./install.sh --no-ollama         # don't touch ollama
#   ./install.sh --no-model          # don't pull a model
#   ./install.sh --no-groq           # don't install the groq library / skip key prompt
#   ./install.sh --no-prompt         # skip ALL interactive prompts
#
# Env overrides:
#   KALI_MODEL=tinyllama:1.1b   ./install.sh    # smaller model (~640 MB)
#   KALI_MODEL=llama3.2:1b      ./install.sh    # default — best 1B
#   KALI_MODEL=qwen2.5:0.5b     ./install.sh    # tiny but capable (~400 MB)
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
SKIP_OLLAMA=0
SKIP_MODEL=0
SKIP_GROQ=0
NO_PROMPT=0
REFRESH_OLLAMA=0
for arg in "$@"; do
  case "$arg" in
    --uninstall)         ACTION="uninstall" ;;
    --update)            ACTION="install" ;;
    --remove-oracle)     ACTION="remove-oracle" ;;
    --no-systemd)        SKIP_SYSTEMD=1 ;;
    --no-ollama)         SKIP_OLLAMA=1 ;;
    --no-model)          SKIP_MODEL=1 ;;
    --no-groq)           SKIP_GROQ=1 ;;
    --no-prompt)         NO_PROMPT=1 ;;
    --refresh-ollama)    REFRESH_OLLAMA=1 ;;
    -h|--help)
      sed -n '2,/^$/p' "$0" | sed 's/^# \?//'
      exit 0 ;;
  esac
done

# ── pretty printing ───────────────────────────────────────────────

if [ -t 1 ]; then
  Y="\033[33m"; G="\033[32m"; R="\033[31m"; B="\033[36m"; M="\033[35m"; D="\033[90m"; X="\033[0m"
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

REQUIRED_FILES=(kali.py kali_core.py kali_persona.py)
OPTIONAL_FILES=(org.thepriest.kali.svg kali-dragon.svg)
GITHUB_REPO="${KALI_REPO:-the-priest/oracle5}"
GITHUB_BRANCH="${KALI_BRANCH:-main}"
MODEL="${KALI_MODEL:-llama3.2:1b}"

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

${M}╔════════════════════════════════════╗${X}
${M}║${X}  ${B}Kali${X} — local, loyal AI assistant   ${M}║${X}
${M}╚════════════════════════════════════╝${X}

  fallback model:  ${MODEL}
  repo:            ${GITHUB_REPO}@${GITHUB_BRANCH}
  install dir:     ${INSTALL_DIR}

  Cloud backend (Groq) is primary, local Ollama is fallback.
  Ollama runs ONLY while the app is open (starts on launch, stops on quit).
  Heads up: the local model pull is the slowest step (~3-5 min on
  phone WiFi for the default 1.3 GB model).  Stay put.
EOF

# Detect a stale oracle install and warn (don't auto-remove — let the user decide)
if [ -f "${DESKTOP_DIR}/oracle.desktop" ] || [ -f "${BIN_DIR}/oracle" ] \
   || [ -f "${SYSTEMD_DIR}/oracle-ollama.service" ]; then
  echo
  warn "previous Oracle installation detected"
  echo "      To remove it:  $0 --remove-oracle"
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
      warn "could not auto-install groq library — Kali will work with Ollama only"
      warn "to fix later:   python3 -m pip install --user --break-system-packages groq"
    fi
  fi
else
  warn "skipping groq library (--no-groq)"
fi

# ── 4. Ollama ─────────────────────────────────────────────────────

if [ $SKIP_OLLAMA -eq 0 ]; then
  step "Ollama"
  if command -v ollama >/dev/null; then
    OLD_VER=$(ollama --version 2>/dev/null | head -1 || echo "?")
    ok "ollama present: ${OLD_VER}"
    if [ $REFRESH_OLLAMA -eq 1 ]; then
      say "refreshing ollama (--refresh-ollama)"
      say "this downloads ~1.5 GB and takes 1-5 min — output below is from ollama's installer"
      printf '%s\n' "${D}──────────────────────────────────────────────${X}"
      curl -fsSL https://ollama.com/install.sh | sh || \
        warn "refresh failed, continuing with existing"
      printf '%s\n' "${D}──────────────────────────────────────────────${X}"
      NEW_VER=$(ollama --version 2>/dev/null | head -1 || echo "?")
      [ "${NEW_VER}" != "${OLD_VER}" ] && ok "updated: ${OLD_VER} → ${NEW_VER}" || \
        ok "ollama already current"
    else
      say "(skipping refresh — pass --refresh-ollama to force re-install)"
    fi
  else
    say "installing ollama via official script"
    say "this downloads ~1.5 GB and takes 1-5 min — output below is from ollama's installer"
    printf '%s\n' "${D}──────────────────────────────────────────────${X}"
    command -v curl >/dev/null || sudo apt-get install -y curl
    curl -fsSL https://ollama.com/install.sh | sh || fatal "ollama install failed"
    printf '%s\n' "${D}──────────────────────────────────────────────${X}"
    ok "ollama installed: $(ollama --version 2>/dev/null | head -1)"
  fi
else
  warn "skipping ollama (--no-ollama)"
fi

# ── 5. Start ollama serve ─────────────────────────────────────────

ollama_healthy() {
  curl -sf --max-time 1 http://127.0.0.1:11434/api/version >/dev/null 2>&1
}

wait_for_ollama() {
  local tries=40   # 40 * 0.5s = 20s
  while [ $tries -gt 0 ]; do
    ollama_healthy && return 0
    sleep 0.5
    tries=$((tries - 1))
  done
  return 1
}

start_ollama_temp() {
  # Start ollama just long enough to pull the model.  Tracks whether we
  # started it so we can stop it after.
  if ollama_healthy; then
    OLLAMA_STARTED_TEMP=0
    return 0
  fi
  say "starting ollama temporarily (for the model pull only)"
  nohup ollama serve >/dev/null 2>&1 &
  disown 2>/dev/null || true
  if wait_for_ollama; then
    OLLAMA_STARTED_TEMP=1
    return 0
  fi
  return 1
}

stop_ollama_temp() {
  # Stop only if we started it.  Leaves user-started ollamas alone.
  if [ "${OLLAMA_STARTED_TEMP:-0}" = "1" ]; then
    say "stopping the temporary ollama"
    pkill -u "${USER:-$(id -un)}" -f "ollama serve" 2>/dev/null || true
    sleep 1
  fi
}

install_systemd_unit_file() {
  # Install the unit file but DO NOT enable or start it.  User can
  # manually `systemctl --user enable kali-ollama.service` if they want
  # ollama always-on.  Default: app starts ollama on launch, stops on quit.
  if [ $SKIP_SYSTEMD -eq 0 ] && command -v systemctl >/dev/null; then
    mkdir -p "${SYSTEMD_DIR}"
    OLLAMA_BIN=$(command -v ollama || echo "/usr/local/bin/ollama")
    cat > "${SYSTEMD_DIR}/kali-ollama.service" <<EOF
[Unit]
Description=Ollama server (managed by Kali)
After=default.target

[Service]
Type=simple
ExecStart=${OLLAMA_BIN} serve
Restart=on-failure
RestartSec=3
Environment=OLLAMA_HOST=127.0.0.1:11434
Environment=OLLAMA_KEEP_ALIVE=2m
Environment=OLLAMA_NUM_PARALLEL=1

[Install]
WantedBy=default.target
EOF
    systemctl --user daemon-reload
    ok "systemd unit file installed (NOT enabled — app manages ollama)"
  fi
}

# Make sure nothing's auto-started left over from earlier installs (oracle or kali)
disable_old_units() {
  for unit in oracle-ollama.service kali-ollama.service; do
    if systemctl --user is-enabled "${unit}" >/dev/null 2>&1; then
      systemctl --user disable "${unit}" >/dev/null 2>&1 || true
      systemctl --user stop    "${unit}" >/dev/null 2>&1 || true
      say "disabled previously-enabled ${unit}"
    fi
  done
}

if [ $SKIP_OLLAMA -eq 0 ]; then
  step "ollama service config"
  disable_old_units
  install_systemd_unit_file
fi

# ── 6. Pull a model ───────────────────────────────────────────────

if [ $SKIP_OLLAMA -eq 0 ] && [ $SKIP_MODEL -eq 0 ]; then
  step "fallback model: ${MODEL}"
  if ! start_ollama_temp; then
    warn "couldn't start ollama for the pull — skipping model"
  else
    if ollama list 2>/dev/null | awk 'NR>1{print $1}' | grep -qx "${MODEL}"; then
      ok "${MODEL} already pulled"
    else
      say "pulling ${MODEL} — progress below is from ollama (this is the slow step)"
      printf '%s\n' "${D}──────────────────────────────────────────────${X}"
      if ! ollama pull "${MODEL}"; then
        warn "pull failed.  Retrying in 3s..."
        sleep 3
        ollama pull "${MODEL}" || warn "could not pull ${MODEL} — continuing without local fallback"
      fi
      printf '%s\n' "${D}──────────────────────────────────────────────${X}"
      ok "${MODEL} pulled"
    fi
    stop_ollama_temp
  fi
else
  warn "skipping model pull"
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

for f in "${REQUIRED_FILES[@]}"; do
  cp "${SRC_DIR}/${f}" "${INSTALL_DIR}/${f}"
done
# (the icon is installed below from an inline heredoc — guaranteed)
ok "code installed at ${INSTALL_DIR}"

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

write_dragon_svg "${INSTALL_DIR}/${APP_ID}.svg"
write_dragon_svg "${ICON_DIR}/${APP_ID}.svg"

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
Comment=Local, loyal AI assistant with full OS access
Exec=${BIN_DIR}/kali
Icon=${APP_ID}
Terminal=false
Categories=Utility;Network;Development;
Keywords=ai;assistant;groq;ollama;chat;jarvis;
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
    warn "no key set — Kali will use Ollama until you add one in Settings"
  else
    echo
    echo "  Groq is FREE and FAST.  Sign up at https://console.groq.com"
    echo "  to get a key, then paste it here.  Press ENTER to skip."
    echo
    printf "  Groq API key: "
    read -r USER_GROQ_KEY
    if [ -n "${USER_GROQ_KEY}" ]; then
      GROQ_KEY_TO_WRITE="${USER_GROQ_KEY}"
      ok "key captured"
    else
      warn "no key — Kali will run on Ollama alone (you can add one later in Settings)"
    fi
  fi
fi

# ── 10. Write settings.json ───────────────────────────────────────

step "settings"
SETTINGS_FILE="${CONFIG_DIR}/settings.json"

DEFAULT_OLLAMA_MODEL="${MODEL}"
if [ $SKIP_MODEL -eq 1 ] || [ $SKIP_OLLAMA -eq 1 ]; then
  if command -v ollama >/dev/null; then
    AVAILABLE=$(ollama list 2>/dev/null | awk 'NR>1{print $1}' | head -1 || echo "")
    [ -n "${AVAILABLE}" ] && DEFAULT_OLLAMA_MODEL="${AVAILABLE}"
  fi
fi

SETTINGS_FILE_PATH="${SETTINGS_FILE}" \
DEFAULT_OLLAMA_MODEL="${DEFAULT_OLLAMA_MODEL}" \
NEW_GROQ_KEY="${GROQ_KEY_TO_WRITE}" \
python3 - <<'PYEOF'
import json, os
settings_file        = os.environ['SETTINGS_FILE_PATH']
default_ollama_model = os.environ['DEFAULT_OLLAMA_MODEL']
new_groq_key         = os.environ.get('NEW_GROQ_KEY', '')

defaults = {
    "groq_api_key": "",
    "groq_model": "llama-3.3-70b-versatile",
    "prefer_groq": True,
    "ollama_model": default_ollama_model,
    "temperature": 0.7,
    "top_p": 0.9,
    "num_ctx": 4096,
    "max_tokens": 2048,
    "system_prompt": "",
    "auto_start_ollama": True,
    "stop_ollama_on_quit": True,
    "agent_mode_default": True,
    "confirm_all_commands": True,
    "watcher_enabled": False,
    "watcher_check_updates": True,
    "watcher_check_downloads": True,
    "watcher_check_journal": False,
    "watcher_interval_minutes": 60,
    "theme": "mocha",
    "ui_scale": 0,  # 0 = auto-detect (must match kali_core DEFAULT_SETTINGS;
                    # a hardcoded 1.0 here pins the scale and disables the
                    # per-screen auto-sizing in _detect_ui_scale()).
    "show_token_count": False,
    "show_provider_pill": True,
}

if os.path.exists(settings_file):
    try:
        with open(settings_file) as f:
            existing = json.load(f)
        # Preserve all user-set values; only fill in missing keys with defaults.
        for k, v in defaults.items():
            existing.setdefault(k, v)
        # Migrate old 'default_model' (oracle) → 'ollama_model' if present
        if 'default_model' in existing and not existing.get('ollama_model'):
            existing['ollama_model'] = existing.pop('default_model')
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

print(f"  ollama_model = {out.get('ollama_model') or '(none — pick one in app)'}")
print(f"  groq_model   = {out.get('groq_model')}")
print(f"  groq_key     = {'set' if out.get('groq_api_key') else '(not set — add via Settings)'}")
PYEOF
ok "settings written"

# ── 11. Summary ───────────────────────────────────────────────────

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

echo "  ${D}Update:    re-run this script${X}"
echo "  ${D}Uninstall: $0 --uninstall${X}"
echo
