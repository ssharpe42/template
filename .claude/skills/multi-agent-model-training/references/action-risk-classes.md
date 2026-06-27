# Action risk classes for model-training repos

Default risk class and judge outcome for the actions that show up in training work.
"Default" means the starting point — context can pull an action up or down (a
"delete" of a scratch dir is reversible-ish; a "launch" of a 512-GPU run is not the
same as an 8-GPU smoke test). When in doubt, treat it as the more dangerous class.

## Safe — just do it (and log it)

Reversible, cheap, local, small blast radius.

- Read configs, code, logs, metrics, dataset *samples*, checkpoint *metadata*.
- `git status` / `git diff` / `git log`; create a branch.
- Edit code or write a **new** config file (not overwriting a shared one).
- Run unit tests, linters, type checks.
- Run a **dry-run / smoke test**: `--dry-run`, print-config, 10–50 step run on a
  tiny slice with output to a scratch dir.
- Compute token/cost *estimates* (no spend).

## Gated → allow-with-conditions — run after safeguards

Cheap-ish and mostly reversible, but a safeguard removes the tail risk. The Judge
typically attaches: dry-run done, step/time cap, fresh output path.

- **Launch a training / fine-tuning run** to a new, run-named output dir.
  Conditions: passing smoke test + `--max-steps`/time cap + new path.
- **Download / build a dataset** to a new path (not huge, not paid egress).
  Conditions: size check, new path, checksum if available.
- **Resume from a checkpoint** into a new run dir.
- **Single cloud/GPU job** within a small pre-agreed budget.

## Gated → escalate — a human decides

Irreversible **and** consequential. Default to escalation; do not auto-approve.

- **Overwrite or delete a checkpoint**, especially `best.pt` / `latest/` or
  anything a serving/eval/production path consumes.
- **Push a model to a registry / hub / production artifact store**, or update a
  "production"/"current" pointer.
- **Delete or overwrite a dataset**, or mutate a shared dataset in place.
- **Launch a hyperparameter sweep** or any fan-out that starts many paid jobs at
  once (cost is multiplicative and easy to under-estimate).
- **Spend real money beyond the pre-agreed cap** — large GPU/TPU allocation,
  multi-node run, paid inference for eval/distillation at volume, large egress.
- **Modify a shared/production training pipeline, scheduler, cron, or CI** that
  other people's runs depend on.
- **Anything touching production data or production model serving.**

## Block (regardless of class) — fix and resubmit

- Gated action proposed **without** a cost estimate or blast-radius.
- Full launch **without** a passing dry-run/smoke test.
- In-place overwrite where a new path would do.
- A run **without** a step/time cap when the config could loop or run unbounded.
- Action broader than the stated intent (scope creep).

## Quick heuristics

- **New path > in-place.** Almost every overwrite can be a fresh dir; promotion is
  a separate, escalated step.
- **Multiply before you launch.** Sweep cost = per-run cost × jobs. Estimate it.
- **Smoke test is non-negotiable** before a real run — it's the cheapest possible
  catch for the most common (config) mistakes.
- **"Best"/"prod"/"latest" are tripwires.** Any action naming one is at least
  `escalate` until proven otherwise.
