# `s3parquet_ddp` — multi-node DDP training over uneven S3 Parquet shards

Train a PyTorch model with the HuggingFace `Trainer` under multi-node DDP,
reading directly from Parquet on S3 — **without** converting, repartitioning, or
landing the full dataset on any single node.

## Why this exists

- Data is up to **10 TB** of Parquet on S3; each node has only ~**7 TB** NVMe.
- No format conversion, no repartition/reshard allowed.
- Files are partitioned `N % world_size == 0` but have **uneven row counts**.
- The HF/accelerate defaults for iterable datasets are pathological at scale:
  `IterableDatasetShard` makes *every* rank read all 10 TB; `dispatch_batches=True`
  makes rank 0 read everything and broadcast.

**Key insight:** with file-level sharding no node needs the whole 10 TB — only
its `≈ 10TB / num_nodes` slice, which fits in NVMe for any multi-node job. So we
assign whole files to ranks, copy each node's slice to local NVMe **once**, and
read locally for every epoch.

## Architecture

| Module | Responsibility |
|---|---|
| `manifest.py` | Footer-only row counts → a shared (EFS) manifest. Cheap; no row data transferred. |
| `assignment.py` | Deterministic, **row-balanced**, **epoch-fixed** file→rank assignment (LPT bin-pack or equal-count "snake"). Plus the DDP step budget. |
| `local_cache.py` | One-time, idempotent per-node copy of the shard to NVMe. |
| `stream.py` | Per-rank streaming `IterableDataset` with file+buffer shuffle and **pad/cycle** so no rank starves the gradient all-reduce. |
| `streaming_trainer.py` | `Trainer` subclass that hands DDP an **already-per-rank** dataloader and bypasses accelerate re-sharding. |
| `distributed_eval.py` | **Exact, no-duplicate** distributed eval via disjoint files + variable-length all-gather. |
| `train.py` | Wires it all together: manifest → assignment → cache → Trainer / eval. |

## How streaming actually reads S3 (not download-to-disk)

`load_dataset("parquet", data_files="s3://...", streaming=True, storage_options=...)`
returns an `IterableDataset` that opens each file lazily through `fsspec`/`s3fs`
and iterates **row groups** via pyarrow — i.e. HTTP **Range GETs**, no caching to
disk. (Plain `load_dataset(...)` *without* `streaming=True` is the one that
downloads.) Here we point the same reader at the **local cached** paths after the
one-time copy.

## Design decisions

- **Coverage = pad/cycle:** every rank runs the same number of `max_steps`
  (sized to the heaviest rank); lighter ranks cycle/oversample. No DDP deadlock.
  Row-balanced assignment keeps the oversampling small.
- **Assignment fixed across epochs:** required so the local NVMe cache stays
  valid. Per-epoch variety comes from file-order + buffer shuffle, not reshuffling
  which node owns which files.
- **Eval is exact:** disjoint eval files ⇒ each row scored once; eval runs under
  `no_grad` so ranks may process unequal counts and we only sync once at the end.
- **Resume is coarse** (epoch/shard boundary); checkpoints live on EFS (NVMe is
  wiped on container reclaim, so resume re-runs the idempotent copy).

## Usage sketch

```python
from s3parquet_ddp.config import RunConfig
from s3parquet_ddp.train import build_trainer, evaluate_exact

cfg = RunConfig(
    train_data="s3://bucket/train/",
    eval_data="s3://bucket/eval/",
    manifest_path="/efs/manifests/train.parquet",
    eval_manifest_path="/efs/manifests/eval.parquet",
    storage_options={"key": ..., "secret": ...},
    local_cache_dir="/mnt/nvme/cache",
    per_device_train_batch_size=8, grad_accum_steps=1, num_epochs=5,
    output_dir="/efs/checkpoints/run",
)

trainer = build_trainer(cfg, model=model, data_collator=collator)
trainer.train()

metrics = evaluate_exact(cfg, model=model, forward_fn=forward_fn,
                         device=device, metric_fn=metric_fn)
```

Launch with `torchrun --nnodes=$N --nproc-per-node=$G -m s3parquet_ddp.train ...`.

## Acceptance gate (the #1 risk)

HF issue #20770 (accelerate re-sharding iterable datasets) has no built-in fix, so
**verify per pinned version**: log the files each rank opens (`log_rank_files`) and
confirm ranks read **disjoint** files and total bytes read ≈ shard size, *not*
`shard × world_size`.

## Tests

```bash
pip install -r s3parquet_ddp/requirements.txt   # torch/transformers optional for the pure-logic tests
python -m pytest tests/ -q
```

The suite covers assignment balance/determinism/divisibility, the step budget,
manifest footer reads, idempotent caching, pad/cycle semantics, and a real
`datasets`-streaming integration that checks pad/cycle and exact disjoint eval over
actual Parquet. The torch/transformers-dependent modules import lazily, so the
suite runs without those heavy packages installed.
