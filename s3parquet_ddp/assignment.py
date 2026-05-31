"""Deterministic, balanced file->rank assignment and DDP step budgeting.

The assignment is **fixed across epochs** (it depends only on the file set and
the world layout, not the epoch). This is required so that the one-time
per-node local NVMe cache stays valid for every epoch -- each rank always owns
the same files, so its node only ever needs to download its slice once.

Files have uneven row counts, so we balance by *rows*, not file count, to keep
the per-rank step budget as even as possible and minimise how much the
pad/cycle logic has to oversample the smaller ranks.
"""

from __future__ import annotations

import heapq
import math
from typing import Iterable, List, Sequence, Tuple, Union

from .common import FileInfo

FileLike = Union[FileInfo, Tuple[str, int], Tuple[str, int, int]]


def _coerce(f: FileLike) -> FileInfo:
    if isinstance(f, FileInfo):
        return f
    if isinstance(f, (tuple, list)):
        if len(f) == 2:
            return FileInfo(path=str(f[0]), num_rows=int(f[1]))
        if len(f) == 3:
            return FileInfo(path=str(f[0]), num_rows=int(f[1]), num_row_groups=int(f[2]))
    raise TypeError(f"Cannot interpret {f!r} as a FileInfo")


def assert_divisible(num_files: int, world_size: int) -> None:
    """Fail loudly unless ``num_files`` is divisible by ``world_size``.

    Divisibility is the user's guarantee; without it HF ``split_dataset_by_node``
    falls back to the slow "every rank iterates everything" path. Repartitioning
    to fix it is disallowed, so we surface a clear error instead.
    """

    if world_size <= 0:
        raise ValueError(f"world_size must be positive, got {world_size}")
    if num_files == 0:
        raise ValueError("No parquet files found")
    if num_files % world_size != 0:
        raise ValueError(
            f"Number of parquet files ({num_files}) is not divisible by world_size "
            f"({world_size}); remainder={num_files % world_size}. Repartitioning is "
            f"not allowed -- adjust world_size or the file set so it divides evenly."
        )


def balanced_assignment(
    files: Iterable[FileLike],
    world_size: int,
    strategy: str = "lpt",
) -> List[List[FileInfo]]:
    """Partition ``files`` across ``world_size`` ranks, balancing total rows.

    Parameters
    ----------
    files:
        Iterable of :class:`FileInfo` (or ``(path, num_rows[, num_row_groups])``).
    world_size:
        Total number of ranks (nodes x GPUs-per-node).
    strategy:
        - ``"lpt"`` (default): Longest-Processing-Time greedy bin-packing. Best
          row balance; file counts per rank may differ slightly.
        - ``"snake"``: round-robin in alternating direction over size-sorted
          files. Guarantees an **equal file count** per rank (good for keeping
          ``dataloader_num_workers`` uniform) with decent row balance.

    Returns
    -------
    A list of length ``world_size``; element ``r`` is the list of files owned by
    rank ``r``. The result is deterministic for a given input set.
    """

    infos = [_coerce(f) for f in files]
    assert_divisible(len(infos), world_size)
    # Stable, deterministic ordering: largest first, ties broken by path.
    ordered = sorted(infos, key=lambda fi: (-fi.num_rows, fi.path))
    bins: List[List[FileInfo]] = [[] for _ in range(world_size)]

    if strategy == "lpt":
        # (total_rows, rank) min-heap -> always extend the lightest rank.
        heap = [(0, r) for r in range(world_size)]
        heapq.heapify(heap)
        for fi in ordered:
            total, r = heapq.heappop(heap)
            bins[r].append(fi)
            heapq.heappush(heap, (total + fi.num_rows, r))
    elif strategy == "snake":
        # Equal file count per rank via boustrophedon (snake) round-robin.
        forward = True
        idx = 0
        for fi in ordered:
            bins[idx].append(fi)
            if forward:
                idx += 1
                if idx == world_size:
                    idx = world_size - 1
                    forward = False
            else:
                idx -= 1
                if idx < 0:
                    idx = 0
                    forward = True
    else:
        raise ValueError(f"Unknown strategy {strategy!r}; use 'lpt' or 'snake'")

    return bins


def rows_per_rank(assignment: Sequence[Sequence[FileInfo]]) -> List[int]:
    """Total rows owned by each rank."""

    return [sum(fi.num_rows for fi in b) for b in assignment]


def steps_per_epoch(
    assignment: Sequence[Sequence[FileInfo]],
    per_device_batch_size: int,
    grad_accum_steps: int = 1,
) -> Tuple[int, List[int]]:
    """Compute the per-epoch optimizer-step budget for DDP.

    Every rank must run the **same** number of steps or the gradient all-reduce
    deadlocks. We size the epoch to the *heaviest* rank (``ceil`` so its data is
    fully covered); lighter ranks pad/cycle to reach the same count.

    Returns ``(steps_this_epoch, per_rank_steps)``.
    """

    if per_device_batch_size <= 0:
        raise ValueError("per_device_batch_size must be positive")
    samples_per_step = per_device_batch_size * max(1, grad_accum_steps)
    per_rank = [math.ceil(r / samples_per_step) for r in rows_per_rank(assignment)]
    return (max(per_rank) if per_rank else 0), per_rank
