#!/usr/bin/env bash
#
# push.sh — sync local kali files to github.com/the-priest/oracle5
#
# Usage:
#   ./push.sh                    # commit & push (will prompt for message)
#   ./push.sh "your message"     # commit with that message & push
#   ./push.sh --status           # just show what changed
#   ./push.sh --setup            # one-time git init / remote setup
#

set -euo pipefail

# ── colours ──────────────────────────────────────────────────────
if [ -t 1 ]; then
  G="\033[32m"; Y="\033[33m"; R="\033[31m"; B="\033[36m"; X="\033[0m"
else
  G=""; Y=""; R=""; B=""; X=""
fi
say()   { printf "${Y}[*]${X} %s\n" "$*"; }
ok()    { printf "${G}[+]${X} %s\n" "$*"; }
warn()  { printf "${Y}[!]${X} %s\n" "$*"; }
err()   { printf "${R}[!]${X} %s\n" "$*" >&2; }
fatal() { err "$*"; exit 1; }

# ── config ───────────────────────────────────────────────────────
REPO_OWNER="${KALI_OWNER:-the-priest}"
REPO_NAME="${KALI_REPO_NAME:-oracle5}"
SSH_REMOTE="git@github.com:${REPO_OWNER}/${REPO_NAME}.git"
HTTPS_REMOTE="https://github.com/${REPO_OWNER}/${REPO_NAME}.git"
BRANCH="${KALI_BRANCH:-main}"

REQUIRED=(kali.py kali_core.py kali_persona.py install.sh README.md LICENSE)
OPTIONAL=(kali-dragon.svg kali.desktop kali-ollama.service push.sh .gitignore)

# ── pre-flight ───────────────────────────────────────────────────
command -v git >/dev/null || fatal "git not installed (sudo apt install git)"

for f in "${REQUIRED[@]}"; do
  [ -f "$f" ] || fatal "missing required file: $f"
done

# ── modes ────────────────────────────────────────────────────────

if [ "${1:-}" = "--status" ]; then
  git status -sb
  exit 0
fi

setup_repo() {
  if [ ! -d .git ]; then
    say "git init"
    git init -b "${BRANCH}"
  fi
  if ! git remote get-url origin >/dev/null 2>&1; then
    say "adding remote origin → ${SSH_REMOTE}"
    git remote add origin "${SSH_REMOTE}"
  fi
  if [ ! -f .gitignore ]; then
    cat > .gitignore <<EOF
__pycache__/
*.pyc
*.pyo
.venv/
venv/
*.swp
.DS_Store
backups/
*.db
.env
EOF
    ok "wrote .gitignore"
  fi
  ok "repo set up"
}

if [ "${1:-}" = "--setup" ]; then
  setup_repo
  exit 0
fi

# Auto-init if needed
if [ ! -d .git ]; then
  warn "no .git here — running --setup"
  setup_repo
fi

# ── commit message ──────────────────────────────────────────────
MSG="${1:-}"
if [ -z "$MSG" ]; then
  printf "${B}commit message: ${X}"
  read -r MSG
  [ -z "$MSG" ] && MSG="update $(date +%Y-%m-%d)"
fi

# ── stage ───────────────────────────────────────────────────────

# Make sure shell scripts are executable BEFORE staging.  Git tracks
# the executable bit; setting it here means anyone who clones the repo
# (or re-copies files in) gets working scripts without needing chmod.
for f in install.sh push.sh; do
  [ -f "$f" ] && chmod +x "$f"
done

for f in "${REQUIRED[@]}"; do
  git add "$f"
done
for f in "${OPTIONAL[@]}"; do
  [ -f "$f" ] && git add "$f" || true
done

# Pick up deletions of any previously-tracked files (e.g. old oracle*).
git add -u

# Also explicitly tell git these scripts are executable, in case the
# bit got stripped by a cp from another filesystem before staging.
git update-index --chmod=+x install.sh 2>/dev/null || true
git update-index --chmod=+x push.sh    2>/dev/null || true

if git diff --cached --quiet; then
  warn "no staged changes"
  exit 0
fi

git status -s
echo

git commit -m "$MSG"
ok "committed: $MSG"

# ── push: SSH first, HTTPS fallback ─────────────────────────────
say "pushing to ${BRANCH}…"
if git push -u origin "${BRANCH}" 2>/dev/null; then
  ok "pushed via SSH"
else
  warn "SSH push failed — trying HTTPS"
  git remote set-url origin "${HTTPS_REMOTE}"
  if git push -u origin "${BRANCH}"; then
    ok "pushed via HTTPS"
  else
    fatal "push failed.  Check credentials.  Remote stays on HTTPS now."
  fi
fi

echo
ok "live at: https://github.com/${REPO_OWNER}/${REPO_NAME}"
echo "  install on phone:  curl -fsSL https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/${BRANCH}/install.sh | bash"
