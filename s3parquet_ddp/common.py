"""Lightweight shared types and helpers (no heavy dependencies)."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class FileInfo:
    """Metadata for a single Parquet file, read from its footer.

    ``num_rows`` and ``num_row_groups`` come from the Parquet footer, which is
    cheap to read (a few KB at the end of the object) and never requires
    transferring the row data itself.
    """

    path: str
    num_rows: int
    num_row_groups: int = 1


def mix_seed(*parts: int) -> int:
    """Deterministically combine integers into a stable 32-bit seed.

    Used to derive per-epoch / per-cycle shuffle seeds from a base seed so that
    runs are reproducible and every rank agrees on the schedule.
    """

    h = 1469598103934665603  # FNV-1a 64-bit offset basis
    for p in parts:
        # fold signed/large ints into the hash
        x = int(p) & 0xFFFFFFFFFFFFFFFF
        h ^= x
        h = (h * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return h & 0x7FFFFFFF


@dataclass(frozen=True)
class DistInfo:
    rank: int
    world_size: int
    local_rank: int
    local_world_size: int

    @property
    def is_global_main(self) -> bool:
        return self.rank == 0

    @property
    def is_local_main(self) -> bool:
        return self.local_rank == 0


def dist_env() -> DistInfo:
    """Read rank/world-size from the standard torchrun environment variables.

    Falls back to a single-process layout when the variables are unset, so the
    code can run unchanged outside a distributed launcher.
    """

    rank = int(os.environ.get("RANK", "0"))
    world_size = int(os.environ.get("WORLD_SIZE", "1"))
    local_rank = int(os.environ.get("LOCAL_RANK", "0"))
    local_world_size = int(os.environ.get("LOCAL_WORLD_SIZE", "1"))
    return DistInfo(rank, world_size, local_rank, local_world_size)
