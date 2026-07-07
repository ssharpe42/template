---
name: training-change
description: >-
  Orchestrate the Loom multi-agent pipeline for changing transformer training code
  (model, data pipeline, training loop, distributed setup, configs, eval). Use for
  any modification, refactor, feature, optimization, or bugfix touching the data
  path, loss, optimizer, LR schedule, mixed precision, DDP/FSDP, grad accumulation,
  torch.compile, checkpointing, logging, or eval — even when the user just says
  "change X" or "fix the training bug", because training code fails silently: tests
  pass and loss looks fine while the model trains on leaked data. The pipeline puts
  an independent adversary and tiered verification between a change and the next
  training run.
---

# Training Change

The flagship Loom pipeline. Core premise: in a training repo, "it runs and the loss
looks reasonable" is not evidence of correctness. A change can leak validation data,
break gradient sync across ranks, silently downcast, or feed an uncompiled model to
the eval loop — and every test still passes. This workflow puts an independent
adversary and a tiered verification layer between a change and the next training run.

## Who runs what

You are the **orchestrator**. You own all state, sequence the phases, hold the
gates, and never edit code yourself once the roster takes over. Every worker is a
named agent from `.claude/agents/` — spawn them with the Agent tool by name; each
agent's definition carries its own brief structure and output contract, so your
spawn prompt supplies only the *inputs* its definition says it needs. This isolation
is the point: the reviewers must not share the implementer's context and
rationalizations, and scouts exploring a 200-file repo must not flood your window.

**The author-is-not-the-approver invariant:** the agent that wrote a change never
signs off on it. If you're tempted to skip a reviewer because the implementer
"already checked" — that is precisely the failure this pipeline exists to prevent.

**Memory is a participant.** The pipeline reads shared memory going in (atlas for
scouts, failure catalog for planner and adversary, ledger for prior decisions) and
writes it coming out (historian at Land). Skipping the memory steps makes the next
change more expensive and the next review blinder.

## Phase 0 — Intake (orchestrator, no subagent)

1. **Classify:** behavior-preserving (refactor, perf, cleanup) vs. behavior-changing
   (feature, bugfix, hyperparameter/algorithm change). This decides whether the
   equivalence tier applies.
2. **Right-size:** a one-line typo, docstring, or comment — do it directly, skip to
   Land. Reserve the pipeline for anything touching the data path, numerics, the
   training/eval loop, distributed code, or configs feeding them. When in doubt,
   run it: the pipeline costs minutes; a silently-wrong training run costs hours of
   GPU plus a poisoned checkpoint.
3. **Frame the intent** in one or two sentences: what should be true after this
   change that isn't true now. Ambiguity that changes the implementation gets one
   sharp question now, not a discovered fork in Review.

State classification and plan-of-attack to the user, then proceed.

## Phase 1 — Orient (scouts, parallel)

Spawn 1–3 **scout** agents in parallel, each on one facet (data pipeline / training
loop / configs & entrypoints), each with the intent and the relevant `context/MAP.md`
section. Scouts verify the atlas rather than re-deriving it, and return map sections
you merge into one **Codebase Map**. Forward their "Atlas corrections" to the next
`/map` refresh (note in STATE gotchas at handoff).

Small, local change → one inline exploration; don't spawn three agents to map two
files.

## Phase 2 — Plan (planner) — GATE 1

Spawn the **planner** with the intent, classification, and merged Codebase Map. It
consults `context/failures/catalog.md` and the ledger itself, and returns the
**Change Plan**: acceptance criteria → acceptance tests → implementation plan →
verification-tier selection (including the reference-trace command for
behavior-preserving changes) → risk register → open questions.

If the plan selects Tier 3, **capture the reference trace now**, before any code
changes — run the exact command the plan specifies and save the loss trace.

**GATE 1:** present the plan to the user (or, for routine changes, confirm it
yourself against the intent). Resolve open questions. No code until the plan is
approved — wrong plans are cheap here and expensive after implementation.

## Phase 3 — Implement (implementer)

Spawn the **implementer** with the approved plan and Codebase Map. Tests first, then
edits, scope limited to the plan; it returns the Implementation Report (diff summary,
criterion→code map, deviations, test results). If it reports the plan wrong or
infeasible, you return to Phase 2 — never forward to Verify on an improvised design.

## Phase 4 — Verify (verifier)

Spawn the **verifier** with the diff and the plan's tier selection (plus the
reference trace location if Tier 3 applies). It runs the tiers from
`references/verification.md` in order and returns the Verification Report — facts
and evidence per tier, no judgments. You and the reviewers decide what failures mean.

## Phase 5 — Review (code-reviewer ∥ ml-adversary) — GATE 2

Spawn **code-reviewer** and **ml-adversary** in parallel — independent, fresh
context, neither wrote the code. Each gets the diff, the plan, and the Verification
Report. The reviewer audits correctness, plan adherence, scope, and test quality;
the adversary loads the failure catalog and attacks along the risk register and
beyond, returning CONFIRMED/SUSPECTED/CLEARED with evidence.

**GATE 2:** both must APPROVE. Any REQUEST CHANGES → carry the findings back to
Phase 3 (re-implement → re-verify → re-review the affected axes). Do not let an
implementer rebut a reviewer into submission; address the finding, change the plan,
or escalate to the user to accept a documented risk. SUSPECTED adversary findings
with a cheap probe get the probe run before the gate closes.

## Phase 6 — Land (orchestrator + historian)

1. Spawn the **historian** with the landed change's title, intent, diff summary,
   verification evidence, reviewer verdicts, and any NEW catalog entries the
   adversary drafted. It appends the ledger entry, lands catalog entries, and
   updates STATE.md.
2. Commit code and memory with a message that makes the trail auditable: what
   changed and why, the acceptance criteria, which tiers ran and their results,
   reviewer sign-offs. Anyone debugging a training run later should see not just
   the diff but the evidence it was safe. Open a PR only if the user asked for one.
3. If the change restructured anything the atlas describes, queue a `/map` refresh.

## Reference files

- `references/verification.md` — the tiers in detail: determinism setup, reference-
  trace capture, overfit-a-batch procedure, tolerances.
- `context/failures/catalog.md` — the silent-failure catalog (lives in memory, not
  in this skill, so it grows): planner builds risk registers from it, adversary
  attacks with it, historian extends it.
