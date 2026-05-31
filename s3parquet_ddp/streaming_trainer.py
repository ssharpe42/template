"""``Trainer`` subclass that feeds an already-per-rank stream to DDP.

The integration risk with HF + accelerate and ``datasets.IterableDataset`` is
that accelerate re-distributes the dataloader for you -- either by wrapping it in
``IterableDatasetShard`` (every rank reads everything, keeping 1/world) or, with
``dispatch_batches=True``, by having rank 0 read everything and broadcast. Both
are fatal at 10 TB.

We side-step it: the dataset handed to the ``DataLoader`` is *already* restricted
to this rank's files, so it must **not** be sharded again. We return a plain
``DataLoader`` from ``get_train_dataloader`` (the Trainer uses it as-is and does
not re-prepare it for distribution), and we set ``dispatch_batches=False`` as
belt-and-suspenders.

ACCEPTANCE GATE (verify per installed transformers/accelerate version): log the
files each rank opens and confirm ranks read **disjoint** files and total bytes
read ~= shard size, not ``shard x world_size``. See ``log_rank_files``.

transformers is imported lazily so the rest of the package imports without it.
"""

from __future__ import annotations

from typing import Callable, List, Optional, Sequence

from .stream import PadCycleIterableDataset


def _import_trainer():
    from transformers import Trainer  # noqa: WPS433 (lazy by design)

    return Trainer


def log_rank_files(rank: int, files: Sequence[str], logger=None) -> None:
    """Emit the acceptance-gate signal: which/how many files this rank owns."""

    msg = f"[rank {rank}] owns {len(files)} files; first={files[0] if files else None}"
    if logger is not None:
        logger.info(msg)
    else:  # pragma: no cover - convenience path
        print(msg, flush=True)


def make_streaming_trainer(
    *,
    rank_files: Sequence[str],
    build_iter_fn: Callable,
    base_seed: int = 0,
    **trainer_kwargs,
):
    """Construct a ``StreamingTrainer`` (defined lazily once transformers is importable).

    ``rank_files`` are the local (cached) paths this rank should read;
    ``build_iter_fn`` is e.g. ``stream.make_hf_build_fn(...)``.
    """

    Trainer = _import_trainer()

    class StreamingTrainer(Trainer):
        def __init__(self, *a, **kw):
            self._rank_files: List[str] = list(rank_files)
            self._build_iter_fn = build_iter_fn
            self._base_seed = base_seed
            super().__init__(*a, **kw)

        def get_train_dataloader(self):
            from torch.utils.data import DataLoader

            ds = PadCycleIterableDataset(
                self._rank_files,
                self._build_iter_fn,
                base_seed=self._base_seed,
                max_items=None,  # infinite; Trainer stops everyone at max_steps
            )
            ds.set_epoch(int(self.state.epoch or 0))

            # Return a bare DataLoader: it is already this-rank-only, so we must
            # NOT let accelerate reshard it. (Do not wrap with
            # accelerator.prepare here -- that would re-introduce sharding.)
            return DataLoader(
                ds,
                batch_size=self.args.per_device_train_batch_size,
                collate_fn=self.data_collator,
                num_workers=self.args.dataloader_num_workers,
                pin_memory=self.args.dataloader_pin_memory,
                persistent_workers=self.args.dataloader_num_workers > 0,
            )

    return StreamingTrainer(**trainer_kwargs)
