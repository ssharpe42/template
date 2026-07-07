#!/usr/bin/env bash
# Loom Stop hook — non-blocking nag: if the working tree changed this session but
# the hot state didn't, the next session will boot on stale memory.
set -uo pipefail

command -v git >/dev/null 2>&1 || exit 0
git rev-parse --git-dir >/dev/null 2>&1 || exit 0

changed=$(git status --porcelain 2>/dev/null)
[ -z "$changed" ] && exit 0

if ! echo "$changed" | grep -q 'context/STATE.md'; then
  echo "Loom reminder: the working tree has changes but context/STATE.md was not" \
       "updated. If a work item landed or is being left in flight, run /handoff so" \
       "the next session inherits accurate state."
fi
exit 0
