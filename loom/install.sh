#!/usr/bin/env bash
# Loom installer — copies the overlay into a target repo without clobbering
# memory or configuration the repo has already accumulated.
#
# Usage: ./install.sh /path/to/target/repo
set -euo pipefail

SRC="$(cd "$(dirname "$0")/overlay" && pwd)"
TARGET="${1:?usage: ./install.sh /path/to/target/repo}"

if [ ! -d "$TARGET" ]; then
  echo "error: target '$TARGET' is not a directory" >&2
  exit 1
fi
if [ ! -e "$TARGET/.git" ]; then
  echo "warning: '$TARGET' is not a git repo — Loom's memory works best under git" >&2
fi

copied=0
skipped=0

# Copy every overlay file, skipping any path that already exists in the target.
# Existing memory (context/) and existing agent/skill customizations are sacred.
while IFS= read -r -d '' f; do
  rel="${f#"$SRC"/}"
  dest="$TARGET/$rel"
  if [ -e "$dest" ]; then
    echo "  skip (exists)   $rel"
    skipped=$((skipped + 1))
  else
    mkdir -p "$(dirname "$dest")"
    cp "$f" "$dest"
    echo "  install         $rel"
    copied=$((copied + 1))
  fi
done < <(find "$SRC" -type f -print0)

chmod +x "$TARGET/.claude/hooks/"*.sh 2>/dev/null || true

# If the target already had a CLAUDE.md, ours was skipped — append the Loom
# router section instead so sessions still learn the rituals.
if [ -e "$TARGET/CLAUDE.md" ] && ! grep -q "Loom router" "$TARGET/CLAUDE.md"; then
  {
    echo ""
    echo "<!-- Loom router (appended by loom/install.sh) -->"
    sed -n '/^# Loom router/,$p' "$SRC/CLAUDE.md"
  } >> "$TARGET/CLAUDE.md"
  echo "  append          CLAUDE.md (Loom router section)"
fi

echo ""
echo "Loom installed: $copied files copied, $skipped preserved."
echo "Next: open a Claude Code session in $TARGET and run /orient, then /map."
