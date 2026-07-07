---
name: orient
description: >-
  Bootstrap a fresh session from Loom's shared memory: load the hot state, ledger
  tail, and atlas summary, verify that git reality matches recorded memory, and
  report what's in flight. Run this as the FIRST act of every session in this repo,
  and whenever resuming after a long pause or a context compaction.
---

# Orient

You are one session in a relay. This skill turns you from amnesiac to informed in
under a minute, and — critically — catches the case where memory and reality have
drifted apart, which is the most dangerous state to work in.

Run the steps inline (no subagents — orientation must be cheap).

## Steps

1. **Load hot state.** Read `context/STATE.md` in full (the SessionStart hook may
   have injected it already — still treat the file as the source of truth). If it's
   missing, memory is uninitialized: say so, offer to run `/map` and create seed
   state, and stop here.

2. **Load recent history.** Read the last 3–5 entries of `context/LEDGER.md` (tail
   of the file — it's append-only). Read the "Orientation in 60 seconds" section of
   `context/MAP.md` if it exists; note its `Last refreshed` commit.

3. **Verify memory against git reality.** Check each claim STATE.md makes:
   - Branch: does `git rev-parse --abbrev-ref HEAD` match the branch STATE names?
   - In-flight work: if STATE says work is in flight, does `git status` /
     `git log` show corresponding uncommitted changes or commits? If STATE says
     clean, is the tree actually clean?
   - Atlas freshness: how many commits between MAP.md's recorded HEAD and current
     HEAD (`git rev-list --count <sha>..HEAD`)? Flag if large (>~30) or if recent
     commits touch subsystems the atlas describes.

4. **Report.** Give the user a compact orientation:
   - Current goal and in-flight work (from STATE), one line each.
   - Next action STATE prescribes.
   - Live gotchas.
   - **Any mismatch between memory and git reality, prominently.** A mismatch means
     a prior session ended without `/handoff` or the branch changed under us — ask
     the user which side is truth before acting on either. Never silently trust
     STATE over git, or git over STATE.
   - Whether the atlas needs a `/map` refresh.

5. **Proceed.** If the user already gave a task, continue into it with this context.
   Otherwise offer the next action from STATE as the default.

## Rules

- Orientation is read-only: fix nothing, update no memory. Mismatches are reported,
  not repaired (repair happens via `/handoff` once truth is established).
- Keep the report under ~15 lines. Orientation that takes longer to read than to
  skip will get skipped.
