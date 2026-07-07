# Loom router

This repository runs **Loom**: a multi-agent operating layer with persistent shared
memory. You are one session in a relay; sessions before you left state for you, and
sessions after you depend on the state you leave. Read this section before doing
anything else.

## First and last acts of every session

- **First act:** run `/orient`. It loads the hot state (`context/STATE.md`), the
  ledger tail, and the atlas summary, verifies that git reality matches recorded
  memory, and tells you (and the user) what's in flight. The SessionStart hook
  already injected `STATE.md` — `/orient` completes and verifies the picture.
- **Last act:** run `/handoff` before the session ends or when a work item lands.
  A session that ends without a handoff steals context from its successor.

## Shared memory — where truth lives

| File | What it holds | Who writes it |
|---|---|---|
| `context/STATE.md` | Hot state: current goal, in-flight work, next action, live gotchas | historian (via `/handoff`) |
| `context/LEDGER.md` | Append-only history: changes, decisions, runs, handoffs, with evidence | historian |
| `context/MAP.md` | Codebase atlas: modules, data flow, config surface, landmines | cartographer (via `/map`) |
| `context/decisions/` | Architecture decision records | historian |
| `context/runs/` | Training-run journal | historian |
| `context/failures/catalog.md` | Growing catalog of silent failure modes — the adversary's playbook | historian (adversary/postmortem findings) |

Trust memory but verify: if `STATE.md` claims a branch or in-flight work that git
contradicts, surface the mismatch to the user before acting on either.

## How work gets done

- **Trivial** (typos, docstrings, comments, docs): do it directly, then `/handoff`.
- **Anything touching the data path, numerics, training/eval loop, distributed code,
  or configs that feed them:** run `/training-change`. It orchestrates the roster —
  scouts → planner (Gate 1) → implementer → verifier → code-reviewer ∥ ml-adversary
  (Gate 2) → historian. When in doubt, use it: the pipeline costs minutes, a
  poisoned checkpoint costs a training run.
- **After a bad or suspicious training run:** run `/postmortem`.
- **When the atlas is missing or stale:** run `/map`.

## Invariants — never bend these

1. **The author is never the approver.** The agent that wrote a change never signs
   off on it. If you implemented something inline, you still spawn independent review
   for anything non-trivial.
2. **Only the historian writes `context/LEDGER.md` and `STATE.md`; only the
   cartographer rewrites `context/MAP.md`.** Single-writer memory stays coherent.
3. **The ledger is append-only.** Never edit or delete past entries; correct the
   record with a new entry.
4. **Verification evidence lands with the change.** A landed change without its
   verification trail is an unverified change, whatever actually happened.
5. **In training code, "it runs and loss looks fine" is not evidence of
   correctness.** Consult `context/failures/catalog.md` whenever reasoning about
   what could be silently wrong.
