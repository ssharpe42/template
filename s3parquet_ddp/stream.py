"""Per-rank streaming dataset with pad/cycle for DDP-balanced training.

Key ideas
---------
* Each rank reads **only its own files** (assigned upstream), so we never pay
  the cost of every rank iterating the whole dataset (the pathology of HF's
  default ``IterableDatasetShard``).
* Files have uneven row counts, so a rank may run out of data before others.
  Under DDP that deadlocks the gradient all-reduce. We make each rank's stream
  **infinite** by cycling, reshuffling on each pass; the ``Trainer`` stops every
  rank together at ``max_steps``. Lighter ranks simply oversample -- the
  "pad/cycle" coverage strategy.
* Reading is lazy and row-group at a time, so memory stays at ~one row group +
  the shuffle buffer; nothing is materialised to disk by the reader.

The :func:`pad_cycle_iter` generator is pure Python and unit-tested without
torch. The torch / ``datasets`` integration is layered on top and imported
lazily so this module is importable without those packages.
"""

from __future__ import annotations

from typing import Callable, Iterable, Iterator, List, Optional, Sequence

from .common import mix_seed

# Torch is optional at import time: fall back to a plain base class and a no-op
# worker-info shim so the pure generator logic is testable without torch.
try:  # pragma: no cover - exercised implicitly when torch is present
    from torch.utils.data import IterableDataset as _TorchIterableDataset
    from torch.utils.data import get_worker_info as _get_worker_info
except Exception:  # pragma: no cover
    _TorchIterableDataset = object  # type: ignore

    def _get_worker_info():  # type: ignore
        return None


def pad_cycle_iter(
    build_iter: Callable[[int], Iterator],
    max_items: Optional[int] = None,
    base_seed: int = 0,
    on_cycle: Optional[Callable[[int], None]] = None,
) -> Iterator:
    """Yield items from ``build_iter`` indefinitely, cycling when exhausted.

    Parameters
    ----------
    build_iter:
        Callable ``seed -> iterator``. Called once per cycle with a fresh,
        per-cycle seed so each pass reshuffles differently.
    max_items:
        Stop after this many items. ``None`` means infinite (the normal training
        case -- the Trainer enforces ``max_steps`` instead).
    base_seed:
        Mixed with the cycle index to derive each cycle's seed.
    on_cycle:
        Optional callback invoked with the cycle index at the start of each pass.

    Raises ``RuntimeError`` if a cycle produces zero items (an empty shard would
    otherwise loop forever).
    """

    emitted = 0
    cycle = 0
    while max_items is None or emitted < max_items:
        if on_cycle is not None:
            on_cycle(cycle)
        seed = mix_seed(base_seed, cycle)
        produced = 0
        for item in build_iter(seed):
            yield item
            emitted += 1
            produced += 1
            if max_items is not None and emitted >= max_items:
                return
        if produced == 0:
            raise RuntimeError(
                "Underlying shard produced no items; cannot pad/cycle an empty "
                "shard. Check the file assignment for this rank."
            )
        cycle += 1


class PadCycleIterableDataset(_TorchIterableDataset):
    """Infinite, reshuffling, worker-sharded view over one rank's files.

    Pass this straight to a ``torch.utils.data.DataLoader``. With
    ``num_workers > 1`` each worker takes a disjoint slice of the rank's files
    so workers don't duplicate reads.
    """

    def __init__(
        self,
        files: Sequence[str],
        build_iter_fn: Callable[[Sequence[str], int], Iterator],
        base_seed: int = 0,
        max_items: Optional[int] = None,
    ) -> None:
        self.files = list(files)
        self.build_iter_fn = build_iter_fn
        self.base_seed = base_seed
        self.max_items = max_items
        self._epoch = 0

    def set_epoch(self, epoch: int) -> None:
        """Advance the shuffle schedule (called by the Trainer between epochs)."""

        self._epoch = int(epoch)

    def _worker_files(self) -> List[str]:
        info = _get_worker_info()
        if info is None:
            return self.files
        return self.files[info.id :: info.num_workers]

    def __iter__(self) -> Iterator:
        files = self._worker_files()
        if not files:
            return iter(())  # extra workers (more workers than files) idle cleanly

        seed_base = mix_seed(self.base_seed, self._epoch)

        def build(seed: int) -> Iterator:
            return self.build_iter_fn(files, seed)

        return pad_cycle_iter(build, max_items=self.max_items, base_seed=seed_base)


def make_hf_build_fn(
    storage_options: Optional[dict] = None,
    shuffle_buffer: int = 0,
    columns: Optional[List[str]] = None,
    to_torch: bool = True,
):
    """Return a ``(files, seed) -> iterator`` backed by ``datasets`` streaming.

    Works identically for local cached paths and ``s3://`` paths: ``datasets``
    opens each file lazily via fsspec and iterates row groups. ``datasets`` is
    imported lazily so this module imports without it.
    """

    def build(files: Sequence[str], seed: int) -> Iterator:
        from datasets import load_dataset

        ds = load_dataset(
            "parquet",
            data_files=list(files),
            streaming=True,
            split="train",
            storage_options=storage_options,
            columns=columns,
        )
        if shuffle_buffer and shuffle_buffer > 0:
            # Shuffles shard (file) order AND fills a local buffer of this size.
            ds = ds.shuffle(buffer_size=shuffle_buffer, seed=seed)
        if to_torch:
            ds = ds.with_format("torch")
        return iter(ds)

    return build


def build_eval_iter(
    files: Sequence[str],
    build_iter_fn: Callable[[Sequence[str], int], Iterator],
    seed: int = 0,
) -> Iterator:
    """Single, exact pass over a rank's eval files (no cycling, no shuffle-cap).

    Eval files are assigned disjointly across ranks, so iterating each rank's
    files exactly once scores every eval row exactly once -- no duplicates.
    """

    return build_iter_fn(files, seed)
