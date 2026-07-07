---
name: python-team-workflow
description: End-to-end workflow for developing and maintaining a shared Python repository with multiple developers. Use when writing, refactoring, reviewing, or debugging Python code in a team repo — adding features, fixing bugs, writing tests, setting up or modernizing tooling (uv, ruff, type checking, pytest, pre-commit, CI), preparing commits and pull requests, resolving merge conflicts, or bootstrapping a new Python project. Covers code standards, testing strategy, git conventions, CI/CD, and team collaboration norms.
---

# Python Team Workflow

Workflow and standards for Python repositories maintained by multiple developers. The goal on every task: leave the repo more consistent, better tested, and easier for the next developer (human or Claude) than you found it.

## Operating principles

1. **The repo is shared.** Match existing conventions before introducing new ones — read neighboring code, `CLAUDE.md`, and `pyproject.toml` before writing. Small, focused diffs merge fast and review well; drive-by refactors belong in their own PR.
2. **Verification is a loop, not a final step.** Run checks after each meaningful change, not once at the end. A change is not "done" until format, lint, types, and tests all pass. This catches drift early, when the diff that caused it is still small.
3. **Configuration is a contract.** `pyproject.toml` is the single source of truth for tooling; `uv.lock` guarantees identical environments for every developer and CI. Never edit the lockfile by hand, never leave it out of a commit that changes dependencies.
4. **Everything reproducible lives in the repo.** Tool versions, hooks, CI, editor-agnostic settings, and Claude configuration (`CLAUDE.md`, `.claude/`) are committed, so every developer and every Claude session behaves the same way.

## The core loop

Copy this checklist into your response for any non-trivial task and check items off as you go:

```
Task Progress:
- [ ] 1. Orient: read the relevant code, CLAUDE.md, and recent git log
- [ ] 2. Plan: state the approach and files to touch before editing
- [ ] 3. Branch: create/confirm a short-lived feature branch
- [ ] 4. Implement in small slices; for bug fixes, write the failing test first
- [ ] 5. Verify: run scripts/checks.sh (format + lint + types + tests)
- [ ] 6. Commit: conventional message, lockfile included if deps changed
- [ ] 7. Deliver: push and open/update the PR with a reviewable description
- [ ] 8. Reflect: if you hit a repo-specific surprise, record it in CLAUDE.md
```

**Step 1 — Orient.** Read the code you'll touch and its tests. Check `git log --oneline -15` for in-flight themes and `CLAUDE.md` for repo-specific rules. In a multi-developer repo, also check open PRs touching the same area to avoid collisions.

**Step 2 — Plan.** For anything beyond a few lines, state the plan first: what changes, where, how it will be tested, what stays out of scope. If two approaches are genuinely viable, pick one and say why — don't implement both.

**Step 3 — Branch.** Never commit directly to `main`. Branch naming and trunk-based conventions: see [references/git-workflow.md](references/git-workflow.md).

**Step 4 — Implement.** Work in vertical slices that each compile and pass tests, rather than one big-bang edit. For bug fixes, reproduce with a failing test *before* fixing — the test is the proof and the regression guard. Follow the code standards in [references/code-standards.md](references/code-standards.md).

**Step 5 — Verify.** Run the bundled gate script from the repo root (it lives in this skill's `scripts/` directory):

```bash
bash <path-to-this-skill>/scripts/checks.sh        # check everything
bash <path-to-this-skill>/scripts/checks.sh --fix  # auto-fix format/lint first, then check
```

Fix failures and re-run until clean. If the repo has its own `make check` / `just check` / CI-mirroring command, prefer that — the script is the fallback that works anywhere.

**Step 6 — Commit.** Conventional Commits format (`feat:`, `fix:`, `chore:`, ...), imperative mood, body explains *why*. Details and examples: [references/git-workflow.md](references/git-workflow.md).

**Step 7 — Deliver.** Push the branch and open or update the PR. A reviewable PR is small (target < ~400 changed lines), has a description stating problem → approach → testing, and calls out anything risky. Only create a PR when the user asks for one.

**Step 8 — Reflect.** The team's golden rule: whenever something repo-specific tripped you up (a hidden convention, a flaky test, a required env var), add one line to `CLAUDE.md` so no future session repeats the mistake. Keep it terse — see [references/collaboration.md](references/collaboration.md).

## Command cheat sheet (uv-based repos)

```bash
uv sync                      # install/refresh the environment from uv.lock
uv run pytest                # run tests in the project environment
uv run pytest tests/test_x.py -k name -x   # one test, stop on first failure
uv add <pkg>                 # add a dependency (updates pyproject + lock)
uv add --dev <pkg>           # add a dev-only dependency
uv lock --upgrade-package <pkg>             # controlled single-package upgrade
uv run ruff format . && uv run ruff check --fix .   # format + lint fix
uv run pre-commit run --all-files          # run all hooks like CI does
```

Always prefix with `uv run` so commands use the locked project environment, never a global interpreter.

## Where to find the details

Read the reference that matches the task at hand — don't load them all:

| Task | Reference |
|---|---|
| Set up / modernize tooling: uv, ruff, type checker, pre-commit, `pyproject.toml` | [references/tooling.md](references/tooling.md) |
| Write or improve tests, coverage policy, fixtures, TDD loop | [references/testing.md](references/testing.md) |
| Code style: typing, docstrings, errors, logging, project layout | [references/code-standards.md](references/code-standards.md) |
| Branching, commits, PRs, code review, merge conflicts, parallel work | [references/git-workflow.md](references/git-workflow.md) |
| CI pipelines, releases, versioning, dependency updates | [references/ci-cd.md](references/ci-cd.md) |
| CLAUDE.md upkeep, shared Claude config, multi-session/multi-dev coordination | [references/collaboration.md](references/collaboration.md) |

## Non-negotiables

- Never commit code that fails format, lint, type, or test checks. If a check must be suppressed, use the narrowest possible ignore (`# noqa: RULE`, `# type: ignore[code]`) with a reason.
- Never push directly to `main` or force-push a shared branch (`--force-with-lease` on your own feature branch is fine).
- Never remove or weaken a failing test to get to green without explicit agreement — a failing test is information.
- Never hand-edit `uv.lock`; never commit secrets, credentials, or `.env` files.
- Never disable a pre-commit hook or CI step to unblock yourself; fix the underlying issue or raise it with the team.
- When a task reveals missing repo documentation or a tooling gap, fix or record it — that's maintenance, and it's part of every task.
