"""Build and load a Parquet file manifest using footer-only reads.

The manifest records, for every file in the dataset, its exact row count and
row-group count. These come from the Parquet **footer**, so building the
manifest transfers only a few KB per file rather than the row data -- cheap even
across thousands of 10 TB-scale files.

The manifest is written once to shared storage (e.g. EFS) and read by every
rank, so all ranks agree on the file set and row counts without each performing
its own S3 ``LIST`` (which would race / differ).

Everything is routed through ``fsspec`` so the same code works for ``s3://``,
local paths, and EFS mounts.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Sequence, Union

import fsspec
import pyarrow as pa
import pyarrow.parquet as pq

from .common import FileInfo

StorageOptions = Optional[Dict[str, object]]


def _protocol(fs) -> str:
    proto = fs.protocol
    return proto[0] if isinstance(proto, (list, tuple)) else proto


def _to_url(fs, path: str) -> str:
    """Re-attach the protocol so paths are unambiguous when stored/reloaded."""

    proto = _protocol(fs)
    if "://" in path or proto in ("file", "local"):
        return path
    return f"{proto}://{path}"


def list_parquet_files(path_or_glob: str, storage_options: StorageOptions = None) -> List[str]:
    """List parquet files under a prefix, a glob, or return a single file."""

    fs, _ = fsspec.core.url_to_fs(path_or_glob, **(storage_options or {}))
    if any(ch in path_or_glob for ch in "*?["):
        paths = fs.glob(path_or_glob)
    elif fs.isdir(path_or_glob):
        paths = fs.glob(path_or_glob.rstrip("/") + "/**/*.parquet")
    else:
        paths = [path_or_glob]
    return sorted(_to_url(fs, p) for p in paths)


def _read_footer(path: str, storage_options: StorageOptions) -> FileInfo:
    fs, p = fsspec.core.url_to_fs(path, **(storage_options or {}))
    with fs.open(p, "rb") as f:
        md = pq.ParquetFile(f).metadata
    return FileInfo(path=path, num_rows=md.num_rows, num_row_groups=md.num_row_groups)


def build_manifest(
    data_files: Union[str, Sequence[str]],
    manifest_path: str,
    storage_options: StorageOptions = None,
    max_workers: int = 16,
) -> List[FileInfo]:
    """Read footers for every file and write a manifest to ``manifest_path``.

    ``data_files`` may be a prefix/glob string or an explicit list of paths.
    Returns the list of :class:`FileInfo`, sorted by path for determinism.
    """

    if isinstance(data_files, str):
        paths = list_parquet_files(data_files, storage_options)
    else:
        paths = list(data_files)
    if not paths:
        raise ValueError(f"No parquet files found for {data_files!r}")

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        infos = list(ex.map(lambda p: _read_footer(p, storage_options), paths))
    infos.sort(key=lambda fi: fi.path)
    write_manifest(infos, manifest_path, storage_options)
    return infos


def write_manifest(
    infos: Sequence[FileInfo],
    manifest_path: str,
    storage_options: StorageOptions = None,
) -> None:
    table = pa.table(
        {
            "path": [fi.path for fi in infos],
            "num_rows": [fi.num_rows for fi in infos],
            "num_row_groups": [fi.num_row_groups for fi in infos],
        }
    )
    fs, p = fsspec.core.url_to_fs(manifest_path, **(storage_options or {}))
    parent = p.rsplit("/", 1)[0] if "/" in p else ""
    if parent:
        fs.makedirs(parent, exist_ok=True)
    with fs.open(p, "wb") as f:
        pq.write_table(table, f)


def load_manifest(manifest_path: str, storage_options: StorageOptions = None) -> List[FileInfo]:
    fs, p = fsspec.core.url_to_fs(manifest_path, **(storage_options or {}))
    with fs.open(p, "rb") as f:
        table = pq.read_table(f)
    d = table.to_pydict()
    return [
        FileInfo(path=path, num_rows=int(nr), num_row_groups=int(nrg))
        for path, nr, nrg in zip(d["path"], d["num_rows"], d["num_row_groups"])
    ]
