#!/usr/bin/env bash
#
# install.sh — Oracle: zero-to-running installer
#
# What this does, in order:
#   1.  checks Python 3.10+
#   2.  installs GTK4 + libadwaita bindings (apt / pacman / dnf)
#   3.  installs Ollama if missing, refreshes if present
#   4.  starts `ollama serve` (via systemd --user if available,
#       otherwise as a background process)
#   5.  pulls a small chat model (default: tinyllama:1.1b)
#   6.  installs the three .py files, launcher, desktop entry, systemd unit
#   7.  writes settings.json so the app opens straight into a working chat
#   8.  verifies the whole stack with a one-token test call
#
# After this: click "Oracle" in your app grid.  That's it.
#
# Usage:
#   ./install.sh                     # install or update
#   ./install.sh --update            # explicit update (same code path)
#   ./install.sh --uninstall         # remove (chat history kept)
#   ./install.sh --no-systemd        # don't install the systemd unit
#   ./install.sh --no-ollama         # don't touch ollama
#   ./install.sh --no-model          # don't pull a model
#
# Env overrides:
#   ORACLE_MODEL=llama3.2:1b   ./install.sh    # pull a different model
#   ORACLE_REPO=the-priest/oracle5  ORACLE_BRANCH=main  ./install.sh
#
# One-liner install from GitHub:
#   curl -fsSL https://raw.githubusercontent.com/the-priest/oracle5/main/install.sh | bash
#

set -euo pipefail

# ── flags ─────────────────────────────────────────────────────────

ACTION="install"
SKIP_SYSTEMD=0
SKIP_OLLAMA=0
SKIP_MODEL=0
for arg in "$@"; do
  case "$arg" in
    --uninstall)   ACTION="uninstall" ;;
    --update)      ACTION="install" ;;
    --no-systemd)  SKIP_SYSTEMD=1 ;;
    --no-ollama)   SKIP_OLLAMA=1 ;;
    --no-model)    SKIP_MODEL=1 ;;
    -h|--help)
      sed -n '2,/^$/p' "$0" | sed 's/^# \?//'
      exit 0 ;;
  esac
done

# ── pretty printing ───────────────────────────────────────────────

if [ -t 1 ]; then
  Y="\033[33m"; G="\033[32m"; R="\033[31m"; B="\033[36m"; D="\033[90m"; X="\033[0m"
else
  Y=""; G=""; R=""; B=""; D=""; X=""
fi
say()   { printf "${Y}[*]${X} %s\n" "$*"; }
ok()    { printf "${G}[+]${X} %s\n" "$*"; }
warn()  { printf "${Y}[!]${X} %s\n" "$*"; }
err()   { printf "${R}[!]${X} %s\n" "$*" >&2; }
fatal() { err "$*"; exit 1; }
step()  { printf "\n${B}== %s ==${X}\n" "$*"; }

# ── paths & config ────────────────────────────────────────────────

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" 2>/dev/null && pwd || echo "" )"
INSTALL_DIR="${HOME}/.local/share/oracle"
DATA_DIR="${HOME}/.local/share/oracle"
CONFIG_DIR="${HOME}/.config/oracle"
BIN_DIR="${HOME}/.local/bin"
DESKTOP_DIR="${HOME}/.local/share/applications"
SYSTEMD_DIR="${HOME}/.config/systemd/user"
BACKUP_DIR="${HOME}/.local/share/oracle/backups"

REQUIRED_FILES=(oracle.py oracle_core.py oracle_persona.py)
GITHUB_REPO="${ORACLE_REPO:-the-priest/oracle5}"
GITHUB_BRANCH="${ORACLE_BRANCH:-main}"
MODEL="${ORACLE_MODEL:-tinyllama:1.1b}"

# ── uninstall path ────────────────────────────────────────────────

uninstall() {
  step "uninstalling Oracle"
  systemctl --user stop    oracle-ollama.service 2>/dev/null || true
  systemctl --user disable oracle-ollama.service 2>/dev/null || true
  rm -f  "${SYSTEMD_DIR}/oracle-ollama.service"
  systemctl --user daemon-reload 2>/dev/null || true
  rm -f  "${BIN_DIR}/oracle"
  rm -f  "${DESKTOP_DIR}/oracle.desktop"
  update-desktop-database "${DESKTOP_DIR}" 2>/dev/null || true
  rm -f "${INSTALL_DIR}"/oracle*.py 2>/dev/null || true
  warn "chat history and settings were NOT removed."
  echo "      To wipe: rm -rf ${DATA_DIR} ${CONFIG_DIR}"
  ok "Oracle uninstalled."
  exit 0
}

[ "${ACTION}" = "uninstall" ] && uninstall

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
  warn "missing — installing"
  if command -v apt-get >/dev/null; then
    sudo apt-get update -qq
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

# ── 3. Ollama ─────────────────────────────────────────────────────

if [ $SKIP_OLLAMA -eq 0 ]; then
  step "Ollama"
  if command -v ollama >/dev/null; then
    OLD_VER=$(ollama --version 2>/dev/null | head -1 || echo "?")
    ok "found ollama: ${OLD_VER}"
    if command -v curl >/dev/null; then
      say "refreshing (idempotent — no-op if current)"
      curl -fsSL https://ollama.com/install.sh | sh >/dev/null 2>&1 || \
        warn "refresh failed, continuing with existing"
      NEW_VER=$(ollama --version 2>/dev/null | head -1 || echo "?")
      [ "${NEW_VER}" != "${OLD_VER}" ] && ok "updated: ${OLD_VER} → ${NEW_VER}"
    fi
  else
    say "installing ollama via official script"
    command -v curl >/dev/null || sudo apt-get install -y curl
    curl -fsSL https://ollama.com/install.sh | sh || fatal "ollama install failed"
    ok "ollama installed: $(ollama --version 2>/dev/null | head -1)"
  fi
else
  warn "skipping ollama (--no-ollama)"
fi

# ── 4. Start ollama serve ─────────────────────────────────────────

ollama_healthy() {
  curl -sf --max-time 1 http://127.0.0.1:11434/api/version >/dev/null 2>&1
}

wait_for_ollama() {
  local tries=40   # 40 * 0.5s = 20s
  while [ $tries -gt 0 ]; do
    if ollama_healthy; then
      return 0
    fi
    sleep 0.5
    tries=$((tries - 1))
  done
  return 1
}

start_ollama() {
  if ollama_healthy; then
    ok "ollama serve already running"
    return 0
  fi

  # Try systemd --user first (so it survives logout/login cleanly)
  if [ $SKIP_SYSTEMD -eq 0 ] && command -v systemctl >/dev/null; then
    mkdir -p "${SYSTEMD_DIR}"
    OLLAMA_BIN=$(command -v ollama || echo "/usr/local/bin/ollama")
    cat > "${SYSTEMD_DIR}/oracle-ollama.service" <<EOF
[Unit]
Description=Ollama server (managed by Oracle)
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
    systemctl --user enable oracle-ollama.service >/dev/null 2>&1 || true
    say "starting ollama via systemd --user"
    if systemctl --user start oracle-ollama.service 2>/dev/null; then
      if wait_for_ollama; then
        ok "ollama serve running (systemd)"
        return 0
      fi
    fi
    warn "systemd start failed or didn't come up — falling back to direct launch"
  fi

  # Fallback: launch in background, detached
  say "starting ollama serve directly"
  nohup ollama serve >/dev/null 2>&1 &
  disown 2>/dev/null || true
  if wait_for_ollama; then
    ok "ollama serve running (detached)"
    return 0
  fi
  return 1
}

if [ $SKIP_OLLAMA -eq 0 ]; then
  step "starting ollama serve"
  if ! start_ollama; then
    fatal "ollama serve didn't come up within 20s — check 'ollama serve' manually"
  fi
fi

# ── 5. Pull a model ───────────────────────────────────────────────

if [ $SKIP_OLLAMA -eq 0 ] && [ $SKIP_MODEL -eq 0 ]; then
  step "model: ${MODEL}"
  if ollama list 2>/dev/null | awk 'NR>1{print $1}' | grep -qx "${MODEL}"; then
    ok "${MODEL} already pulled"
  else
    say "pulling ${MODEL} — this can take a few minutes the first time"
    if ! ollama pull "${MODEL}"; then
      warn "pull failed.  Trying again in 3s..."
      sleep 3
      ollama pull "${MODEL}" || fatal "could not pull ${MODEL}"
    fi
    ok "${MODEL} pulled"
  fi

  say "smoke-testing the model"
  if echo "say ok" | timeout 30 ollama run "${MODEL}" >/dev/null 2>&1; then
    ok "${MODEL} responds"
  else
    warn "model didn't respond cleanly in 30s — Oracle will still launch, "
    warn "but first turn may be slow as the model warms up"
  fi
else
  warn "skipping model pull"
fi

# ── 6. Source files ───────────────────────────────────────────────

step "preparing source files"
mkdir -p "${INSTALL_DIR}" "${CONFIG_DIR}" "${BIN_DIR}" "${DESKTOP_DIR}" "${BACKUP_DIR}"

HAVE_LOCAL=1
if [ -z "${SCRIPT_DIR}" ]; then
  HAVE_LOCAL=0
else
  for f in "${REQUIRED_FILES[@]}"; do
    [ -f "${SCRIPT_DIR}/${f}" ] || { HAVE_LOCAL=0; break; }
  done
fi

if [ $HAVE_LOCAL -eq 1 ]; then
  ok "using local source files from ${SCRIPT_DIR}"
  SRC_DIR="${SCRIPT_DIR}"
else
  say "fetching source from github.com/${GITHUB_REPO}@${GITHUB_BRANCH}"
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
  SRC_DIR="${TMP}"
fi

# Back up existing chat DB before any code change
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
ok "code installed at ${INSTALL_DIR}"

# ── 7. Launcher + desktop + systemd unit ──────────────────────────

cat > "${BIN_DIR}/oracle" <<EOF
#!/usr/bin/env bash
cd "${INSTALL_DIR}" || exit 1
exec python3 oracle.py "\$@"
EOF
chmod +x "${BIN_DIR}/oracle"

cat > "${DESKTOP_DIR}/oracle.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Oracle
Comment=Local AI assistant
Exec=${BIN_DIR}/oracle
Icon=applications-science
Terminal=false
Categories=Utility;Network;
Keywords=ai;assistant;ollama;chat;
EOF
update-desktop-database "${DESKTOP_DIR}" 2>/dev/null || true
ok "launcher + desktop entry installed"

if [ $SKIP_SYSTEMD -eq 0 ] && command -v systemctl >/dev/null; then
  # already created above when starting ollama; ensure it's enabled
  systemctl --user enable oracle-ollama.service >/dev/null 2>&1 || true
  ok "systemd unit enabled (starts at login)"
fi

# ── 8. Write settings.json so app opens to a working chat ─────────

step "writing app settings"
SETTINGS_FILE="${CONFIG_DIR}/settings.json"

# Pick the model to set as default
DEFAULT_MODEL_FOR_SETTINGS="${MODEL}"
if [ $SKIP_MODEL -eq 1 ] || [ $SKIP_OLLAMA -eq 1 ]; then
  # Look at what's actually installed
  if command -v ollama >/dev/null; then
    AVAILABLE=$(ollama list 2>/dev/null | awk 'NR>1{print $1}' | head -1 || echo "")
    DEFAULT_MODEL_FOR_SETTINGS="${AVAILABLE}"
  fi
fi

# Merge — preserve any user changes if settings already exist
python3 - <<PYEOF
import json, os
settings_file = "${SETTINGS_FILE}"
default_model = "${DEFAULT_MODEL_FOR_SETTINGS}"

defaults = {
    "default_model": default_model,
    "temperature": 0.7,
    "top_p": 0.9,
    "num_ctx": 4096,
    "system_prompt": "",
    "auto_start_ollama": True,
    "stop_ollama_on_quit": False,
    "agent_mode_default": False,
    "confirm_all_commands": True,
    "theme": "mocha",
    "wrap_messages": True,
    "show_token_count": False,
}
if os.path.exists(settings_file):
    try:
        with open(settings_file) as f:
            existing = json.load(f)
        # Only set default_model if it isn't set or points to a missing model
        if not existing.get("default_model") and default_model:
            existing["default_model"] = default_model
        # Fill in any keys missing since last install
        for k, v in defaults.items():
            existing.setdefault(k, v)
        out = existing
    except Exception:
        out = defaults
else:
    out = defaults

os.makedirs(os.path.dirname(settings_file), exist_ok=True)
with open(settings_file, "w") as f:
    json.dump(out, f, indent=2)
print(f"  default_model = {out.get('default_model') or '(none — pick one in app)'}")
PYEOF
ok "settings written to ${SETTINGS_FILE}"

# ── 9. Final summary ──────────────────────────────────────────────

step "done"
echo
echo "  Open your app grid and click ${G}Oracle${X}."
echo "  Or run from a terminal:  ${G}oracle${X}"
echo

if ! echo ":${PATH}:" | grep -q ":${BIN_DIR}:"; then
  warn "${BIN_DIR} is not in your PATH (terminal users only — the .desktop entry works either way)"
  echo "      Add to ~/.bashrc or ~/.zshrc:"
  echo "        export PATH=\"\$HOME/.local/bin:\$PATH\""
  echo
fi

echo "  ${D}Update:    re-run this script${X}"
echo "  ${D}Uninstall: $0 --uninstall${X}"
echo
