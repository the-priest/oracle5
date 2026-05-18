#!/usr/bin/env bash
#
# push.sh — push Oracle to github.com/the-priest/oracle5
#
# Prereqs:
#   1. You've created an empty repo at https://github.com/the-priest/oracle5
#      (don't tick "add README" or any starter files — make it empty)
#   2. You have git auth set up — either SSH key (recommended) or a
#      personal access token cached via:  gh auth login
#
# Then just:  ./push.sh
#

set -euo pipefail

USER="the-priest"
REPO="oracle5"
REMOTE_SSH="git@github.com:${USER}/${REPO}.git"
REMOTE_HTTPS="https://github.com/${USER}/${REPO}.git"

Y="\033[33m"; G="\033[32m"; R="\033[31m"; B="\033[36m"; X="\033[0m"
say() { printf "${Y}[*]${X} %s\n" "$*"; }
ok()  { printf "${G}[+]${X} %s\n" "$*"; }
err() { printf "${R}[!]${X} %s\n" "$*" >&2; exit 1; }

# Sanity check — are we in the right folder?
for f in oracle.py oracle_core.py oracle_persona.py install.sh README.md; do
  [ -f "$f" ] || err "missing $f — run this from the oracle/ folder"
done

# init if needed
if [ ! -d .git ]; then
  say "git init"
  git init -b main >/dev/null
fi

# .gitignore (always overwrite — keep it consistent)
cat > .gitignore <<'EOF'
__pycache__/
*.pyc
*.pyo
*.pyd
.DS_Store
*.swp
*.bak
*.orig
backups/
.idea/
.vscode/
EOF

# Configure git user if not set globally
if [ -z "$(git config user.name 2>/dev/null || true)" ]; then
  say "setting local git user (The Priest / no-reply email)"
  git config user.name  "The Priest"
  git config user.email "the-priest@users.noreply.github.com"
fi

# Stage + commit
git add .
if git diff --cached --quiet; then
  ok "nothing to commit"
else
  if [ -z "$(git log --oneline 2>/dev/null | head -1)" ]; then
    git commit -m "Oracle: initial commit" >/dev/null
  else
    git commit -m "Oracle: update" >/dev/null
  fi
  ok "committed"
fi

# Add or update origin — prefer SSH if user has keys, else HTTPS
if git remote get-url origin >/dev/null 2>&1; then
  say "remote 'origin' already configured: $(git remote get-url origin)"
else
  # Try SSH if a key exists
  if [ -f "${HOME}/.ssh/id_ed25519" ] || [ -f "${HOME}/.ssh/id_rsa" ]; then
    git remote add origin "${REMOTE_SSH}"
    ok "added remote (ssh): ${REMOTE_SSH}"
  else
    git remote add origin "${REMOTE_HTTPS}"
    ok "added remote (https): ${REMOTE_HTTPS}"
    say "you'll be prompted for username + token on first push"
    echo "    (use a Personal Access Token, not your password)"
    echo "    create one at: https://github.com/settings/tokens"
  fi
fi

# Push
say "pushing to origin/main"
git branch -M main 2>/dev/null || true
git push -u origin main

echo
ok "pushed to https://github.com/${USER}/${REPO}"
echo
echo "${B}Your one-line install (share anywhere):${X}"
echo
echo "  curl -fsSL https://raw.githubusercontent.com/${USER}/${REPO}/main/install.sh | bash"
echo
