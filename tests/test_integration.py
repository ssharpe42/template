"""End-to-end integration over local Parquet (no torch required).

Exercises the real pipeline: write parquet -> build manifest -> balanced
assignment -> stream via `datasets` -> pad/cycle. This validates that
`datasets` streaming actually reads raw Parquet lazily (here from local files;
the same code path uses s3fs for s3:// URLs).
"""

import pytest

pa = pytest.importorskip("pyarrow")
import pyarrow.parquet as pq  # noqa: E402

pytest.importorskip("datasets")

from s3parquet_ddp.assignment import balanced_assignment, rows_per_rank, steps_per_epoch  # noqa: E402
from s3parquet_ddp.manifest import build_manifest  # noqa: E402
from s3parquet_ddp.stream import (  # noqa: E402
    PadCycleIterableDataset,
    build_eval_iter,
    make_hf_build_fn,
)


def _write(path, start, n):
    pq.write_table(pa.table({"id": list(range(start, start + n))}), path)


def test_full_pipeline_streams_and_pads(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    # 4 uneven files for a world_size of 2.
    sizes = [10, 30, 5, 15]
    start = 0
    for i, n in enumerate(sizes):
        _write(str(data / f"f{i}.parquet"), start, n)
        start += n

    manifest_path = str(tmp_path / "manifest.parquet")
    infos = build_manifest(str(data), manifest_path)
    assert sum(fi.num_rows for fi in infos) == 60

    asg = balanced_assignment(infos, world_size=2, strategy="lpt")
    assert sorted(rows_per_rank(asg)) == [30, 30]  # LPT balances perfectly here

    steps, per_rank = steps_per_epoch(asg, per_device_batch_size=5)
    assert steps == 6 and per_rank == [6, 6]

    # Stream rank 0's files, capped (pad/cycle) to a fixed item budget.
    build_fn = make_hf_build_fn(shuffle_buffer=4, to_torch=False)
    rank0_files = [fi.path for fi in asg[0]]
    ds = PadCycleIterableDataset(rank0_files, build_fn, base_seed=7, max_items=40)
    items = list(iter(ds))
    assert len(items) == 40  # cycled past the 30 real rows -> pad/cycle works
    assert "id" in items[0]


def test_eval_pass_is_exact_and_disjoint(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    sizes = [10, 10, 10, 10]
    start = 0
    all_ids = []
    for i, n in enumerate(sizes):
        _write(str(data / f"e{i}.parquet"), start, n)
        all_ids.extend(range(start, start + n))
        start += n

    manifest_path = str(tmp_path / "m.parquet")
    infos = build_manifest(str(data), manifest_path)
    asg = balanced_assignment(infos, world_size=4, strategy="lpt")

    build_fn = make_hf_build_fn(shuffle_buffer=0, to_torch=False)
    seen = []
    for rank in range(4):
        rank_files = [fi.path for fi in asg[rank]]
        for ex in build_eval_iter(rank_files, build_fn):
            seen.append(int(ex["id"]))

    # Every eval row scored exactly once, no duplicates, full coverage.
    assert sorted(seen) == sorted(all_ids)
    assert len(seen) == len(set(seen))
