---
name: multi-agent-model-training
description: >-
  Multi-agent workflow for designing and implementing changes on a model-training
  repo, with a separate judge that gates risky or expensive actions before they
  run. Use when planning or making changes to training code, configs, data
  pipelines, eval harnesses, sweeps, or experiment infrastructure — anything that
  can launch a training run, spend GPU/cloud budget, move data, or overwrite
  checkpoints or a model registry. Triggers on "train", "fine-tune", "sweep",
  "launch a run", "data pipeline", "checkpoint", "eval", "experiment".
---

# Multi-Agent Model Training (Actor + Judge)

## Why this skill exists

Coding agents fail loudest where actions are **expensive and irreversible**. The
public horror stories — agents deleting a production database, wiping mailboxes,
sending unauthorized email, burning a budget that wasn't theirs to spend — all
share one shape: a single agent that was *pursuing a task* also got to *decide
whether its own actions were safe*. Those are two different jobs, and one model
in one context window does both badly: while it's optimizing for "finish the
task," it has every incentive to rationalize the risky shortcut.

Model-training repos are a sharp version of this. A single misjudged command can
burn hours of GPU time on a misconfigured run, overwrite a checkpoint that took a
day to produce, delete a dataset, or stomp a production model artifact. Prompts
("be careful!") and after-the-fact approval modals both break under real load —
prompts don't bind, and humans rubber-stamp the tenth modal of the hour.

**The pattern that works: separate the actor from the judge.** An independent
reviewer — its own context, its own prompt, a frontier model — sits at the action
boundary and decides whether each proposed risky action moves forward. The actor
proposes; the judge disposes. Orchestration (coordinating who does what) is *not*
judgment (deciding whether an action is safe) — keep them in different homes.

This skill gives you that structure as a Claude Code workflow: an **Architect**
that designs, an **Implementer** that writes code, and a **Judge** that gates the
small number of actions that can actually hurt you.

## When to use it

Invoke this workflow whenever the task could:

- launch or queue a training / fine-tuning run, or a hyperparameter sweep;
- spend GPU, TPU, or cloud budget (including spinning up instances);
- move, transform, download, or delete a dataset;
- write, overwrite, or delete a checkpoint, or push to a model registry/hub;
- modify a production training pipeline, scheduler, or CI that others depend on.

For purely local, read-only, or trivially reversible work (reading configs,
inspecting metrics, editing a docstring), you don't need the full ceremony — but
the **action classification** in `references/action-risk-classes.md` still tells
you when an innocuous-looking step crosses a line.

## The three roles

| Role | Context | Mandate | How to run it |
|---|---|---|---|
| **Architect** | read-only | Understand the repo and the request; produce a concrete plan and a list of the actions it will require. Does **not** edit or run anything. | `Explore` / `Plan` subagent, or plan mode |
| **Implementer** | read-write | Execute the plan: edit code/configs, prepare commands. Stops at every **gated** action and hands it to the Judge instead of running it. | main agent or a `general-purpose` subagent |
| **Judge** | isolated | Independently review each proposed gated action against the rubric and return a verdict: `allow`, `block`, or `escalate`. Sees the action + context, **not** the pressure to finish. | a **separate** subagent, or the programmatic judge in `templates/judge.py` |

The Judge being a *separate* invocation is the whole point. Do not let the
Implementer "judge itself" inline — that collapses the two jobs back into one
context and you're back to the failure mode. Spawn a fresh agent (or call the
programmatic judge) so the verdict comes from a clean context that was never told
"get this training run working."

## The loop

1. **Design (Architect).** Read the repo, the request, and the existing
   experiment/config conventions. Output: a plan plus an explicit **action list**.
   Tag each action with its risk class (see `references/action-risk-classes.md`).
2. **Implement (Implementer).** Work through the plan. For each action:
   - **Safe / reversible** → just do it (and log it).
   - **Gated** (expensive or irreversible) → **stop**, assemble an action proposal
     (what, why, exact command, cost estimate, blast radius, rollback), and send it
     to the Judge. Do not run it yet.
3. **Judge.** The Judge returns `allow` / `block` / `escalate` with reasons.
   - `allow` → Implementer runs it, logs the verdict + outcome.
   - `block` → Implementer revises the action and re-submits, or drops it.
   - `escalate` → surface to the human with the Judge's reasoning; wait for a
     decision. Use `AskUserQuestion` for this.
4. **Record.** Append every gated action, its proposal, the verdict, and the
   outcome to a run log (`templates/run-log.md`). This is the audit trail the
   horror-story teams wished they had.

Read `references/workflow.md` for the step-by-step with concrete model-training
examples, and `references/agent-roles.md` for ready-to-paste role prompts.

## The judge, concretely

The Judge classifies every proposed action and applies a four-outcome decision —
the core of the "give your agent a judge" pattern:

- **allow** — reversible, cheap, in-scope. Proceed.
- **allow-with-conditions** — proceed only after a named safeguard (dry-run first,
  cap `max_steps`, checkpoint to a new path, set a spend ceiling).
- **block** — the action is unsafe or out-of-scope as written; send it back.
- **escalate** — irreversible or real-money/production stakes; a human decides.

The rubric (reversibility, cost, blast radius, scope, reversal cost) lives in
`references/judge-rubric.md`. The action → default-outcome mapping for training
repos lives in `references/action-risk-classes.md`.

Two ways to run the Judge:

- **Interactive / in-session:** spawn a separate reviewer subagent with the Judge
  prompt from `references/agent-roles.md`. Best while you're actively working.
- **Programmatic / CI gate:** `templates/judge.py` is a standalone LLM-as-judge
  (Anthropic SDK, `claude-opus-4-8`, structured-output verdict) you can drop into a
  pre-run hook, a sweep launcher, or CI so that *no* run starts without a verdict.
  This is how you make the gate impossible to skip when no human is watching.

## Principles (from the failure modes)

- **Actor ≠ judge.** Never let the agent doing the work sign off on its own risky
  action. Separate context, every time.
- **Gate on reversibility and cost, not on vibes.** "Is this hard to undo or
  expensive to redo?" is the question, not "does this feel risky?".
- **Dry-run before the real run.** Most training mistakes are caught by a 10-step
  dry run or a `--dry-run` / `print-config` pass. The Judge should demand it.
- **Earn complexity.** Don't stand up elaborate multi-agent orchestration before
  the basics (a run survives a crash, checkpoints are resumable, the eval is
  trustworthy) work. Premature complexity is itself a top failure mode.
- **A task is not a job.** Finishing "launch the run" is not the same as "advance
  the experiment safely." The Judge holds the line on the job.
- **Log everything gated.** If it was expensive or irreversible, the proposal,
  verdict, and outcome go in the run log.

## Files

- `references/workflow.md` — the loop, step by step, with training examples.
- `references/agent-roles.md` — paste-ready Architect / Implementer / Judge prompts.
- `references/judge-rubric.md` — the dimensions the Judge scores and how.
- `references/action-risk-classes.md` — training actions mapped to default outcomes.
- `templates/judge.py` — programmatic LLM-as-judge for hooks / CI.
- `templates/run-log.md` — audit-log template for gated actions.

## Attribution

Inspired by Nate B. Jones, *"Your AI Agent Doesn't Need A Better Prompt. It Needs
A Judge."* (AI News & Strategy Daily, May 2026) and his agent judge-layer writing.
