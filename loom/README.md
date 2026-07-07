# Loom

**Many agents, one memory.**

Loom is an agentic operating layer for a transformer-training repository. It turns a
directory of Claude Code sessions — each one amnesiac, ephemeral, and isolated — into a
single continuous engineering organism: any fresh session can orient itself in under a
minute, pick up exactly where the last one left off, delegate work to a roster of
specialized agents, and leave the shared memory richer than it found it.

It is the "grand version" of a single orchestration skill. Where a skill tells one
session how to run one workflow, Loom gives the *repo itself* a nervous system:

| Layer | What it is | Where it lives |
|---|---|---|
| **Memory** | Git-versioned shared brain: hot state, codebase atlas, append-only ledger, decision records, run journal, a *growing* silent-failure catalog | `context/` |
| **Roster** | Eight typed agents with distinct powers, tool restrictions, and output contracts | `.claude/agents/` |
| **Rituals** | Workflow skills every session runs: orient → work → handoff, plus the flagship training-change pipeline, mapping, and postmortems | `.claude/skills/` |
| **Reflexes** | Hooks that fire automatically — every session boots with the current state injected into context before the first user message | `.claude/settings.json` + `.claude/hooks/` |

## The problem this solves

Three compounding failure modes plague agentic work on training code:

1. **Session amnesia.** Every fresh session re-explores the repo from zero, re-derives
   decisions that were already made, and steps on in-flight work it can't see.
2. **Context pollution.** One session that reads 200 files to plan a change has no
   room left to implement it carefully — and an implementer that reviews its own code
   approves its own bugs.
3. **Silent failure.** Training code fails invisibly: tests pass and loss looks fine
   while the model trains on leaked validation data, skips gradient sync on rank 3, or
   evals an uncompiled graph. "It runs" is not evidence of correctness.

Loom answers each: memory defeats amnesia, the roster's isolation defeats pollution
(the author is never the approver; scouts absorb exploration cost so the orchestrator
stays lean), and the tiered-verification + adversary pipeline defeats silence.

## Quickstart

```bash
# Install the overlay into your training repo
./install.sh /path/to/your/training/repo

# Then, in a Claude Code session inside that repo:
/orient            # bootstrap from shared memory — the first act of every session
/map               # build the codebase atlas (first time, or after big changes)
/training-change   # make a change through the full multi-agent pipeline
/handoff           # write state for the next session — the last act of every session
/postmortem        # after a bad training run, extract the lesson into memory
```

The `overlay/` directory is exactly what lands in your repo: `.claude/` (agents,
skills, hooks, settings) plus `context/` (seed memory). The installer never clobbers
memory you've already accumulated.

## The session lifecycle

Every session, no matter what it's for, follows the same arc:

```
 SessionStart hook injects context/STATE.md automatically
        │
        ▼
   /orient ── read state, ledger tail, atlas; verify git reality matches memory
        │
        ▼
   work ── directly for trivia; through the roster for anything that touches
        │   data, numerics, training/eval loops, distributed code, or configs
        ▼
   /handoff ── rewrite STATE.md, append the ledger, commit memory
```

A session that ends without `/handoff` is a session that stole context from its
successor. The Stop hook will nag you about it.

## The roster

| Agent | Role | Writes code? | Key constraint |
|---|---|---|---|
| `scout` | Fast read-only recon of one facet of the codebase | No | Reports a map section, never floods the orchestrator |
| `cartographer` | Builds/refreshes the codebase atlas (`context/MAP.md`) | Only `MAP.md` | Atlas must stay under budget — it's a map, not a mirror |
| `planner` | Turns intent into acceptance criteria, tests, plan, risk register | No | Criteria are written *before* implementation exists |
| `implementer` | Executes the approved plan, tests-first | Yes | Scope = the plan, nothing else; deviations surfaced, never buried |
| `verifier` | Runs tiered verification, reports facts | No | Reports evidence, never verdicts |
| `code-reviewer` | Correctness, scope, readability review | No | Independent of the implementer's context |
| `ml-adversary` | Hunts the failure that passes every test | No | Assumes the change is wrong; consults the failure catalog |
| `historian` | Writes ledger entries, decision records, run journal, state | Only `context/` | Memory stays accurate, bounded, and honest |

The one invariant that must never bend: **the agent that wrote a change never signs
off on it.**

## Why git is the memory store

No vector DB, no external service, no daemon. Memory is markdown in the repo because:

- **It travels with the code.** Clone the repo, get the brain. Branches carry the
  memory state that matches the code state.
- **It's auditable.** `git log context/LEDGER.md` is the history of every decision.
- **It's merge-friendly.** The ledger is append-only; STATE.md is small and rewritten
  whole; conflicts are rare and trivially resolvable.
- **Agents already speak it.** Reading a file costs nothing; no retrieval
  infrastructure to break or to poison.

## Self-improvement loop

The system gets smarter with use. Two feedback edges make knowledge compound:

1. Every real finding by the `ml-adversary`, and every `/postmortem` root cause,
   is appended to `context/failures/catalog.md` — which is exactly the document the
   adversary and planner read on the *next* change. Today's incident is tomorrow's
   pre-flight check.
2. Every landed change updates the atlas and the ledger, so the next session's
   scouts start from what's known instead of re-deriving it.

## Repository layout of this framework

```
loom/
├── README.md                  ← you are here
├── install.sh                 ← copies overlay/ into a target repo, non-destructively
├── docs/
│   └── ARCHITECTURE.md        ← design principles and the reasoning behind them
└── overlay/                   ← exactly what lands in the target repo
    ├── CLAUDE.md              ← the router every session reads first
    ├── .claude/
    │   ├── settings.json      ← SessionStart + Stop hooks
    │   ├── hooks/
    │   │   ├── session-start.sh
    │   │   └── stop-reminder.sh
    │   ├── agents/            ← the roster (8 agents)
    │   └── skills/
    │       ├── orient/
    │       ├── handoff/
    │       ├── map/
    │       ├── postmortem/
    │       └── training-change/
    │           └── references/verification.md
    └── context/               ← seed memory
        ├── STATE.md           ← hot handoff state (rewritten every session)
        ├── MAP.md             ← codebase atlas (owned by cartographer)
        ├── LEDGER.md          ← append-only history of changes & decisions
        ├── decisions/         ← architecture decision records
        ├── runs/              ← training-run journal
        └── failures/
            └── catalog.md     ← the growing silent-failure catalog
```
