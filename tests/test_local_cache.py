import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from s3parquet_ddp.common import FileInfo
from s3parquet_ddp.local_cache import (
    cache_files_to_local,
    estimate_total_bytes,
    local_name,
    node_files,
)


def _write_parquet(path, n_rows):
    pq.write_table(pa.table({"x": list(range(n_rows))}), path)


def test_local_name_is_deterministic_and_unique():
    a = local_name("s3://b/dir1/f.parquet")
    b = local_name("s3://b/dir2/f.parquet")
    assert a == local_name("s3://b/dir1/f.parquet")
    assert a != b  # same basename, different path -> different cache name
    assert a.endswith("f.parquet")


def test_cache_copies_and_is_idempotent(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    files = []
    for i in range(3):
        p = src / f"f{i}.parquet"
        _write_parquet(str(p), 5 + i)
        files.append(str(p))

    dst = tmp_path / "cache"
    mapping = cache_files_to_local(files, str(dst), check_space=False)
    assert len(mapping) == 3
    for remote, local in mapping.items():
        assert pq.read_table(local).num_rows == pq.read_table(remote).num_rows

    # Second run is a no-op (idempotent): same mapping, files untouched.
    mtimes = {local: __import__("os").path.getmtime(local) for local in mapping.values()}
    mapping2 = cache_files_to_local(files, str(dst), check_space=False)
    assert mapping2 == mapping
    for local, mtime in mtimes.items():
        assert __import__("os").path.getmtime(local) == mtime


def test_cache_raises_when_space_insufficient(tmp_path):
    p = tmp_path / "f.parquet"
    _write_parquet(str(p), 10)
    huge_margin = 10 ** 18  # force the space check to fail
    with pytest.raises(RuntimeError):
        cache_files_to_local([str(p)], str(tmp_path / "c"),
                             check_space=True, free_margin_bytes=huge_margin)


def test_estimate_total_bytes(tmp_path):
    p = tmp_path / "f.parquet"
    _write_parquet(str(p), 10)
    assert estimate_total_bytes([str(p)]) > 0


class _Dist:
    def __init__(self, rank, local_rank, local_world_size):
        self.rank = rank
        self.local_rank = local_rank
        self.local_world_size = local_world_size


def test_node_files_collects_all_local_ranks():
    # world of 4 ranks, 2 per node. Node 1 holds ranks 2 and 3.
    asg = [
        [FileInfo("r0", 1)],
        [FileInfo("r1", 1)],
        [FileInfo("r2", 1)],
        [FileInfo("r3", 1)],
    ]
    dist = _Dist(rank=3, local_rank=1, local_world_size=2)
    files = node_files(asg, dist)
    assert set(files) == {"r2", "r3"}
