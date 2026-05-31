import pyarrow as pa
import pyarrow.parquet as pq

from s3parquet_ddp.manifest import build_manifest, list_parquet_files, load_manifest


def _write_parquet(path, n_rows, row_group_size=None):
    table = pa.table({"x": list(range(n_rows)), "y": [i * 2 for i in range(n_rows)]})
    pq.write_table(table, path, row_group_size=row_group_size or n_rows)


def test_build_and_load_manifest(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    sizes = {"a.parquet": 10, "b.parquet": 25, "c.parquet": 7}
    for name, n in sizes.items():
        _write_parquet(str(data_dir / name), n)

    manifest_path = str(tmp_path / "manifest.parquet")
    infos = build_manifest(str(data_dir), manifest_path)

    by_name = {fi.path.split("/")[-1]: fi for fi in infos}
    assert by_name["a.parquet"].num_rows == 10
    assert by_name["b.parquet"].num_rows == 25
    assert by_name["c.parquet"].num_rows == 7

    # Reload from disk and confirm round-trip.
    reloaded = load_manifest(manifest_path)
    assert sum(fi.num_rows for fi in reloaded) == 42
    assert {fi.path for fi in reloaded} == {fi.path for fi in infos}


def test_row_group_count_recorded(tmp_path):
    p = tmp_path / "rg.parquet"
    _write_parquet(str(p), 100, row_group_size=25)  # -> 4 row groups
    manifest_path = str(tmp_path / "m.parquet")
    infos = build_manifest([str(p)], manifest_path)
    assert infos[0].num_row_groups == 4


def test_list_parquet_files_glob(tmp_path):
    for name in ["one.parquet", "two.parquet"]:
        _write_parquet(str(tmp_path / name), 3)
    (tmp_path / "ignore.txt").write_text("nope")
    found = list_parquet_files(str(tmp_path / "*.parquet"))
    assert len(found) == 2
    assert all(f.endswith(".parquet") for f in found)
