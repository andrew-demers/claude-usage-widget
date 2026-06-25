#!/bin/bash
# Regenerate the Claude Code usage widget from local transcripts and push to
# GitHub Pages. Run by launchd daily; safe to run by hand anytime.
set -euo pipefail

PY=/opt/homebrew/bin/python3
GH=/opt/homebrew/bin/gh
GIT=/usr/bin/git
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
GH_USER=andrew-demers
GH_REPO=claude-usage-widget
COMMIT_EMAIL="${GH_USER}@users.noreply.github.com"

cd "$REPO_DIR"

"$PY" generate.py --out .

"$GIT" add -A
if "$GIT" diff --cached --quiet; then
  echo "$(date -u +%FT%TZ) no changes, skipping push"
  exit 0
fi

"$GIT" -c user.name="$GH_USER" -c user.email="$COMMIT_EMAIL" \
  commit -m "chore: refresh usage stats $(date -u +%FT%TZ)"

# Push with the personal account's token explicitly, so this works regardless
# of which gh account is currently "active".
TOKEN="$("$GH" auth token --user "$GH_USER")"
"$GIT" push "https://${GH_USER}:${TOKEN}@github.com/${GH_USER}/${GH_REPO}.git" HEAD:main

echo "$(date -u +%FT%TZ) pushed"
