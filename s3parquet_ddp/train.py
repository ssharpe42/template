"""End-to-end entrypoint wiring manifest -> assignment -> cache -> Trainer.

Launch with torchrun, e.g.::

    torchrun --nnodes=$NNODES --nproc-per-node=$NGPU \
        -m s3parquet_ddp.train --config configs/example.yaml

The heavy pieces (model, collator, metric, forward_fn) are intentionally left as
hooks for the caller -- this module owns the *data + distribution* plumbing, not
the modelling choices.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional, Sequence

from .assignment import balanced_assignment, steps_per_epoch
from .common import dist_env
from .config import RunConfig
from .local_cache import cache_files_to_local, local_name, node_files
from .manifest import build_manifest, load_manifest
from .stream import build_eval_iter, make_hf_build_fn
from .streaming_trainer import log_rank_files, make_streaming_trainer

logger = logging.getLogger("s3parquet_ddp")


def _ensure_manifest(path: str, data, storage_options):
    """Build the manifest on the global main rank; everyone else loads it."""

    import fsspec

    fs, p = fsspec.core.url_to_fs(path, **(storage_options or {}))
    dist = dist_env()
    if dist.is_global_main and not fs.exists(p):
        logger.info("Building manifest at %s", path)
        build_manifest(data, path, storage_options=storage_options)
    _barrier()
    return load_manifest(path, storage_options=storage_options)


def _barrier():
    try:
        import torch.distributed as dist

        if dist.is_available() and dist.is_initialized():
            dist.barrier()
    except Exception:  # pragma: no cover - single process / no torch
        pass


def prepare_rank_files(cfg: RunConfig) -> Sequence[str]:
    """Manifest -> fixed assignment -> (optional) local cache -> this rank's paths."""

    dist = dist_env()
    infos = _ensure_manifest(cfg.manifest_path, cfg.train_data, cfg.storage_options)
    assignment = balanced_assignment(infos, dist.world_size, strategy=cfg.assignment_strategy)
    my_remote = [fi.path for fi in assignment[dist.rank]]

    if not cfg.cache_to_local:
        log_rank_files(dist.rank, my_remote, logger)
        return my_remote

    # Node-local copy (only local-main copies; the rest wait, then map paths).
    if dist.is_local_main:
        cache_files_to_local(
            node_files(assignment, dist),
            cfg.local_cache_dir,
            storage_options=cfg.storage_options,
            max_workers=cfg.cache_max_workers,
            check_space=cfg.cache_check_space,
        )
    _barrier()

    import os

    my_local = [os.path.join(cfg.local_cache_dir, local_name(p)) for p in my_remote]
    log_rank_files(dist.rank, my_local, logger)
    return my_local


def build_trainer(
    cfg: RunConfig,
    *,
    model,
    data_collator=None,
    compute_metrics: Optional[Callable] = None,
    eval_dataset=None,
    training_args_overrides: Optional[dict] = None,
):
    """Assemble a ready-to-run ``StreamingTrainer`` from ``cfg`` and a model."""

    from transformers import TrainingArguments

    dist = dist_env()
    infos = load_manifest(cfg.manifest_path, storage_options=cfg.storage_options)
    assignment = balanced_assignment(infos, dist.world_size, strategy=cfg.assignment_strategy)
    steps_epoch, per_rank = steps_per_epoch(
        assignment, cfg.per_device_train_batch_size, cfg.grad_accum_steps
    )
    max_steps = steps_epoch * cfg.num_epochs
    logger.info(
        "steps/epoch=%d (per-rank min=%d max=%d) -> max_steps=%d",
        steps_epoch, min(per_rank), max(per_rank), max_steps,
    )

    rank_files = prepare_rank_files(cfg)
    build_fn = make_hf_build_fn(
        storage_options=cfg.storage_options if not cfg.cache_to_local else None,
        shuffle_buffer=cfg.shuffle_buffer,
        columns=cfg.columns,
    )

    args_kwargs = dict(
        output_dir=cfg.output_dir,
        per_device_train_batch_size=cfg.per_device_train_batch_size,
        gradient_accumulation_steps=cfg.grad_accum_steps,
        max_steps=max_steps,
        dataloader_num_workers=cfg.dataloader_num_workers,
        dataloader_pin_memory=cfg.pin_memory,
        # Belt-and-suspenders: do not let accelerate dispatch/broadcast batches.
        accelerator_config={"dispatch_batches": False},
    )
    args_kwargs.update(training_args_overrides or {})
    training_args = TrainingArguments(**args_kwargs)

    return make_streaming_trainer(
        rank_files=rank_files,
        build_iter_fn=build_fn,
        base_seed=cfg.base_seed,
        model=model,
        args=training_args,
        data_collator=data_collator,
        compute_metrics=compute_metrics,
        eval_dataset=eval_dataset,
    )


def evaluate_exact(
    cfg: RunConfig,
    *,
    model,
    forward_fn: Callable,
    device,
    metric_fn: Callable,
):
    """Run the exact, no-duplicate distributed eval and return the metric dict."""

    from .distributed_eval import run_distributed_eval

    dist = dist_env()
    eval_manifest = cfg.eval_manifest_path or cfg.manifest_path
    infos = load_manifest(eval_manifest, storage_options=cfg.storage_options)
    assignment = balanced_assignment(infos, dist.world_size, strategy=cfg.assignment_strategy)
    my_eval = [fi.path for fi in assignment[dist.rank]]

    build_fn = make_hf_build_fn(
        storage_options=cfg.storage_options,
        shuffle_buffer=0,  # exact pass, no shuffle
        columns=cfg.columns,
    )
    eval_iter = build_eval_iter(my_eval, build_fn, seed=cfg.base_seed)
    all_pred, all_label = run_distributed_eval(model, eval_iter, forward_fn, device)
    return metric_fn(all_pred, all_label)
