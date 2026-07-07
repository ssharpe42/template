# Silent-Failure Catalog

> Failure modes in transformer training that pass every test: nothing errors, loss
> looks plausible, CI is green — and the run is still wrong. The planner builds each
> change's risk register from this file; the ml-adversary uses it as an attack
> playbook; the historian appends new entries from CONFIRMED adversary findings and
> postmortem root causes. **Append-only; never delete an entry.** Seeded entries are
> SF-001…SF-016; repo-specific scar tissue starts at SF-100.

Entry format:

```
## SF-NNN: <name>
- Class: data | masking | precision | rng | distributed | optimizer | compile | checkpoint | eval | logging
- Mechanism: how it happens
- Symptom: what you'd (barely) observe — often "nothing"
- Detection: the concrete probe that exposes it
- Prevention: what a change must do/avoid
- Incidents: seed | <ledger/run references once it bites this repo>
```

---

## SF-001: Validation data leaks into training
- Class: data
- Mechanism: split done after shuffling with an unseeded RNG, split by index on a
  resorted dataset, dedup applied per-split instead of before splitting, or a
  sampler/config change that silently re-includes held-out shards.
- Symptom: eval metrics improve — the failure *rewards* you. Nothing errors.
- Detection: dump the actual example IDs (not indices) drawn by the train sampler
  for an epoch and intersect with the val set; must be empty. Check near-duplicates
  too if the corpus has them.
- Prevention: split by stable content hash or frozen ID list, never by position;
  any change to sampling/splitting re-runs the intersection probe.
- Incidents: seed

## SF-002: Loss mask / label misalignment
- Class: masking
- Mechanism: off-by-one between logits and labels (double-shift or no-shift),
  padding included in the loss, prompt tokens unmasked in SFT, or ignore_index
  mismatch between collator and loss.
- Symptom: loss decreases anyway — the model happily learns the wrong objective.
  Suspiciously low loss (predicting pad) or high floor (shifted targets).
- Detection: for one batch, decode and print token/label/mask triples aligned in
  columns; verify by eye that exactly the intended positions carry loss. Assert
  `loss(batch with all-masked labels)` is NaN/0 as designed.
- Prevention: a unit test that checks mask/label alignment on a crafted mini-batch
  with known answer; never trust "the collator handles it".
- Incidents: seed

## SF-003: Attention mask wrong under padding or packing
- Class: masking
- Mechanism: causal mask correct but padding mask dropped after a refactor;
  sequence packing lets tokens attend across document boundaries; mask dtype/
  additive-vs-boolean convention flipped between components.
- Symptom: none at small scale; degraded quality that looks like a data problem.
- Detection: feed a batch where sequence B is garbage-padded; logits for sequence A
  must be identical with/without B present. For packing: perturb tokens of doc 1
  and assert doc 2's logits unchanged.
- Prevention: keep the invariance probes as tests; any change near attention or
  collation re-runs them.
- Incidents: seed

## SF-004: Silent dtype downcast / upcast
- Class: precision
- Mechanism: a `.to()`, autocast boundary, or buffer init that leaves layernorm/
  softmax/loss in fp16/bf16 when policy says fp32 (or the reverse, silently doubling
  memory); optimizer states created in the wrong dtype after a refactor.
- Symptom: training "works"; instability appears only at scale or late in training.
- Detection: walk the module tree and print param/buffer/activation dtypes at each
  boundary for one forward; diff against the declared precision policy.
- Prevention: an assert-dtypes test pinned to the policy; changes near autocast or
  model init re-run it.
- Incidents: seed

## SF-005: Grad accumulation loss scaling wrong
- Class: optimizer
- Mechanism: loss not divided by accumulation steps (or divided twice), or
  accumulation interacts wrongly with loss reduction ('mean' vs 'sum') after a
  change — effective LR silently multiplied/divided by the accumulation factor.
- Symptom: loss curve plausible; run behaves like a different LR was chosen.
- Detection: fixed seed, compare N steps at accum=1, batch=B against N steps at
  accum=k, microbatch=B/k — parameter updates must match within tolerance.
- Prevention: keep that equivalence as a test; any change to the step loop re-runs it.
- Incidents: seed

## SF-006: Gradient sync silently skipped or doubled (DDP/FSDP)
- Class: distributed
- Mechanism: `no_sync()` scope wrong after refactor, manual all-reduce added on top
  of DDP's, a parameter created outside the wrapped module, or conditional layers
  causing rank divergence (unused-parameter handling).
- Symptom: single-GPU tests all pass; multi-GPU run quietly trains k different
  models or halves gradients.
- Detection: 2-process CPU (gloo) run on the tiny config; after each step assert all
  ranks' parameters are bitwise identical; compare update magnitude against a
  single-process run.
- Prevention: keep the 2-rank parity check runnable on CPU so it's cheap; run it for
  any change touching the step loop, wrapping, or model construction.
- Incidents: seed

## SF-007: Rank-conditional code diverges collective schedules
- Class: distributed
- Mechanism: `if rank == 0:` around code that (transitively) hits a collective, or
  data-dependent control flow that differs across ranks — deadlocks are the *loud*
  version; the silent one is ranks proceeding with different state.
- Symptom: occasional hangs "in logging" or nondeterministic multi-node behavior.
- Detection: grep for rank-conditional branches introduced by the diff; trace
  whether any collective is reachable inside them. 2-rank smoke with timeout.
- Prevention: collectives never inside rank-conditional code; log-only work strictly
  after sync points.
- Incidents: seed

## SF-008: DataLoader workers duplicate augmentation/sampling RNG
- Class: rng
- Mechanism: numpy/python RNG seeded before fork, so every worker applies identical
  "random" augmentation or sampling; or worker_init_fn dropped in a refactor.
- Symptom: effective data diversity silently shrinks; metrics slightly worse, never
  an error.
- Detection: log the first augmentation draw per worker for one epoch; draws must
  differ across workers and across epochs.
- Prevention: worker_init_fn deriving per-worker seeds from (base_seed, worker_id,
  epoch); test asserts the draws differ.
- Incidents: seed

## SF-009: Determinism quietly lost
- Class: rng
- Mechanism: a new op without a deterministic implementation, cudnn.benchmark
  re-enabled, unseeded shuffle added, or set iteration order leaking into batch
  order.
- Symptom: none — until you need to reproduce a run or referee an equivalence check.
- Detection: run the tiny config twice with the same seed; loss traces must match
  bitwise (or within documented tolerance).
- Prevention: the repeat-run check is Tier 3's precondition; keep it green.
- Incidents: seed

## SF-010: torch.compile trains one graph, eval uses another
- Class: compile
- Mechanism: eval path calls the uncompiled module (or vice versa), a dynamic-shape
  recompile silently falls back to eager, or graph breaks split exactly at the
  changed code so the new logic runs eagerly with different numerics.
- Symptom: train/eval metric gap that looks like overfitting; or perf regression
  attributed to "compile being flaky".
- Detection: assert eval consumes the same compiled object as training; run with
  compile debug/logging flags and count graphs/recompiles before vs after the change.
- Prevention: one owner object for the compiled model; changes near the compile
  boundary re-check graph counts.
- Incidents: seed

## SF-011: Eval runs in training mode (or grads on)
- Class: eval
- Mechanism: missing `model.eval()` (dropout active during eval) or missing
  `inference_mode/no_grad` (results fine, memory silently balloons); or eval
  mutates BN/statistics state.
- Symptom: noisy/pessimistic eval metrics; OOMs blamed on batch size.
- Detection: assert `model.training is False` and `torch.is_grad_enabled() is False`
  inside the eval loop, as a test.
- Prevention: the eval entrypoint owns mode/grad state; keep the assertion test.
- Incidents: seed

## SF-012: Checkpoint round-trip loses state
- Class: checkpoint
- Mechanism: optimizer/scheduler/scaler/RNG state or custom buffers not saved (or
  saved but not loaded), key remapping after a rename swallowing mismatches with
  `strict=False`, or dataloader position not restored — resume quietly restarts
  parts of training.
- Symptom: loss spike or subtle LR-schedule reset after resume; often shrugged off
  as "resume noise".
- Detection: train k steps → checkpoint → resume → train k more; compare against
  2k uninterrupted steps at fixed seed — traces must match. Diff state-dict keys
  saved vs loaded.
- Prevention: the resume-equivalence test is mandatory for any checkpoint-adjacent
  change; `strict=False` requires a logged, reviewed allowlist.
- Incidents: seed

## SF-013: LR schedule / warmup silently wrong
- Class: optimizer
- Mechanism: scheduler stepped per-epoch vs per-step after a loop refactor, warmup
  counted in microbatches vs optimizer steps under accumulation, or resume
  restarting warmup (see SF-012).
- Symptom: training works but underperforms; nobody looks at the actual LR curve.
- Detection: log LR every step on the tiny config and diff the curve against the
  intended schedule closed-form.
- Prevention: a test that evaluates the schedule at a handful of known steps.
- Incidents: seed

## SF-014: Metric aggregation lies (distributed or weighted)
- Class: logging
- Mechanism: loss averaged over ranks without weighting by sample count, token-level
  metrics averaged per-batch then per-epoch (Simpson's-paradox style), or a metric
  reset missing so it accumulates across evals.
- Symptom: dashboards show wrong numbers with full confidence; decisions get made
  on them.
- Detection: recompute the metric offline from raw predictions for one eval and diff
  against the logged value.
- Prevention: metric objects owned in one place with tested reduction semantics.
- Incidents: seed

## SF-015: Data ordering/sharding change starves ranks or repeats shards
- Class: data
- Mechanism: shard assignment by `rank * len // world` off-by-one, drop_last
  interacting with uneven shards, or an epoch-boundary shuffle that re-deals some
  files to two ranks and none to others.
- Symptom: throughput fine, loss fine; some data seen twice per epoch, some never.
- Detection: instrument the sampler on tiny config with world=2: union of example
  IDs across ranks == dataset, intersection == empty, per-epoch.
- Prevention: keep the sharding-partition probe as a test parameterized by world
  size.
- Incidents: seed

## SF-016: "Refactor" changes numerics via op reordering
- Class: precision
- Mechanism: reassociating a sum, fusing ops, changing reduction order, or swapping
  einsum for matmul — mathematically identical, floating-point different. Fine when
  intended; a silent behavior change when it rides along in a "pure refactor".
- Symptom: none locally; equivalence with the pre-change trace is broken.
- Detection: Tier 3 reference-trace diff at fixed seed.
- Prevention: numerics-touching reorderings must be declared in the Change Plan with
  a justified tolerance — declared before the diff exists, not rationalized after.
- Incidents: seed

---

<!-- Repo-specific entries (SF-100+) land below this line. Historian: next free ID is SF-100. -->
