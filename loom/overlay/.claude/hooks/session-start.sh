#!/usr/bin/env bash
# Loom SessionStart hook — inject the hot state so every session boots oriented.
# stdout from this hook is added to the session's context before the first turn.
set -uo pipefail

echo "=== LOOM: shared memory snapshot (SessionStart) ==="

if [ -f context/STATE.md ]; then
  echo "--- context/STATE.md (hot state) ---"
  cat context/STATE.md
else
  echo "context/STATE.md is missing — memory is uninitialized. Run /orient, then /map."
fi

if [ -f context/LEDGER.md ]; then
  echo ""
  echo "--- last 3 ledger entries (headers) ---"
  grep -nE '^## [0-9]{4}-[0-9]{2}-[0-9]{2}' context/LEDGER.md | tail -n 3 || echo "(no entries yet)"
fi

echo ""
echo "--- git reality check ---"
echo "branch: $(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo 'not a git repo')"
dirty=$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')
echo "uncommitted paths: ${dirty}"

echo ""
echo "Loom rituals: /orient to verify this picture, /handoff before ending."
echo "=== END LOOM SNAPSHOT ==="
exit 0
