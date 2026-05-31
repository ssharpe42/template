"""Configuration for an S3-Parquet DDP training run."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class RunConfig:
    # --- data location ---
    train_data: str  # s3:// prefix, glob, or explicit list joined upstream
    eval_data: Optional[str] = None
    manifest_path: str = "/efs/manifests/train_manifest.parquet"  # shared (EFS)
    eval_manifest_path: Optional[str] = None
    storage_options: Dict[str, object] = field(default_factory=dict)  # creds -> s3fs

    # --- local caching ---
    cache_to_local: bool = True
    local_cache_dir: str = "/mnt/nvme/parquet_cache"
    cache_max_workers: int = 8
    cache_check_space: bool = True

    # --- sharding / batching ---
    assignment_strategy: str = "lpt"  # "lpt" (row-balanced) or "snake" (count-balanced)
    per_device_train_batch_size: int = 8
    grad_accum_steps: int = 1
    num_epochs: int = 5
    shuffle_buffer: int = 10_000
    base_seed: int = 0
    columns: Optional[List[str]] = None

    # --- dataloader ---
    dataloader_num_workers: int = 4
    pin_memory: bool = True

    # --- output ---
    output_dir: str = "/efs/checkpoints/run"  # checkpoints on shared storage
