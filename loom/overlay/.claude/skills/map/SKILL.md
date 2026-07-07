---
name: map
description: >-
  Build or refresh the codebase atlas (context/MAP.md) via the cartographer agent.
  Run when the atlas is missing (first Loom session in a repo), when /orient reports
  it stale, after large landed changes, or when scouts report atlas drift. The atlas
  is the shared spatial memory that lets scouts and planners start from what's known
  instead of re-exploring.
---

# Map

The atlas pays exploration cost once so every future session doesn't. This skill
delegates to the **cartographer** — the only agent allowed to rewrite
`context/MAP.md`.

## Steps

1. **Decide build vs. refresh.** Read the current `context/MAP.md` header if the
   file exists. Fresh build if missing or placeholder; refresh otherwise. For a
   refresh, gather the drift signals: scout "Atlas corrections" from recent work,
   `git log --stat <atlas-sha>..HEAD` to see which subsystems changed.

2. **Spawn the cartographer** with:
   - Build or refresh, and for a refresh, the specific drifted areas (so it touches
     only those sections plus the header).
   - Any user hints about subsystems that matter most right now.

   For a very large repo, optionally spawn 2–3 scouts in parallel first (one per
   major subsystem) and hand their map sections to the cartographer to merge —
   scouts explore, cartographer owns the file.

3. **Sanity-check the result.** Skim the new atlas: header updated with today's date
   and current HEAD sha; under ~250 lines; landmines carry file:line anchors;
   "Orientation in 60 seconds" actually orients in 60 seconds.

4. **Commit.** `memory: refresh atlas at <short-sha>` — the atlas is memory, and
   uncommitted memory doesn't exist for the next session. Note the refresh in the
   next handoff's ledger entry rather than writing a separate one.

## Rules

- Never edit MAP.md inline in the main session while the cartographer exists as an
  agent — single-writer ownership is what keeps the atlas coherent. (Exception: a
  one-line landmine addition discovered mid-task may be delegated to the next
  refresh via a note in STATE's gotchas.)
- Don't refresh reflexively on every change — the atlas tolerates small drift, and
  scouts verify-then-correct as they go. Refresh on structural change.
