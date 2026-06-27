# Gated-action run log

One row per gated action (anything that spent budget, moved data, or
overwrote/deleted an artifact). This is the audit trail: what was proposed, how it
was judged, and what actually happened. Copy this file into the experiment dir and
append as you go.

| When | Action (intent) | Command | Risk | Cost est. | Verdict | Conditions / changes | Outcome (run id, ckpt path, cost actual) |
|------|-----------------|---------|------|-----------|---------|----------------------|------------------------------------------|
| 2026-06-27 14:02 | Smoke-test new LR config | `torchrun ... --max-steps 10` | safe | ~1 min | (n/a — safe) | — | passed, no nan |
| 2026-06-27 14:10 | Fine-tune 7B, higher LR | `torchrun --nproc_per_node=8 train.py configs/sft_7b_lr3e4.yaml` | gated | ~6 GPU-hr → ckpts/sft_7b_lr3e4/ | allow-with-conditions | smoke passed; added `--max-steps 4000`; new output dir | run_042, ckpts/sft_7b_lr3e4/, ~5.8 GPU-hr |
| 2026-06-27 16:30 | Promote new ckpt to best.pt | `cp ckpts/sft_7b_lr3e4/step_4000.pt ckpts/best.pt` | gated (irreversible) | trivial | escalate → human approved | eval delta +0.4 → human OK'd; backed up old best.pt → best_prev.pt first | best.pt updated, prev archived |

## Columns

- **When** — timestamp.
- **Action (intent)** — one line: what and why.
- **Command** — the exact command run (verbatim).
- **Risk** — safe / gated, and whether it's irreversible.
- **Cost est.** — GPU-hours / $ / wall-clock, and what it writes.
- **Verdict** — allow / allow-with-conditions / block / escalate (+ who approved an escalation).
- **Conditions / changes** — safeguards applied, or required changes for a block.
- **Outcome** — run id, checkpoint path, actual cost, result. Note rollbacks if any.
