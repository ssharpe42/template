# Verification tiers

The ladder the verifier climbs, cheapest first. Each tier answers a different
question; passing a lower tier is never evidence for a higher one. The Change Plan
selects which tiers apply; the verifier runs them and reports facts.

Prerequisite: the repo should have a **tiny config** — same code path as real
training but pocket-sized (tiny model, tiny batch, ~50–200 steps, CPU or single
GPU, seconds to run). If none exists, creating one is a training-change of its own
and one of the best investments in the repo.

## Tier 0 — Static: "does it even load?"

- Import every touched module (`python -c "import <mod>"` or the repo's equivalent).
- Type-check and lint the touched files with the repo's configured tools.
- Instantiate the config(s) the change affects; config systems fail at parse time or
  never.

## Tier 1 — Unit: "does it do what the plan says in isolation?"

- Run the plan's acceptance tests (written in Implement, before/alongside the code).
- Run the existing test files nearest the change (same module/package), then the
  broader suite if it's cheap.
- Record exact counts: passed/failed/skipped, plus the command.

## Tier 2 — Smoke: "does training still train?"

Run a short training on the tiny config and assert, mechanically:

- Loss is finite at every step (no NaN/inf), and decreases over the window (compare
  mean of first N/4 steps vs last N/4 — don't eyeball).
- Gradients flow: no parameter with `requires_grad=True` has `grad is None` after
  the first backward; global grad-norm is finite and nonzero.
- Shapes and dtypes at the model boundary match what the plan expects — print and
  check, don't assume.
- Checkpoint save fires if the window includes one, and the file is loadable.

## Tier 3 — Equivalence: "did the refactor change behavior?" (behavior-preserving only)

The reference trace is captured **at Plan time, before any code changes**:

```bash
# determinism preamble (adapt to the repo's own seeding utility if it has one)
export PYTHONHASHSEED=0 CUBLAS_WORKSPACE_CONFIG=:4096:8
# in the run: seed python/numpy/torch(+cuda), torch.use_deterministic_algorithms(True),
# cudnn.benchmark=False, DataLoader with fixed generator + worker_init_fn
python train.py --config configs/tiny.yaml --seed 1234 --steps 50 \
  --log-loss-file /tmp/loom-ref-trace.jsonl
```

At Verify time: rerun the identical command on the changed code and compare
step-by-step loss.

- Default tolerance: `max |Δloss| ≤ 1e-5` (fp32 tiny config). Any op-reordering the
  plan *intended* (e.g. fused kernels) must be declared there with its justified
  looser tolerance — a tolerance chosen after seeing the diff is a rationalization.
- **A refactor that changes the loss curve at fixed seed is a bug until proven
  otherwise.** "The new curve also looks fine" is not proof.
- Also diff: parameter count, initial loss (step 0 catches init/data changes), and
  final optimizer state norms if cheap.

## Tier 4 — Overfit-a-batch: "can the model still learn?" (model/loss/optimizer changes)

Learning can break with no error and a plausible-looking loss. The classic check:

- Take ONE batch from the real pipeline; train on it repeatedly (a few hundred
  steps, LR at the config default or slightly higher, no regularization/dropout if
  easily disabled).
- PASS: loss drives toward ~zero (or task-appropriate floor — e.g. near-zero CE for
  a memorizable batch). FAIL: loss plateaus well above the floor → gradients,
  masking, labels, or the update rule are silently broken.
- Record the loss curve (first, min, last, step of min), not just the verdict.

## Reporting discipline

- Every tier row carries the exact command and observed numbers. "Matched the
  trace" is not a report; "max |Δloss| = 3.2e-7 over 50 steps, tol 1e-5" is.
- SKIPPED always carries the reason (no tiny config, tier not selected, blocked by
  earlier failure).
- If determinism is in doubt, run twice and report both — a trace that doesn't
  reproduce against itself can't referee an equivalence check.
