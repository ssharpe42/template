# Collaboration: CLAUDE.md, shared Claude config, multi-developer coordination

## Contents
- CLAUDE.md: the team's shared memory
- What goes in CLAUDE.md (and what doesn't)
- Shared .claude/ configuration
- Working effectively as a Claude session in a team repo
- Parallel Claude sessions
- Decision records
- Onboarding a new developer (or Claude environment)

## CLAUDE.md: the team's shared memory

`CLAUDE.md` at the repo root is committed, loaded into every Claude session, and shared by the whole team. It is the highest-leverage file in the repo for AI-assisted development.

**The golden rule:** whenever Claude (or a developer) does something wrong that better context would have prevented, add one line to CLAUDE.md so it never happens again. It's a living document — expect it to change weekly. Prune as aggressively as you add: an instruction that no longer applies is worse than none.

**Keep it around ~100 lines.** Every line is a permanent tax on every session's context window; short, dense files are followed far more reliably than 800-line manuals. When a section grows into a *procedure* rather than a fact, move it into a skill (like this one) whose body loads only on demand, and leave a one-line pointer.

## What goes in CLAUDE.md (and what doesn't)

A good team CLAUDE.md skeleton:

```markdown
# myproject

One sentence on what this repo is.

## Commands
- `uv sync` — install env; `uv run pytest -n auto` — tests
- `make check` — everything CI runs (do this before any commit)

## Architecture
- src/myproject/billing — invoicing domain logic (pure, no I/O)
- src/myproject/api — FastAPI layer; talks to billing via services.py
- Entry points: cli.py (ops), api/app.py (service)

## Rules
- Money is Decimal end to end; float money is a bug
- All timestamps UTC, tz-aware; naive datetimes are a bug
- DB access goes through repositories/, never raw SQL in handlers
- Feature flags via flags.py; never os.environ directly

## Gotchas
- tests/integration needs `docker compose up -d db` first
- settings.py reads .env only in dev; prod is real env vars
```

**Belongs**: commands, architectural map, repo-specific invariants, gotchas that cost someone an hour.
**Doesn't belong**: generic Python advice (Claude knows it), long procedures (make a skill), anything the linter/type-checker already enforces (make the tool enforce it — tools beat prose), secrets (never).

## Shared .claude/ configuration

Commit the team's Claude configuration so every developer's sessions behave consistently:

```
.claude/
├── skills/                  # shared workflows, invoked as /skill-name
│   └── python-team-workflow/
├── agents/                  # custom subagent definitions, if used
└── settings.json            # shared permissions and hooks
```

- `settings.json` (committed) holds team-wide permission allowlists (e.g. allow `uv run pytest`, `ruff`, read-only git) and hooks; `settings.local.json` (gitignored) holds personal overrides.
- High-value hooks for a Python team: a `PostToolUse` hook that runs `ruff format` on edited `*.py` files, and a hook that blocks `git commit --no-verify`. Keep hooks fast and quiet.
- Treat `.claude/` changes like code: PR-reviewed, since skills and settings can grant tool permissions.

## Working effectively as a Claude session in a team repo

- **Plan before building.** For multi-file changes, explore and produce a plan first (plan mode / a written plan in the response), get it confirmed, then implement. The most expensive failure mode is a fast, wrong implementation.
- **Course-correct early.** If reality diverges from the plan mid-task (an API doesn't exist, a test framework surprise), stop and say so rather than improvising a workaround that reviewers will have to untangle.
- **Manage context.** In long sessions, prefer targeted reads (specific files, `grep`) over bulk directory dumps; quality degrades as the window fills — keep well under capacity. Summarize and continue rather than dragging dead exploration along.
- **Verify like a human teammate.** Before declaring done: checks pass, the feature actually runs (not just typechecks), and the diff is self-reviewed. Report results honestly — "tests pass except X, which fails because Y" beats a false "all green".
- **Leave the trail.** Update CLAUDE.md (golden rule), the changelog when user-visible, and docstrings for changed public APIs — in the same PR.

## Parallel Claude sessions

Teams routinely run several Claude sessions at once. Rules that keep them from colliding:

- One branch + one worktree per session (see [git-workflow.md](git-workflow.md) → Parallel work); each worktree gets its own `uv sync`. Never point two sessions at the same checkout.
- Give each session a crisply scoped task with explicit *non-goals* — overlap in scope becomes merge conflicts an hour later.
- Sessions must not edit the same hot files (`pyproject.toml`, `uv.lock`, root `conftest.py`) concurrently; sequence those changes.
- For competing-implementation experiments (N sessions, pick the best), mark the losers' branches for deletion immediately — abandoned branches confuse the team.

## Decision records

When a change involves a decision that will need re-explaining in six months (new dependency, architectural boundary, versioning policy), write a short ADR in `docs/adr/NNNN-title.md`: context, decision, alternatives considered, consequences — ten lines is fine. Link it from the PR. This is dramatically cheaper than re-litigating the decision at every review, and gives future Claude sessions the *why* behind the rules in CLAUDE.md.

## Onboarding a new developer (or Claude environment)

The repo should make this a three-command experience — if it isn't, fixing that is high-priority maintenance:

```bash
git clone <repo> && cd <repo>
uv sync && uv run pre-commit install
make check     # or the repo's equivalent — must pass on a fresh clone
```

Everything else a newcomer needs lives in: `README.md` (what/why/quickstart), `CONTRIBUTING.md` (workflow + PR expectations), `CLAUDE.md` (repo map + rules), `docs/adr/` (why things are the way they are). If onboarding required tribal knowledge, that knowledge was in the wrong place — commit it.
