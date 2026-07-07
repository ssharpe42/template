# Tooling: uv, ruff, type checking, pre-commit

## Contents
- The standard toolchain
- pyproject.toml as single source of truth (full example)
- uv: environments and dependency discipline
- Ruff: lint + format configuration
- Type checking
- pre-commit configuration
- Task runner (Makefile/justfile)
- Bootstrapping a new repo
- Modernizing an existing repo (pip/poetry/black/flake8 → uv/ruff)

## The standard toolchain

One tool per job, all configured in `pyproject.toml`:

| Job | Tool | Replaces |
|---|---|---|
| Packaging, venvs, Python versions, lockfile | **uv** | pip, pip-tools, virtualenv, pyenv, poetry |
| Lint + import sorting + upgrades + format | **ruff** | flake8, isort, pyupgrade, black |
| Type checking | **mypy** (CI) / **pyright** (editor) — or **ty** if the repo has adopted it | — |
| Tests | **pytest** + coverage | unittest runners |
| Git hooks | **pre-commit** | ad-hoc scripts |

If the repo already uses different tools, follow the repo — propose migration as a separate PR, never as a side effect of a feature.

## pyproject.toml as single source of truth

All tool configuration lives here — no `setup.cfg`, `.flake8`, `mypy.ini`, or scattered dotfiles. A complete team-ready example:

```toml
[project]
name = "myproject"
version = "0.1.0"
description = "One-line description"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "httpx>=0.27",
]

[dependency-groups]
dev = [
    "pytest>=8",
    "pytest-cov>=5",
    "pytest-xdist>=3",
    "mypy>=1.11",
    "ruff>=0.6",
    "pre-commit>=3.8",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = [
    "E", "W",   # pycodestyle
    "F",        # pyflakes
    "I",        # isort
    "B",        # bugbear (likely bugs)
    "UP",       # pyupgrade
    "SIM",      # simplify
    "C4",       # comprehensions
    "RUF",      # ruff-specific
    "PT",       # pytest style
]
ignore = ["E501"]  # line length handled by the formatter

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["B011"]  # assert-based test helpers are fine

[tool.mypy]
python_version = "3.11"
strict = true
warn_unreachable = true
# Loosen only for tests, never for src:
[[tool.mypy.overrides]]
module = "tests.*"
disallow_untyped_defs = false

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra --strict-markers --strict-config"
xfail_strict = true
filterwarnings = ["error"]  # warnings are future bugs; fail on them

[tool.coverage.run]
source = ["src"]
branch = true

[tool.coverage.report]
fail_under = 85
show_missing = true
skip_covered = true
```

Adjust `fail_under`, rule selection, and strictness to the repo's existing baseline — ratchet up over time, never down.

## uv: environments and dependency discipline

- `uv sync` creates/updates `.venv` from `uv.lock`. Run it after every pull that touched dependencies.
- **Always commit `uv.lock`** for applications and internal tools (libraries published to PyPI may omit it, but committing is still fine for dev reproducibility).
- Add dependencies with `uv add` / `uv add --dev`, never by editing `pyproject.toml` alone — that keeps the lock consistent.
- Upgrades are deliberate: `uv lock --upgrade-package <pkg>` for one package, `uv lock --upgrade` for all (its own PR, with tests).
- In CI use `uv sync --frozen` so CI fails loudly if the lockfile is stale instead of silently re-resolving.
- Pin the Python version in `.python-version` (e.g. `3.11`) so uv, CI, and every developer agree.

## Ruff: lint + format

- Run order matters: `ruff check --fix .` **then** `ruff format .` (lint fixes can introduce formatting changes).
- Never argue with the formatter; never commit unformatted code.
- Suppress at the narrowest scope with a reason: `x = eval(expr)  # noqa: S307 — expr is validated above`. Repo-wide ignores go in `pyproject.toml` with a comment explaining why.
- When enabling new rule families in an existing repo, fix violations in a dedicated PR (or use `ruff check --add-noqa` to baseline, then burn down).

## Type checking

- **Editor**: pyright via Pylance — fast feedback while writing.
- **CI/gate**: mypy in `strict` mode (best plugin ecosystem, e.g. Django/SQLAlchemy), or `ty` if the repo has standardized on it. Whichever the repo uses, match it — two checkers disagreeing is worse than one.
- New code is fully annotated. For legacy modules, add annotations when you touch them; use per-module overrides rather than global loosening.
- `# type: ignore` must carry the error code and ideally a reason: `# type: ignore[arg-type]  # upstream stub is wrong, see issue #123`.

## pre-commit configuration

`.pre-commit-config.yaml` — committed at repo root; every developer runs `uv run pre-commit install` once after cloning:

```yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v5.0.0
    hooks:
      - id: check-merge-conflict
      - id: check-yaml
      - id: check-toml
      - id: end-of-file-fixer
      - id: trailing-whitespace
      - id: check-added-large-files
      - id: detect-private-key
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.6.9
    hooks:
      - id: ruff-check     # lint first...
        args: [--fix]
      - id: ruff-format    # ...then format
  - repo: https://github.com/astral-sh/uv-pre-commit
    rev: 0.4.20
    hooks:
      - id: uv-lock        # keep uv.lock in sync with pyproject.toml
```

Keep hooks fast (< a few seconds) — slow hooks get skipped with `--no-verify`, which defeats the point. Type checking and the full test suite belong in CI, not hooks. Hooks can be bypassed locally, so CI must run the same checks authoritatively (see [ci-cd.md](ci-cd.md)).

## Task runner

Give the team one memorable entry point mirroring CI. A `Makefile` works everywhere:

```makefile
.PHONY: install check fix test
install:
	uv sync && uv run pre-commit install
check:
	uv run ruff format --check . && uv run ruff check . && uv run mypy src && uv run pytest
fix:
	uv run ruff check --fix . && uv run ruff format .
test:
	uv run pytest -n auto
```

## Bootstrapping a new repo

```bash
uv init --lib myproject        # or --app; creates src layout + pyproject.toml
cd myproject
echo "3.11" > .python-version
uv add --dev pytest pytest-cov ruff mypy pre-commit
# add [tool.*] sections from the example above
uv run pre-commit install
git add -A && git commit -m "chore: bootstrap project tooling"
```

Then add: `README.md` (what/why/quickstart), `CONTRIBUTING.md` (the loop from SKILL.md), `CLAUDE.md` (see [collaboration.md](collaboration.md)), CI workflow (see [ci-cd.md](ci-cd.md)), `.gitignore` (Python template).

## Modernizing an existing repo

Do this incrementally, one PR per step, with the team's agreement:

1. **uv**: `uv init` in place, move deps from `requirements*.txt`/poetry into `[project]`/`[dependency-groups]` (`uvx migrate-to-uv` automates most of this), generate `uv.lock`, update CI and docs.
2. **ruff**: replace black/isort/flake8/pyupgrade with the config above; run `ruff check --fix` + `ruff format` in one mechanical, no-logic-change commit so `git blame` stays useful (add that commit to `.git-blame-ignore-revs`).
3. **Types**: add mypy with permissive settings, ratchet per-module toward strict.
4. **pre-commit + CI**: wire the same checks in both.

Never mix a modernization step with feature work in one PR.
