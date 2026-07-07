# python-team-workflow

A Claude Code skill for developing and maintaining a Python repository with multiple developers. It gives every Claude session (and every teammate's session) the same playbook: modern tooling (uv + ruff + strict typing + pytest), a verify-before-commit loop, git/PR conventions, CI/CD templates, and team-collaboration norms like the CLAUDE.md "golden rule".

## Install

Copy this directory into a repo at `.claude/skills/python-team-workflow/` and commit it. Every developer's Claude Code sessions pick it up automatically:

- Claude loads it on its own whenever a task matches the description (writing/refactoring Python, tests, tooling, PRs, ...).
- Anyone can invoke it explicitly with `/python-team-workflow`.

## Layout

```
python-team-workflow/
├── SKILL.md                      # entry point: principles, core loop, cheat sheet, non-negotiables
├── references/                   # loaded on demand, one level deep (progressive disclosure)
│   ├── tooling.md                # uv, ruff, type checking, pre-commit, pyproject.toml
│   ├── testing.md                # pytest strategy, fixtures, coverage, flaky tests
│   ├── code-standards.md         # layout, typing, docstrings, errors, logging, deps
│   ├── git-workflow.md           # branching, conventional commits, PRs, review, conflicts
│   ├── ci-cd.md                  # GitHub Actions, releases, versioning, dependency updates
│   └── collaboration.md          # CLAUDE.md upkeep, shared .claude/, parallel sessions
└── scripts/
    └── checks.sh                 # one-command gate: format + lint + types + tests
```

## Customizing for your repo

The skill is deliberately repo-agnostic. Team-specific facts (commands, architecture map, invariants, gotchas) belong in your repo's `CLAUDE.md`, not here — see `references/collaboration.md` for the recommended split. If your team's conventions differ (e.g. merge commits instead of squash, CalVer instead of SemVer), edit the relevant reference file; each is self-contained.
