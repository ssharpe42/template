"""DDP training over uneven S3 Parquet shards with the HuggingFace Trainer.

This package implements the data + training plumbing needed to train a PyTorch
model with the HuggingFace ``Trainer`` under multi-node DDP, reading directly
from Parquet files on S3 without converting or resharding them.

Modules
-------
- :mod:`s3parquet_ddp.manifest`        build/load a file->row-count manifest (footer-only reads)
- :mod:`s3parquet_ddp.assignment`      deterministic, balanced file->rank assignment + step budget
- :mod:`s3parquet_ddp.local_cache`     one-time per-node copy of a shard to local NVMe
- :mod:`s3parquet_ddp.stream`          per-rank streaming IterableDataset with pad/cycle
- :mod:`s3parquet_ddp.streaming_trainer`  Trainer subclass that bypasses accelerate re-sharding
- :mod:`s3parquet_ddp.distributed_eval`   exact, no-duplicate distributed evaluation

The pure-logic modules (``manifest``, ``assignment``, ``local_cache`` and the
generator helpers in ``stream``) have no hard dependency on torch/transformers,
so they can be unit-tested in isolation. The torch/transformers/datasets
imports are deferred so importing this package never fails when those (large)
packages are absent.
"""

from .common import FileInfo, mix_seed, dist_env
from .assignment import (
    assert_divisible,
    balanced_assignment,
    rows_per_rank,
    steps_per_epoch,
)

__all__ = [
    "FileInfo",
    "mix_seed",
    "dist_env",
    "assert_divisible",
    "balanced_assignment",
    "rows_per_rank",
    "steps_per_epoch",
]
