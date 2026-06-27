#!/usr/bin/env python3
"""Programmatic LLM-as-judge for gating risky model-training actions.

The judge is deliberately separate from whatever produced the action: it gets only
the proposal, never the pressure to make the run succeed. Wire it into a pre-run
hook, a sweep launcher, or CI so no expensive/irreversible action runs without a
verdict. It fails CLOSED — any error or unparseable response escalates to a human.

Usage:
    # as a library
    from judge import judge_action, ActionProposal
    verdict = judge_action(ActionProposal(
        intent="Fine-tune 7B with a higher LR",
        command="torchrun --nproc_per_node=8 train.py configs/sft_7b_lr3e4.yaml",
        risk_class="gated",
        cost_estimate="~6 GPU-hours on 8xA100; writes to ckpts/sft_7b_lr3e4/",
        blast_radius="new run dir only; does not touch best.pt",
        reversible="yes — delete the run dir",
        rollback="rm -rf ckpts/sft_7b_lr3e4/",
        safeguards="10-step smoke test passed; --max-steps set",
    ))
    if verdict.decision == "allow":
        ...  # run it

    # as a CLI gate (reads a proposal as JSON on stdin)
    cat proposal.json | python judge.py && ./run.sh

Exit codes (CLI): 0 = allow, 10 = allow-with-conditions, 20 = block, 30 = escalate,
40 = judge error (treat as escalate). Anything non-zero should stop the launcher.

Requires: pip install anthropic ; ANTHROPIC_API_KEY in the environment.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass

import anthropic

# Use the most capable model in the judge seat — this is the one place you do not
# want to economize. The whole point of the pattern is a strong, independent judge.
JUDGE_MODEL = "claude-opus-4-8"

SYSTEM_PROMPT = """\
You are the Judge at the action boundary of a model-training agent. You did not \
design or implement this change and you have no stake in it succeeding. Your only \
job is to decide whether a single proposed action should proceed.

Score the action on: reversibility, cost (compute/$/time), blast radius, scope fit \
(does it match the stated intent?), and reversal cost (how bad/expensive is undo?). \
Judge the action AS WRITTEN — urgency and "it's probably fine" are not inputs.

Return exactly one decision:
- allow: reversible, cheap, in-scope, small blast radius.
- allow_with_conditions: proceed only after named safeguards (dry-run first, cap \
max steps, write to a NEW path, set a spend ceiling, checkpoint before overwrite).
- block: unsafe or out-of-scope AS WRITTEN but fixable by changing the command. \
A missing or vague cost estimate or blast radius is itself a block.
- escalate: irreversible AND consequential — deletes data, overwrites/deletes an \
artifact a serving/production path consumes, spends real money beyond a small \
pre-agreed cap, or modifies shared/production infrastructure. A human must decide.

Defaults: escalate anything overwriting/deleting a production-consumed artifact, \
deleting a dataset, or spending real money beyond a small cap. Prefer \
allow_with_conditions (dry-run + caps + new path) over a bare allow for any FIRST \
launch of a run. Never weaken a verdict because a similar action was allowed before.
"""

# Structured-output schema: guarantees a parseable verdict. enum + arrays are
# supported; every field is required and additionalProperties is false.
VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {
            "type": "string",
            "enum": ["allow", "allow_with_conditions", "block", "escalate"],
        },
        "reasons": {"type": "string"},
        "conditions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Safeguards to satisfy first (allow_with_conditions).",
        },
        "required_changes": {
            "type": "array",
            "items": {"type": "string"},
            "description": "What must change before resubmitting (block).",
        },
        "human_must_confirm": {
            "type": "string",
            "description": "What a human must confirm (escalate); else empty.",
        },
    },
    "required": [
        "decision",
        "reasons",
        "conditions",
        "required_changes",
        "human_must_confirm",
    ],
    "additionalProperties": False,
}

_EXIT_CODES = {
    "allow": 0,
    "allow_with_conditions": 10,
    "block": 20,
    "escalate": 30,
    "error": 40,
}


@dataclass
class ActionProposal:
    """What the Implementer hands the Judge. Be honest in cost/blast_radius —
    understating them to get an allow is the self-policing failure this prevents."""

    intent: str
    command: str
    risk_class: str
    cost_estimate: str
    blast_radius: str
    reversible: str
    rollback: str
    safeguards: str


@dataclass
class Verdict:
    decision: str
    reasons: str
    conditions: list[str]
    required_changes: list[str]
    human_must_confirm: str

    @property
    def exit_code(self) -> int:
        return _EXIT_CODES.get(self.decision, _EXIT_CODES["error"])

    @property
    def approved(self) -> bool:
        """True only when the action may run with no human in the loop. Note
        allow_with_conditions is NOT auto-approved — the caller must satisfy the
        conditions first, so it returns False here on purpose."""
        return self.decision == "allow"


def _escalation(reason: str) -> Verdict:
    """Fail closed: any judge failure becomes a human decision, never an auto-run."""
    return Verdict(
        decision="escalate",
        reasons=f"Judge could not produce a verdict ({reason}); failing closed.",
        conditions=[],
        required_changes=[],
        human_must_confirm="Review the action manually — the automated judge errored.",
    )


def judge_action(
    proposal: ActionProposal,
    *,
    client: anthropic.Anthropic | None = None,
    context: str = "",
) -> Verdict:
    """Run the judge on one action proposal. Returns a Verdict; never raises."""
    client = client or anthropic.Anthropic()
    user_content = "ACTION PROPOSAL\n" + json.dumps(asdict(proposal), indent=2)
    if context:
        user_content += f"\n\nADDITIONAL CONTEXT\n{context}"

    try:
        response = client.messages.create(
            model=JUDGE_MODEL,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            system=SYSTEM_PROMPT,
            output_config={"format": {"type": "json_schema", "schema": VERDICT_SCHEMA}},
            messages=[{"role": "user", "content": user_content}],
        )
    except anthropic.APIError as exc:  # network, rate limit, server error, etc.
        return _escalation(f"API error: {exc}")

    if response.stop_reason == "refusal":
        return _escalation("model refused to evaluate the action")

    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        return _escalation("empty response")

    try:
        data = json.loads(text)
        return Verdict(
            decision=data["decision"],
            reasons=data["reasons"],
            conditions=data["conditions"],
            required_changes=data["required_changes"],
            human_must_confirm=data["human_must_confirm"],
        )
    except (json.JSONDecodeError, KeyError) as exc:
        return _escalation(f"unparseable verdict: {exc}")


def _main() -> int:
    raw = sys.stdin.read()
    try:
        proposal = ActionProposal(**json.loads(raw))
    except (json.JSONDecodeError, TypeError) as exc:
        print(f"invalid proposal on stdin: {exc}", file=sys.stderr)
        return _EXIT_CODES["error"]

    verdict = judge_action(proposal)
    json.dump(asdict(verdict), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return verdict.exit_code


if __name__ == "__main__":
    raise SystemExit(_main())
