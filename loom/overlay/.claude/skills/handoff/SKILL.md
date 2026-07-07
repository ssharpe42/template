---
name: handoff
description: >-
  Write session state back to Loom's shared memory so the next session inherits
  accurate context: rewrite context/STATE.md, append a LEDGER.md entry, and commit
  memory. Run as the LAST act of every session, when a work item lands, before any
  risky operation, and whenever context is about to compact. A session that ends
  without handoff steals context from its successor.
---

# Handoff

The single highest-leverage ritual in Loom: thirty seconds of writing now saves the
next session (which may be you, post-compaction) twenty minutes of re-derivation —
or worse, saves it from acting on stale state.

## Steps

1. **Take stock honestly.** What actually happened this session: what landed, what's
   half-done, what failed, what was decided, what surprised you. Include the
   unflattering parts — a handoff that hides a failed approach condemns the next
   session to repeat it.

2. **Spawn the historian** with a brief containing:
   - Session summary: goal, what was done, evidence for anything claimed done
     (commands run, tests passed, commits made).
   - In-flight work: exact state, including which files are dirty and why.
   - Next action: the single most useful thing for the next session to do first,
     specific enough to start cold ("run tier 2 smoke on tiny.yaml — tier 1 already
     green", not "continue verification").
   - Live gotchas: anything the next session could trip over (a flaky test, a
     temporarily-disabled check, an unmerged dependency).
   - Any decision made that deserves an ADR, any run that deserves a journal entry.

   The historian rewrites `context/STATE.md` (whole-file, ≤80 lines, template
   structure) and appends the ledger entry. For a trivial session where spawning is
   overkill, do the historian's writes yourself following the same rules — the
   single-writer invariant is about *concurrent* ownership, and you inherit the
   role for this step.

3. **Commit memory.** Stage and commit the `context/` changes — together with the
   session's code changes if they land as one unit, or as a standalone
   `memory: handoff — <summary>` commit if not. Memory that isn't committed doesn't
   exist for the next session (fresh clones, other machines). Push if the session's
   branch instructions call for it.

4. **Confirm.** Tell the user in 2–3 lines what state was recorded and what the
   next session will see as its first action.

## Rules

- Never skip the ledger entry, even for "nothing happened" sessions — "explored X,
  concluded not worth doing because Y" is exactly the knowledge that prevents the
  next session from re-exploring X.
- STATE.md describes the present, the ledger records the past. Don't let STATE
  accumulate history — move it to the ledger and keep STATE ≤80 lines.
- If this session discovered a memory/reality mismatch at orient time, this is
  where it gets repaired: record in the ledger what the mismatch was and which side
  was adopted as truth.
