#!/usr/bin/env bash
# Netlify "ignore" check: exit 0 = skip this build (costs no credits),
# exit 1 = build. Every production deploy costs credits on the Free plan, so
# pushes that only touch docs, tests or CI config are not deployed.
# Builds started by the build hook (autobuild) always run.
if [ -n "${INCOMING_HOOK_TITLE:-}${INCOMING_HOOK_URL:-}" ]; then exit 1; fi
if [ -z "${CACHED_COMMIT_REF:-}" ] || [ "${CACHED_COMMIT_REF}" = "${COMMIT_REF:-}" ]; then exit 1; fi
git diff --quiet "$CACHED_COMMIT_REF" "$COMMIT_REF" -- ascent netlify netlify.toml pyproject.toml
