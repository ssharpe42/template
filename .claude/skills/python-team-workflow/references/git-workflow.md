# Git workflow: branches, commits, PRs, review

## Contents
- Branching model
- Commit messages (Conventional Commits)
- Keeping history clean
- Staying current with main
- Merge conflicts
- Pull requests
- Code review — as author
- Code review — as reviewer
- Parallel work without collisions

## Branching model

Trunk-based development with short-lived branches:

- `main` is always releasable; protected — changes land only via reviewed PRs with green CI.
- Branch per task, named `<type>/<short-slug>` (optionally `<user>/`-prefixed if the repo does that): `feat/invoice-refunds`, `fix/duration-parse-overflow`, `chore/ruff-0.7`.
- Branches live **days, not weeks**. If a feature is too big for that, slice it into independently-mergeable PRs (behind a flag if needed) rather than growing a long-lived branch that will rot and conflict.

```bash
git fetch origin main
git switch -c feat/invoice-refunds origin/main
```

## Commit messages (Conventional Commits)

Format: `type(scope): imperative summary` — ≤72 chars, no trailing period. Body (when needed) explains **why** and any non-obvious consequences; the diff already shows *what*.

Types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore` (tooling/deps), `perf`, `ci`, `revert`. Add `!` for breaking changes: `feat(api)!: ...` plus a `BREAKING CHANGE:` footer.

```
fix(billing): reject refunds exceeding the settled total

Refunds were compared against the pre-discount total, letting
customers reclaim more than they paid. Compare against the
settled amount and add a regression test.

Closes #412
```

- Each commit is one logical change that passes checks on its own — never mix a refactor with a behavior change, or formatting churn with logic.
- Reference issues in the footer (`Closes #412`) so history links to context.
- These messages feed changelog automation (see [ci-cd.md](ci-cd.md)), so the type/scope matter beyond aesthetics.

## Keeping history clean

- On your own unpushed/unreviewed branch, freely `git commit --amend` and `git rebase -i` to shape commits into a reviewable story.
- **After review has started, stop rewriting** — push new commits so reviewers can see what changed since their last pass. Tidy at merge time via squash if the repo uses squash-merge.
- Never rewrite `main` or any branch others build on. Force-push only your own branch, only with `--force-with-lease`.
- Follow the repo's merge convention (check recent merged PRs): squash-merge keeps `main` linear and is the common default; if merge commits are used, make each commit in the PR clean.

## Staying current with main

Rebase your branch onto main regularly (at least before requesting review and before merge):

```bash
git fetch origin main
git rebase origin/main
# resolve conflicts, run checks, then:
git push --force-with-lease
```

The longer you wait, the worse the conflicts — in a multi-developer repo, rebase daily on active branches.

## Merge conflicts

1. Look at both sides *and their intent*: `git log --oneline origin/main ^HEAD -- <file>` shows what landed; read those commits/PRs, don't just eyeball markers.
2. Resolution must preserve **both** intents — the most common conflict mistake is silently discarding the other developer's change. If both sides changed the same logic for different reasons, combine them deliberately.
3. After resolving: run the full check suite before continuing the rebase. A conflict resolution that compiles but breaks tests is worse than the conflict.
4. If the other change fundamentally invalidates your approach, stop and reassess (or talk to that author) rather than forcing a textual merge.

## Pull requests

- **Small.** Target under ~400 changed lines of substance; split bigger work into stacked or sequential PRs. Review quality collapses with size.
- **One concern per PR.** Mechanical churn (formatting, renames) goes in its own PR so the behavioral diff stays readable.
- Description answers, in order: *Problem* (why this change exists, link the issue), *Approach* (what you did and any alternative you rejected), *Testing* (how you verified — commands, new tests, manual steps), *Risk/rollout* (migrations, flags, anything reviewers should probe). Use the repo's PR template if one exists.
- Draft PRs for early direction feedback; ready-for-review means checks are green and you've self-reviewed the diff line by line first — you'll catch the embarrassing stuff before anyone else does.

## Code review — as author

- Respond to every comment: fix it, or explain why not — never silently ignore.
- Push review fixes as new commits (see "Keeping history clean") and re-request review.
- Don't take findings personally and don't defend reflexively; the reviewer is your first production user.
- If a discussion exceeds a few round-trips, take it to a synchronous channel and record the outcome on the PR.

## Code review — as reviewer

Review priority order — spend attention where it matters:

1. **Correctness**: logic errors, unhandled edge cases and error paths, concurrency/state hazards.
2. **Design**: does this belong here, does it fit existing patterns, will it corner us later?
3. **Tests**: do they actually pin the new behavior? Would they fail if the fix were reverted?
4. **Readability**: naming, structure, surprising constructs.
5. Style/formatting: **don't comment on it** — that's the linter's job; if the linter allows it, it's allowed.

Etiquette: be specific and actionable, distinguish blocking issues from `nit:` preferences, ask questions instead of issuing verdicts ("what happens if `lines` is empty?"), approve when it's *good enough and safe*, not perfect. Review promptly — a stale PR punishes exactly the developer who kept their diff small.

## Parallel work without collisions

For multiple work streams (including multiple Claude sessions) on one machine, use worktrees — each gets its own directory and branch with one shared object store:

```bash
git worktree add ../myproject-refunds feat/invoice-refunds
git worktree add ../myproject-hotfix fix/duration-parse-overflow
git worktree list && git worktree remove ../myproject-hotfix   # when done
```

- Each worktree needs its own environment: run `uv sync` inside it.
- Before starting significant work, scan open PRs and branches touching the same modules; coordinate rather than racing to merge.
- If two streams must touch the same hot file, land the smaller change first and rebase the other on it.
