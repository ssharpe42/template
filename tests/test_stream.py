import pytest

from s3parquet_ddp.stream import PadCycleIterableDataset, pad_cycle_iter


def test_pad_cycle_finite_caps_items():
    out = list(pad_cycle_iter(lambda seed: iter([1, 2, 3]), max_items=7))
    assert out == [1, 2, 3, 1, 2, 3, 1]


def test_pad_cycle_reshuffles_each_cycle_via_seed():
    # build_iter returns a different order depending on seed parity.
    def build(seed):
        return iter([seed % 2, seed % 2 + 10])

    seen = []
    list(pad_cycle_iter(lambda s: build(s), max_items=4, base_seed=1,
                        on_cycle=lambda c: seen.append(c)))
    assert seen == [0, 1]  # two cycles invoked


def test_pad_cycle_empty_shard_raises():
    with pytest.raises(RuntimeError):
        list(pad_cycle_iter(lambda seed: iter([]), max_items=3))


def test_pad_cycle_iter_infinite_is_lazy():
    gen = pad_cycle_iter(lambda seed: iter([1, 2]), max_items=None)
    first = [next(gen) for _ in range(5)]
    assert first == [1, 2, 1, 2, 1]


def test_dataset_cycles_single_worker():
    files = ["a", "b", "c"]

    def build_iter_fn(fs, seed):
        # emit one item per file
        return iter(list(fs))

    ds = PadCycleIterableDataset(files, build_iter_fn, max_items=7)
    out = list(iter(ds))
    assert len(out) == 7
    assert out[:3] == ["a", "b", "c"]


def test_dataset_set_epoch_changes_schedule():
    files = ["a", "b"]
    seeds_seen = []

    def build_iter_fn(fs, seed):
        seeds_seen.append(seed)
        return iter(list(fs))

    ds = PadCycleIterableDataset(files, build_iter_fn, base_seed=0, max_items=2)
    list(iter(ds))
    ds.set_epoch(1)
    list(iter(ds))
    # Different epoch -> different derived seed for the first cycle.
    assert seeds_seen[0] != seeds_seen[-1]
