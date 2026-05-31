import pytest

from s3parquet_ddp.assignment import (
    assert_divisible,
    balanced_assignment,
    rows_per_rank,
    steps_per_epoch,
)
from s3parquet_ddp.common import FileInfo


def make_files(rows):
    return [FileInfo(path=f"s3://b/f{i}.parquet", num_rows=n) for i, n in enumerate(rows)]


def test_assert_divisible_ok():
    assert_divisible(8, 4)


@pytest.mark.parametrize("n,w", [(7, 4), (10, 3), (0, 4)])
def test_assert_divisible_raises(n, w):
    with pytest.raises(ValueError):
        assert_divisible(n, w)


def test_lpt_covers_all_files_disjointly():
    files = make_files([10, 20, 30, 40, 50, 60, 70, 80])
    asg = balanced_assignment(files, world_size=4, strategy="lpt")
    paths = [fi.path for rank in asg for fi in rank]
    assert len(paths) == 8
    assert len(set(paths)) == 8  # disjoint, full coverage


def test_lpt_balances_rows_better_than_naive():
    # Uneven sizes: LPT should keep the per-rank row spread small.
    rows = [100, 90, 80, 70, 60, 50, 40, 30]
    asg = balanced_assignment(make_files(rows), world_size=4, strategy="lpt")
    per = rows_per_rank(asg)
    # Perfect balance is 130 each (520/4). LPT achieves it here.
    assert max(per) - min(per) <= 10


def test_snake_gives_equal_file_counts():
    files = make_files([5, 4, 3, 2, 1, 9, 8, 7])
    asg = balanced_assignment(files, world_size=4, strategy="snake")
    counts = [len(r) for r in asg]
    assert counts == [2, 2, 2, 2]


def test_deterministic():
    files = make_files([1, 5, 3, 9, 2, 8, 4, 7])
    a1 = balanced_assignment(files, 4, "lpt")
    a2 = balanced_assignment(list(reversed(files)), 4, "lpt")
    # Order-independent: same input set -> same assignment.
    assert [[fi.path for fi in r] for r in a1] == [[fi.path for fi in r] for r in a2]


def test_steps_per_epoch_uses_max_rank_and_ceil():
    # rank rows: rank0=100, rank1=40 with bs=10 -> steps 10 and 4 -> max 10
    asg = [make_files([100]), make_files([40])]
    steps, per_rank = steps_per_epoch(asg, per_device_batch_size=10, grad_accum_steps=1)
    assert per_rank == [10, 4]
    assert steps == 10


def test_steps_per_epoch_grad_accum():
    asg = [make_files([100])]
    steps, _ = steps_per_epoch(asg, per_device_batch_size=10, grad_accum_steps=2)
    assert steps == 5
