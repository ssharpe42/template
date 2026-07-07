---
name: postmortem
description: >-
  Investigate a failed, suspicious, or surprisingly-bad training run, establish the
  root cause with evidence, and bank the lesson into shared memory: a run-journal
  entry, a ledger record, and — for silent failures — a new failure-catalog entry
  that future planners and adversaries will check automatically. Use after loss
  blowups, NaN runs, eval regressions, throughput collapses, or "the numbers look
  wrong but nothing errored".
---

# Postmortem

A training run that fails without a postmortem will fail again. This skill converts
one incident into permanent institutional memory — the second feedback edge of
Loom's self-improvement loop (the first is the adversary's findings).

## Steps

1. **Freeze the evidence.** Before anything is cleaned up or re-run: capture the
   run's config, git sha, seed, launch command, logs, metric curves, and the
   checkpoint lineage. Note wall-clock of the anomaly onset vs. run start.

2. **Build the timeline.** When did the run start, when did metrics go wrong, what
   changed in the repo/config/data between the last good run and this one
   (`git log --stat <good-sha>..<bad-sha>`, config diffs, data-version changes).
   The delta between last-good and first-bad is your search space.

3. **Investigate.** Read `context/failures/catalog.md` first — match symptoms
   against known modes before deriving from scratch. Then hypothesize → probe, in
   order of blast radius (data/masks/labels, then loss/grads/optimizer, then
   precision, then distributed, then infra). For heavy exploration, spawn the
   **ml-adversary** with the diff between last-good and first-bad and the symptom
   description — hunting silent failures is exactly its job.

4. **Demand evidence for the root cause.** A root cause is established when you can
   state: the mechanism, the observation that confirms it, and — gold standard —
   a minimal reproduction or a probe that flips with the fix. "Probably X" goes in
   the record as SUSPECTED, clearly labeled, not dressed up as a conclusion.

5. **Bank the lesson — spawn the historian** with:
   - A run-journal entry for `context/runs/` (use the template there): timeline,
     symptom, root cause + evidence, fix, cost of the incident.
   - A ledger entry referencing it.
   - If the failure was *silent* (nothing errored; tests would have passed): a new
     catalog entry for `context/failures/catalog.md`, generalized into a checkable
     detection + prevention, citing this incident.

6. **Close the loop.** If a code fix is needed, that's a change — route it through
   `/training-change` (the fix for a subtle failure is itself a prime candidate for
   subtle failure). If the failure evaded Gate 2 on a change this system reviewed,
   say so explicitly in the ledger: that's a review-process gap worth a note in the
   catalog entry's detection section.

## Rules

- Postmortems are blameless toward past sessions but merciless toward causes.
- Never let the fix land before the lesson is banked — fixes without recorded causes
  regress.
- One incident, one journal file. Multiple hypotheses may die in it; only one root
  cause (or an explicit UNRESOLVED) comes out of it.
