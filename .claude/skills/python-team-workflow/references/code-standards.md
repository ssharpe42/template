# Code standards

## Contents
- Project layout
- Typing rules
- Docstrings and comments
- API design
- Errors and exceptions
- Logging
- Data modeling
- Dependency discipline
- Deprecation in a multi-developer repo

## Project layout

Use the **src layout** — it prevents accidentally importing the working copy instead of the installed package:

```
myproject/
├── pyproject.toml
├── uv.lock
├── .python-version
├── .pre-commit-config.yaml
├── CLAUDE.md
├── src/myproject/
│   ├── __init__.py          # public API re-exports + __all__
│   ├── py.typed             # marks the package as typed
│   └── billing/
│       ├── __init__.py
│       ├── invoice.py
│       └── _rounding.py     # underscore prefix = internal module
└── tests/
```

- Organize by **domain** (`billing/`, `ingest/`), not by kind (`models/`, `utils/`). A growing `utils.py` is a design failure — give code a named home.
- Underscore-prefix internal modules and names; define the public surface explicitly with `__all__` in `__init__.py`.
- No import-time side effects (network calls, file reads, heavy computation). Importing a module must always be cheap and safe.
- Circular imports mean the boundary is wrong — restructure, don't paper over with function-level imports (acceptable only as a documented last resort).

## Typing rules

- **All new/changed public functions, methods, and module-level variables are fully annotated**, including `-> None`.
- Use modern syntax: `list[str]`, `str | None`, `from collections.abc import Sequence` — not `List`, `Optional`, `typing.Sequence` (ruff `UP` rules enforce this).
- Accept broad, return narrow: take `Sequence[str]`/`Mapping[str, int]` as parameters, return concrete `list`/`dict`.
- `Any` is a last resort and never leaks from a public signature. Prefer `object` + narrowing, `TypeVar`, or `Protocol`.
- Use `Protocol` for duck-typed seams (easy to fake in tests) instead of inheriting abstract base classes across module boundaries.
- Libraries ship `py.typed` so downstream type checkers see the annotations.

## Docstrings and comments

- Docstrings on the public API: what it does, args that aren't self-evident, raised exceptions, and gotchas. Pick one style repo-wide (Google style is the default) and keep it consistent:

```python
def refund(self, amount: Decimal) -> Refund:
    """Refund part or all of a settled invoice.

    Args:
        amount: Refund amount; must not exceed the settled total.

    Raises:
        RefundError: If the invoice is unsettled or amount exceeds the total.
    """
```

- Don't docstring the obvious (`"""Init."""`) — noise trains readers to skip docs.
- Comments explain **why**, never what: constraints, non-obvious tradeoffs, links to issues/specs. If a comment explains *what* the code does, rewrite the code to say it itself.
- `TODO`s carry an owner or issue: `# TODO(#412): remove after v2 migration`. Orphan TODOs get deleted or filed during maintenance.

## API design

- Functions do one thing; if a docstring needs "and", split it.
- Keyword-only arguments (`*,`) for booleans and anything beyond ~3 parameters — call sites stay readable and reorderable.
- No mutable default arguments; default to `None` and normalize inside.
- Prefer returning values over mutating arguments; prefer raising over returning `None`-as-error unless absence is a normal, expected case.
- Pure logic core, effectful shell: keep I/O at the edges so the core is trivially testable.

## Errors and exceptions

- Define a small exception hierarchy per package, rooted in one base:

```python
class BillingError(Exception):
    """Base for all billing errors."""

class RefundError(BillingError): ...
```

  Callers can then catch `BillingError` at boundaries without enumerating specifics.
- Never bare `except:`; never `except Exception:` except at top-level boundaries (request handler, CLI main, worker loop) where it's logged and translated.
- Raise with actionable context: `raise RefundError(f"refund {amount} exceeds settled total {self.total}")` — the message should let someone debug without a debugger.
- Chain when translating: `raise StorageError("failed to persist invoice") from err`.
- Don't use exceptions for control flow; don't swallow and continue (`except: pass`) — either handle it meaningfully or let it propagate.

## Logging

- Module-level logger, never `print` in library code:

```python
logger = logging.getLogger(__name__)
logger.info("invoice settled", extra={"invoice_id": invoice.id, "total": str(total)})
```

- Libraries log; only applications configure handlers/levels (in the entrypoint).
- Levels: `debug` = development detail, `info` = notable business events, `warning` = degraded-but-continuing, `error` = failed operation someone may need to act on. `exception()` inside `except` blocks to capture tracebacks.
- Never log secrets, tokens, or full payloads containing PII.

## Data modeling

- Prefer typed structures over loose dicts crossing function boundaries:
  - `@dataclass(frozen=True, slots=True)` for internal value objects.
  - **pydantic** models at validation boundaries (API payloads, config, external data) — if the repo already uses it.
  - `NamedTuple` for tiny immutable records; `Enum`/`StrEnum` instead of magic strings.
- A dict is fine as a local, short-lived container; the moment it's passed between modules it deserves a type.

## Dependency discipline

Adding a dependency taxes every developer and every deploy. Before `uv add`, check:

1. Is it ≲30 lines to do ourselves with the stdlib? Write it.
2. Is it maintained (recent releases, issues triaged), typed, and license-compatible?
3. Does something already in `uv.lock` cover it? (Don't add `requests` to a repo using `httpx`.)

Name the new dependency and the reason explicitly in the PR description.

## Deprecation in a multi-developer repo

Others may be building on the code you're changing — don't break them silently:

1. Search the whole repo (and known downstream consumers) for usages before changing a signature.
2. For public APIs, deprecate before removing: keep the old path working, emit `DeprecationWarning` (`warnings.warn("use refund() instead", DeprecationWarning, stacklevel=2)`), note the removal target in the docstring/CHANGELOG.
3. Remove in a later release/PR once usages are migrated. Internal (`_`-prefixed) code can be changed freely — that's what the prefix buys.
