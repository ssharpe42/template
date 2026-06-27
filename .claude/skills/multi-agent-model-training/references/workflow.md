# Workflow — Actor + Judge loop for a model-training change

This is the step-by-step the orchestrator (you, the main agent) runs. The goal is
to keep the *doing* and the *judging* in separate contexts so the agent that wants
the run to succeed isn't the one deciding whether it's safe to launch.

## 0. Frame the request

State, in one or two lines, what's being asked and what could go wrong. Examples:

- "Add a cosine LR schedule and re-run the 7B fine-tune." → can launch an
  expensive run, can overwrite checkpoints.
- "Clean up old experiment artifacts." → can delete checkpoints/datasets.
- "Wire up a hyperparameter sweep." → can fan out into many paid runs at once.

If nothing in the request can spend money, move data, or destroy an artifact, you
probably don't need the full loop — but check `action-risk-classes.md` first; the
dangerous step is often hidden inside an innocuous-sounding task.

## 1. Design (Architect — read-only)

Spawn an `Explore` or `Plan` subagent, or use plan mode. Its job:

1. Read the repo: training entrypoint, config system (Hydra / YAML / argparse /
   `accelerate`/`deepspeed` configs), dataset loaders, checkpoint + logging paths,
   eval harness, launcher (sbatch / `torchrun` / Ray / k8s / cloud job).
2. Learn the conventions: where checkpoints go, how runs are named, how configs
   are composed, what the existing dry-run / smoke-test path is.
3. Produce a **plan** and an explicit **action list**, each action tagged with a
   risk class from `action-risk-classes.md` and, for gated actions, a rough
   **cost/blast-radius estimate**.

The Architect must not edit files or run training. Read-only keeps the design
honest and prevents "I'll just kick it off to see" mistakes during planning.

Output shape:

```
PLAN
- step 1: ...
- step 2: ...

ACTIONS
- [safe]  edit configs/train.yaml: add lr_scheduler block
- [gated] launch fine-tune: torchrun ... configs/train.yaml  (~6 GPU-hr, writes ckpts/run_042)
- [gated] overwrite ckpts/best.pt with new best                (irreversible)
```

## 2. Implement (Implementer — read-write)

Work the plan top to bottom. For each action, branch on its class:

- **Safe / reversible** (edit code, write a *new* config, create a branch, run a
  unit test, `--dry-run`): do it, then add a one-line entry to the run log.
- **Gated** (anything that spends, moves data, or overwrites/deletes an artifact):
  **do not run it.** Instead, assemble an **action proposal** and hand it to the
  Judge. Keep working on non-gated steps while the verdict is pending if you can.

### Action proposal format

```
ACTION PROPOSAL
intent:        why this action advances the task
command:       the exact command / code that would run (verbatim)
risk_class:    from action-risk-classes.md
cost_estimate: GPU-hours / $ / wall-clock, and what it consumes
blast_radius:  what it writes/overwrites/deletes; who/what else depends on it
reversible:    yes / no — and if yes, how to undo it
rollback:      the concrete undo (or "none — irreversible")
safeguards:    dry-run done? step cap? new output path? spend limit? checkpoint first?
```

Be honest in `cost_estimate` and `blast_radius` — the Judge can only be as good as
the proposal. Understating cost to get an `allow` is exactly the self-policing
failure this skill exists to prevent.

## 3. Judge (separate context)

Send the proposal to a **fresh** reviewer — either a separate subagent primed with
the Judge prompt (`agent-roles.md`) or the programmatic judge (`templates/judge.py`).
The Judge applies the rubric (`judge-rubric.md`) and returns:

```
VERDICT: allow | allow-with-conditions | block | escalate
reasons: ...
conditions: ...        # if allow-with-conditions
required_changes: ...  # if block
```

Handle the verdict:

- **allow** → run the action. Capture the outcome. Log proposal + verdict + result.
- **allow-with-conditions** → satisfy every condition first (e.g. run the 10-step
  dry run, set `--max-steps`, point `--output-dir` at a fresh path), then run.
- **block** → revise per `required_changes` and re-submit, or drop the action.
  Never override a block silently.
- **escalate** → stop and bring the human in with `AskUserQuestion`, including the
  Judge's reasoning and the cost/blast-radius. Wait for the decision; record it.

## 4. Record

Append a row to the run log (`templates/run-log.md`) for every gated action:
proposal, verdict, conditions, outcome, and (for runs) the run ID / checkpoint
path / cost actually consumed. This is the trail that turns "the agent went off
the rails" into "here's exactly what was proposed, judged, and run."

## Worked example

> Request: "Try a higher LR on the 7B fine-tune and keep the best checkpoint."

1. **Architect** maps: config in `configs/sft_7b.yaml`, launcher `scripts/train.sh`
   → `torchrun`, checkpoints to `ckpts/`, best tracked at `ckpts/best.pt`, eval via
   `scripts/eval.sh`. Actions: edit config `[safe]`; smoke test 10 steps `[safe]`;
   full run `[gated, ~6 GPU-hr → ckpts/sft_7b_lr3e4/]`; promote to `best.pt`
   `[gated, irreversible overwrite]`.
2. **Implementer** edits the config (new file path, not in place), runs the
   10-step smoke test — passes. Reaches the full run; builds a proposal
   (cost ~6 GPU-hr, writes a **new** run dir, reversible by deletion). Sends to Judge.
3. **Judge** → `allow-with-conditions`: "new output dir is good; confirm the
   smoke test passed and cap `--max-steps` to the planned budget so a config typo
   can't run unbounded." Implementer confirms, adds the cap, runs.
4. Run finishes. Implementer proposes promoting to `best.pt`. **Judge** → `escalate`:
   "overwriting `best.pt` is irreversible and `best.pt` is consumed by the serving
   pipeline; a human should confirm the new checkpoint actually wins on eval first."
   Implementer runs eval, then asks the human via `AskUserQuestion` with the eval
   delta. Everything logged.

Note where the judge earned its keep: not on the routine run, but on the one
irreversible, production-touching step the actor would have been tempted to just do.
