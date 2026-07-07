# CI/CD: pipelines, releases, dependency updates

## Contents
- Principles
- GitHub Actions: CI workflow (full example)
- Required checks and branch protection
- Versioning and changelog
- Release workflow (PyPI / internal index)
- Dependency updates
- When CI fails

## Principles

- **CI runs exactly what developers run locally** — same tools, same versions (that's why `uv sync --frozen` and pre-commit both exist). Any drift between "works locally" and CI is a bug in the setup.
- CI is the authority; pre-commit hooks are a local convenience that can be bypassed. Every gate a hook enforces must also run in CI.
- Fast feedback: fail on lint/format/types in under a minute before spending minutes on tests. Cache aggressively.
- A red `main` is a stop-the-line event: fixing or reverting the offending commit takes priority over new work. Revert first, investigate after, if the fix isn't obvious within the hour.

## GitHub Actions: CI workflow

`.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true          # stale pushes stop wasting runners

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
        with:
          enable-cache: true
      - run: uv sync --frozen
      - run: uv run ruff format --check .
      - run: uv run ruff check .
      - run: uv run mypy src

  test:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.11", "3.12", "3.13"]   # libraries: all supported; apps: just the deployed version
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
        with:
          enable-cache: true
      - run: uv sync --frozen
        env:
          UV_PYTHON: ${{ matrix.python-version }}
      - run: uv run pytest -n auto --cov --cov-report=xml
      - uses: codecov/codecov-action@v4   # or the repo's coverage service
        if: matrix.python-version == '3.12'
```

Notes:
- `--frozen` makes CI fail if `uv.lock` is out of sync with `pyproject.toml` instead of silently re-resolving.
- Applications pin one Python version (match `.python-version`); libraries test the full supported matrix.
- Add service containers (postgres, redis) in the `test` job for integration tests behind the `integration` marker.

## Required checks and branch protection

Configure on `main`:

- Require the `lint` and `test` checks to pass before merge.
- Require at least one approving review; dismiss stale approvals on new pushes.
- Require branches to be up to date before merging (or use a merge queue at higher volume) — prevents "green on a stale base" breakage.
- No direct pushes, including admins.

## Versioning and changelog

- **SemVer** (`MAJOR.MINOR.PATCH`) for libraries; CalVer is acceptable for applications if the team prefers.
- The version lives in one place: `[project] version` in `pyproject.toml`.
- Maintain `CHANGELOG.md` in Keep-a-Changelog format with an `## [Unreleased]` section; PRs that change user-visible behavior add a line to it. With disciplined Conventional Commits you can automate this (release-please, python-semantic-release, or `git-cliff`) — adopt the automation as its own PR, agreed by the team.
- Breaking changes: bump MAJOR, document the migration path in the changelog.

## Release workflow

Tag-triggered publish with **PyPI Trusted Publishing** (OIDC — no long-lived API tokens in secrets):

```yaml
# .github/workflows/release.yml
name: Release
on:
  push:
    tags: ["v*"]

jobs:
  publish:
    runs-on: ubuntu-latest
    environment: release          # gate behind an environment for approval/audit
    permissions:
      id-token: write             # trusted publishing
      contents: write             # GitHub release
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv build
      - run: uv publish           # PyPI trusted publisher configured for this repo/workflow
      - uses: softprops/action-gh-release@v2
        with:
          generate_release_notes: true
```

Release procedure (manual parts):

1. Ensure `main` is green and the changelog's `Unreleased` section is accurate.
2. Bump the version + move changelog entries in a `chore(release): v1.4.0` PR; merge it.
3. `git tag v1.4.0 && git push origin v1.4.0` — the workflow does the rest.
4. Verify the package installs from the index before announcing.

## Dependency updates

- Enable **Dependabot** (or Renovate) for grouped weekly updates:

```yaml
# .github/dependabot.yml
version: 2
updates:
  - package-ecosystem: uv
    directory: "/"
    schedule: {interval: weekly}
    groups:
      minor-and-patch:
        update-types: [minor, patch]
  - package-ecosystem: github-actions
    directory: "/"
    schedule: {interval: weekly}
```

- Green CI is the merge bar for grouped minor/patch bumps. Major bumps get a human (or Claude) reading the changelog for breaking changes and testing affected paths.
- Security advisories jump the queue: patch, verify, release.

## When CI fails

1. Read the actual failing step's log — don't guess from the job name.
2. Reproduce locally with the same command CI ran (they're identical by design).
3. Flaky failure? Re-run once to confirm, then treat the flake itself as a bug (see [testing.md](testing.md) → Flaky tests) — habitual "re-run until green" destroys trust in CI.
4. Never merge on red, never `skip-ci` your way past a gate, never delete the failing check.
