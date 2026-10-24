#!/usr/bin/env bash
# Rebuild the encrypted submissions file from a fresh Forms export (.xlsx or .csv) and publish it.
#   ./update.sh ~/Downloads/export.xlsx [--inactive R5,R6]
set -euo pipefail
cd "$(dirname "$0")"
xlsx="${1:?usage: ./update.sh path/to/export.xlsx}"
uv run tools/build_data.py "$xlsx" "${@:2}"
git add data/submissions.enc.json
if git diff --cached --quiet; then
  echo "No change in the data file."
else
  git commit -q -m "Update submissions $(date +%Y-%m-%d)"
  git push
  echo "Pushed. GitHub Pages redeploys in about a minute; reviewers reload the page."
fi
