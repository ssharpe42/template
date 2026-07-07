# Testing strategy

## Contents
- What to test (and what not to)
- Layout and naming
- The bug-fix loop (test first)
- Writing good tests: patterns
- Fixtures and conftest.py
- Parametrization and markers
- Mocking policy
- Coverage policy
- Speed: keeping the suite fast
- Flaky tests

## What to test (and what not to)

- Test **behavior through public interfaces**, not private implementation. A test that breaks when you rename a private helper without changing behavior is a liability.
- Priority order: (1) core business logic and algorithms, (2) edge cases and error paths, (3) integration seams (DB, HTTP, filesystem), (4) regression tests for every bug fixed.
- Don't test the framework, the standard library, or trivial getters. Don't chase 100% coverage — chase confidence.
- Every new feature ships with tests in the same PR. Every bug fix ships with a test that failed before the fix.

## Layout and naming

```
src/myproject/billing/invoice.py
tests/billing/test_invoice.py        # mirrors src structure
tests/conftest.py                    # shared fixtures
```

- Test names describe the scenario and expectation: `test_refund_rejects_amount_exceeding_original_charge`, not `test_refund_2`. A reader should understand the requirement from the name alone.
- Group related cases in a class (`class TestRefund:`) when a module tests several units; otherwise flat functions are fine. Follow whichever style the repo already uses.
- Structure each test as **Arrange / Act / Assert** — one behavior per test, ideally one logical assertion (multiple `assert` lines on one result object are fine).

## The bug-fix loop (test first)

Follow this order strictly — it turns every bug into a permanent regression guard:

1. Write a test that reproduces the bug. Run it. **Confirm it fails for the reported reason** (not an import error or fixture typo).
2. Fix the code with the minimal change.
3. Run the test — it passes. Run the surrounding suite — nothing else broke.
4. Commit test and fix together: `fix(billing): reject refunds exceeding original charge`.

If you can't reproduce the bug in a test, say so explicitly in the PR rather than shipping an unverified fix.

## Writing good tests: patterns

```python
def test_invoice_total_applies_percentage_discount() -> None:
    # Arrange
    invoice = Invoice(lines=[Line(amount=Decimal("100.00"))], discount_pct=10)
    # Act
    total = invoice.total()
    # Assert
    assert total == Decimal("90.00")
```

- Prefer real objects over mocks; prefer `tmp_path` over patching the filesystem; prefer fakes over `MagicMock`.
- Compare whole values (`assert result == expected_obj`) rather than field-by-field where equality is defined — failures show the full diff.
- Use `pytest.raises` with `match=` to pin the error *and* its message contract:

```python
with pytest.raises(RefundError, match="exceeds original charge"):
    invoice.refund(Decimal("200.00"))
```

- For numeric work use `pytest.approx`; never `==` on floats.
- For invariant-heavy pure functions (parsers, serializers, math), consider property-based tests with `hypothesis` — but only if the repo already depends on it or the team agrees to add it.

## Fixtures and conftest.py

- Fixtures express *required state*, factories express *variation*. A fixture that takes ten parameters should be a factory function instead.
- Put fixtures at the narrowest useful scope: test file first, `tests/conftest.py` only when genuinely shared. A giant root conftest is a code smell.
- Use `scope="session"` only for expensive immutable resources (containers, compiled artifacts); mutable session-scoped fixtures cause order-dependent tests.
- Clean up with `yield` fixtures, not `addfinalizer` gymnastics:

```python
@pytest.fixture
def db(tmp_path: Path) -> Iterator[Database]:
    database = Database(tmp_path / "test.db")
    database.migrate()
    yield database
    database.close()
```

## Parametrization and markers

```python
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1h30m", timedelta(hours=1, minutes=30)),
        ("90m", timedelta(minutes=90)),
        ("0s", timedelta()),
    ],
    ids=["hours-and-minutes", "minutes-only", "zero"],
)
def test_parse_duration(raw: str, expected: timedelta) -> None:
    assert parse_duration(raw) == expected
```

- Declare custom markers in `pyproject.toml` (`--strict-markers` makes typos fail loudly):

```toml
[tool.pytest.ini_options]
markers = [
    "slow: takes >5s, excluded from default runs",
    "integration: requires external services",
]
```

- Default local run excludes slow/integration (`-m "not slow and not integration"` in a Makefile target); CI runs everything.

## Mocking policy

- Mock at **system boundaries only**: network, clock, randomness, subprocesses, third-party APIs. Mocking your own domain logic couples tests to implementation.
- Patch where the name is *used*, not where it's defined: `mocker.patch("myproject.billing.invoice.now")`, not `myproject.utils.time.now`.
- Inject the clock/UUID/randomness as a parameter when designing new code — code that needs no patching is better than well-patched code.
- Every mocked contract should have at least one integration test somewhere proving the real thing matches.

## Coverage policy

- Enforce a floor in `pyproject.toml` (`fail_under`) and CI; never lower it to make a PR pass. Ratchet it up when it's comfortably exceeded.
- Use `branch = true` — statement coverage alone hides untested `else` paths.
- Review the coverage report for *your changed files* before pushing: `uv run pytest --cov --cov-report=term-missing`. New logic with uncovered branches needs either a test or a stated reason in the PR.

## Speed: keeping the suite fast

A slow suite stops getting run, and a suite that isn't run is decoration.

- Parallelize: `uv run pytest -n auto` (pytest-xdist). Tests must be independent — no shared mutable globals, no fixed ports/paths (use `tmp_path`, ephemeral ports).
- While iterating: `uv run pytest tests/test_x.py -k case -x` and `--lf` (rerun last failures).
- Keep unit tests sub-second; push anything slower behind the `slow`/`integration` markers.

## Flaky tests

A flaky test is a P1 maintenance item, not background noise:

1. Reproduce with `uv run pytest tests/test_x.py --count 50` (pytest-repeat) or `-p randomly` if the repo uses pytest-randomly.
2. Usual suspects: real time/sleeps (inject a clock), test-order coupling (leaked global state), real network, timezone/locale assumptions, dict/set ordering assumptions.
3. If it can't be fixed today, mark it `@pytest.mark.xfail(strict=False, reason="flaky: issue #NNN")` **and file the issue** — never delete it silently, never let the team normalize red CI.
