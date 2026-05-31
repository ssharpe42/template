"""One-time per-node copy of a rank/node's shard to local NVMe.

With file-level sharding, a node only ever needs its own slice of the dataset
(~ ``total / num_nodes``), which fits in local NVMe for any multi-node job. We
copy those Parquet files **once** at startup and read them locally for every
epoch. Copying the *same* files byte-for-byte is neither a format conversion nor
a reshard, so it respects the project constraints, and it avoids re-streaming
the shard from S3 on each of many epochs.

The copy is idempotent (safe to re-run after a container restart / on resume):
a file already present with the right size is skipped.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Sequence

import fsspec

StorageOptions = Optional[Dict[str, object]]

_DEFAULT_MARGIN = 10 * 1024 ** 3  # keep 10 GiB free for checkpoints/OS scratch


def local_name(remote_path: str) -> str:
    """Deterministic, collision-resistant local filename for a remote path."""

    digest = hashlib.sha1(remote_path.encode()).hexdigest()[:16]
    base = os.path.basename(remote_path.split("://")[-1]) or "file.parquet"
    return f"{digest}_{base}"


def estimate_total_bytes(remote_files: Sequence[str], storage_options: StorageOptions = None) -> int:
    total = 0
    for path in remote_files:
        fs, p = fsspec.core.url_to_fs(path, **(storage_options or {}))
        total += int(fs.size(p))
    return total


def cache_files_to_local(
    remote_files: Sequence[str],
    local_dir: str,
    storage_options: StorageOptions = None,
    max_workers: int = 8,
    check_space: bool = True,
    free_margin_bytes: int = _DEFAULT_MARGIN,
) -> Dict[str, str]:
    """Copy ``remote_files`` into ``local_dir``; return ``{remote: local}``.

    Raises ``RuntimeError`` if the shard plus a safety margin would not fit in
    the free space at ``local_dir`` (i.e. the operator chose too few nodes).
    """

    os.makedirs(local_dir, exist_ok=True)

    if check_space:
        need = estimate_total_bytes(remote_files, storage_options)
        free = shutil.disk_usage(local_dir).free
        if need + free_margin_bytes > free:
            raise RuntimeError(
                f"Insufficient local space at {local_dir}: shard needs ~{need / 1e9:.1f} GB "
                f"+ {free_margin_bytes / 1e9:.1f} GB margin, but only {free / 1e9:.1f} GB free. "
                f"Use more nodes (smaller per-node shard) or switch to streaming."
            )

    def _copy(path: str):
        fs, p = fsspec.core.url_to_fs(path, **(storage_options or {}))
        dst = os.path.join(local_dir, local_name(path))
        size = int(fs.size(p))
        if os.path.exists(dst) and os.path.getsize(dst) == size:
            return path, dst  # idempotent: already cached
        tmp = dst + ".tmp"
        fs.get(p, tmp)
        os.replace(tmp, dst)  # atomic publish so partial copies are never read
        return path, dst

    mapping: Dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for path, dst in ex.map(_copy, list(remote_files)):
            mapping[path] = dst
    return mapping


def node_files(assignment, dist) -> List[str]:
    """Paths owned by all ranks co-located on the same node as ``dist``.

    The cache lives on shared node-local disk, so we copy every file any local
    rank will read, then each rank opens only its own subset.
    """

    first_global = dist.rank - dist.local_rank
    paths: List[str] = []
    for lr in range(dist.local_world_size):
        gr = first_global + lr
        if 0 <= gr < len(assignment):
            paths.extend(fi.path for fi in assignment[gr])
    return paths
