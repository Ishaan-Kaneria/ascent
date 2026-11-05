#!/usr/bin/env bash
# Netlify build: sync real data and render the dashboard into site/.
# --strict fails the build if an API is down, so Netlify keeps the last good deploy.
set -euo pipefail

if [ -z "${CF_HANDLE:-}" ]; then
  echo "CF_HANDLE is empty: set it in netlify.toml or in Netlify's environment variables." >&2
  exit 1
fi

python3 -m pip install --quiet .
export ASCENT_HOME="$PWD/.ascent-build"
mkdir -p "$ASCENT_HOME" site

python3 -m ascent init --cf "$CF_HANDLE" --lc "${LC_HANDLE:-}" --target "${TARGET_RATING:-1600}"

# Optional: commit your ~/.ascent/journal.jsonl to data/ so timers, editorial
# flags and sheet imports show up on the hosted dashboard too.
if [ -f data/journal.jsonl ]; then
  cp data/journal.jsonl "$ASCENT_HOME/journal.jsonl"
  python3 -m ascent sync --rebuild --strict
else
  python3 -m ascent sync --strict
fi
python3 -m ascent dashboard -o site/index.html
