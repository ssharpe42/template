# Loom Architecture

The design principles, in the order they matter.

## 1. Sessions are ephemeral; memory is durable

A Claude Code session is a process: it boots cold, accumulates context, and dies.
Everything a session learns that isn't written to `context/` is lost. Loom therefore
treats the filesystem as the only real state, and sessions as interchangeable workers
that check state out and check it back in.

Concretely:

- **`context/STATE.md`** is the *hot* state — what's in flight right now, what the
  next action is, what gotchas are live. It is small (≤ ~80 lines), rewritten whole at
  every handoff, and injected automatically into every new session by the
  SessionStart hook. A fresh session is productive before its first tool call.
- **`context/LEDGER.md`** is the *cold* state — an append-only log of every landed
  change, decision, run, and handoff, each entry carrying its evidence. Append-only
  means merge conflicts are near-impossible and history is never rewritten.
- **`context/MAP.md`** is the *spatial* state — a codebase atlas maintained by the
  cartographer: modules, data flow, config surface, test coverage, landmines. Scouts
  consult it before exploring so exploration cost is paid once, not per session.
- **`context/decisions/`**, **`context/runs/`**, **`context/failures/`** are the
  deep archives: ADRs, the training-run journal, and the silent-failure catalog.

The split matters. Hot state must be tiny so it can be injected wholesale; cold state
can grow forever because nobody reads it linearly — they grep it.

## 2. Context is a budget, and the orchestrator is the treasury

The main session (the orchestrator) is the only long-lived context in the system, so
its window is the scarcest resource. Every design choice spends it deliberately:

- **Scouts absorb exploration.** Mapping a 200-file blast radius costs the scout its
  own disposable window; the orchestrator receives a bounded map section.
- **Workers get briefs, not transcripts.** Each subagent receives exactly the
  artifacts it needs (intent + map for the planner; plan + map for the implementer;
  diff + plan + report for reviewers) — never the whole conversation.
- **Artifacts are contracts.** Every agent returns a structured document with a fixed
  shape. The orchestrator composes documents; it does not replay reasoning.

## 3. The author is never the approver

An implementer that reviews its own diff approves its own blind spots — it *cannot*
find the bug it just rationalized into existence. So review is structurally
independent: the code-reviewer and ml-adversary are spawned fresh, share none of the
implementer's context, and receive the diff as a hostile document. The adversary's
prior is that the change is wrong; its job is to find the proof.

This is also why the pipeline loops through *re-implementation* rather than letting
an implementer argue a reviewer down: findings are addressed in code or escalated to
the human, never rebutted into silence.

## 4. In training code, "it runs" is not evidence

A training-code change can pass every test while leaking validation data, breaking
gradient sync on one rank, silently downcasting, or evaluating the wrong graph. So
verification is tiered and evidence-based (static → unit → smoke → equivalence →
overfit-a-batch; see `overlay/.claude/skills/training-change/references/verification.md`),
behavior-preserving changes are diffed against a reference loss trace captured
*before* implementation, and a dedicated adversary hunts the failures that tests
can't see, armed with a catalog of exactly those failures.

## 5. Knowledge must compound

A system that makes the same mistake twice has no memory worth the name. Loom closes
two feedback loops:

- **Failure → catalog → prevention.** Confirmed adversary findings and postmortem
  root causes are appended to `context/failures/catalog.md`. The planner reads the
  catalog to build each change's risk register; the adversary reads it as its attack
  playbook. The catalog ships seeded with the classic transformer failure modes and
  grows with the repo's own scar tissue — which is worth more than any generic list,
  because it encodes *this codebase's* specific traps.
- **Change → atlas + ledger → orientation.** Landing a change updates the map and
  appends the ledger, so the next session's `/orient` starts from current truth.

## 6. Rituals beat intentions

Discipline that depends on remembering is discipline that fails. Loom moves the
critical habits into mechanism:

- The **SessionStart hook** injects `STATE.md` and the ledger tail before the first
  user message — orientation happens even if nobody asks for it.
- The **Stop hook** checks whether the working tree changed while memory didn't, and
  nags for a `/handoff` — the one ritual whose omission taxes the *next* session.
- **Gates in the training-change pipeline** are checkpoints the orchestrator may not
  skip: plan approval before code exists (Gate 1), dual independent approval before
  landing (Gate 2).

## 7. Right-size everything

The full pipeline exists for changes that touch the data path, numerics, the
training/eval loop, distributed code, or the configs feeding them. A typo fix takes
the direct path. The orchestrator classifies at intake and states its choice; when in
doubt it runs the machine, because the pipeline costs minutes and a poisoned
checkpoint costs a training run. Same principle for mapping: a two-file change gets
inline exploration, not three scouts.

## Data flow of the flagship pipeline

```
                   ┌────────────────────── ORCHESTRATOR ──────────────────────┐
 intent ──► intake │ classify · right-size · frame                            │
                   │                                                          │
        MAP.md ──► │ scouts (∥) ──► map sections ──► merged Codebase Map      │
                   │                                                          │
   catalog.md ──►  │ planner ──► Change Plan (criteria → tests → edits →      │
                   │             tiers → risk register)         ══ GATE 1 ══  │
                   │                                                          │
                   │ implementer ──► diff + self-report + deviations          │
                   │                                                          │
                   │ verifier ──► Verification Report (facts per tier)        │
                   │                                                          │
                   │ code-reviewer (∥) ml-adversary ──► APPROVE / REQUEST     │
                   │       ▲______________loop on findings______│ ══ GATE 2 ══│
                   │                                                          │
                   │ historian ──► ledger entry · catalog additions ·         │
                   │               STATE.md · MAP.md touch-up      ──► LAND   │
                   └──────────────────────────────────────────────────────────┘
```

## What Loom deliberately does not do

- **No external memory service.** Markdown in git beats a vector store here: it
  branches with the code, merges with the code, and needs zero infrastructure.
- **No always-on daemon.** Reflexes are hooks; everything else is invoked. A system
  you can read end-to-end is a system you can trust and extend.
- **No agent autonomy over memory truth.** Only the historian writes the ledger, only
  the cartographer rewrites the atlas — single-writer ownership keeps memory coherent.
