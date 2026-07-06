---
name: sequence-motif-discovery
description: >
  Discover simple, human-readable sequential patterns (motifs) that differentiate two
  groups of tokenized event sequences — e.g. fraud vs good-standing accounts. Use when
  the user has per-account/customer event sequences (tokens like "feature=bucketed_value")
  with binary labels and wants interpretable, rule-engine-ready discriminative patterns.
  Combines deterministic sequence mining (PrefixSpan-style contrast mining, statistical
  verification) with LLM reasoning in a propose→verify loop. Triggers: "sequential
  patterns", "motifs", "fraud patterns", "contrast mining", "discriminative sequences",
  "behavioral rules from event data".
---

# Sequence Motif Discovery

You are running a **propose → verify loop**: algorithms generate statistically grounded
candidates, you (the LLM) reason over them — generalize, abstract, constrain, combine —
and every hypothesis you produce is **verified by the matching engine, never by your own
reading of the data**. You must not estimate counts, supports, or lifts yourself.

Full design rationale and decision points: `references/design.md`.
Pattern language spec: `references/pattern-dsl.md`.

## Hard rules

1. **Never claim a pattern discriminates without a verifier run.** All reported patterns
   must carry stats from `scripts/verify_patterns.py` on a **holdout split**.
2. **Keep patterns simple**: ≤ 4 steps, predicates a human can read aloud. If a pattern
   needs more, it's probably two patterns.
3. **Watch for label leakage**: tokens that encode the outcome itself (chargeback,
   account_closed, fraud_review) make perfect-looking useless rules. Flag them to the
   user before mining; exclude with `--exclude-tokens`.
4. Do the two-directional analysis: patterns **enriched in the target class** AND
   patterns **conspicuously absent** from it (protective/normal-behavior motifs).

## Phase 0 — Intake and data audit (do this before any mining)

The loader accepts JSONL (one line per account) in two equivalent shapes:
`{"id": "...", "label": "fraud", "events": [...], "times": [...]}` or the native
`{"account_id": ..., "label": "fraud", "event_tokens": [...], "event_times": [...]}`.
An event may be a single token, a list of tokens (itemset event), or a composite
string `"[EVT:type]---feat1:v1--feat2:v2"` (split on `---` after the event-type
header, then `--` between features; token values must not contain `--`). Both
`feat=val` and `feat:val` token styles parse. A `label` field is REQUIRED on every
record; numeric labels are fine (0/1 → `--pos-label 1`, and e.g.
`--random-cut-label 0`). Times are
optional (epoch seconds or ISO-8601, one per event) and unlock time-based
constraints, gap tokens, and recency windowing. Then run:

```bash
python scripts/profile_data.py data.jsonl --pos-label fraud
```

Read the profile and **stop to resolve the decision points in
`references/design.md` § "Decisions that require looking at the data"** (event granularity,
anchoring/truncation, leakage tokens, imbalance, vocabulary size, timestamps). If times
exist and histories are long, decide the anchoring recipe here: the default
recommendation is equal observation windows —
`--random-cut-label good --recent-seconds 6mo --min-span 6mo` (design.md § D5b; window
length from the user/profile) — plus gap-token buckets (`--gap-buckets`, informed by the
profile's per-class gap distributions). Use the SAME flags on every subsequent script
call. Ask the
user only where the data itself doesn't answer the question. Read 5–10 raw sequences per
class yourself to build intuition — but only for hypothesis generation, never for stats.

Create a train/holdout split now (verifier: `--split 0.3 --seed 42`, stratified). All
iteration happens on train; holdout is touched once, at the end.

## Phase 1 — Deterministic candidate generation

```bash
python scripts/mine_candidates.py data.jsonl --pos-label fraud --direction both \
  --min-pos-support 0.05 --max-len 4 --top 50 --metric wracc --out candidates.json
```

This runs class-aware PrefixSpan and scores every frequent subsequence with WRAcc, lift,
odds ratio, information gain and Fisher exact p (see `references/design.md` § Metrics).
Start with `--max-gap`/`--max-time-gap` unset (unconstrained order); you'll tighten in
Phase 2. Exception: if sequences are long/dense and mining is slow, a loose
`--max-time-gap` (e.g. a few days) both speeds it up and denoises candidates.
Tune `--min-pos-support` from the profile: rare-event data may need 0.02, dense data 0.10.

## Phase 2 — LLM reasoning loop (your job)

Iterate 2–4 rounds. Each round:

1. **Study** the top candidates plus a stratified sample of sequences that match / don't
   match them (verifier `--show-matches`).
2. **Propose** 5–15 hypotheses as Pattern DSL JSON (`references/pattern-dsl.md`). Moves
   that work:
   - **Generalize values**: merge adjacent bins (`amt=high`,`amt=very_high` → `any_of`),
     or wildcard the value (`{"feature": "device_change"}`).
   - **Conjoin within events** (itemset data): mined steps are single tokens; use
     `all_of` to require tokens in the SAME event (`[EVT:txn]` + `amt=high`). Seed
     these from the profiler's `--event-pairs` table.
   - **Tighten**: add `max_gap`/`window` — or with times, `max_time_gap` (between
     consecutive steps) / `time_window` (first→last step of the motif) — to require
     the motif happens in a burst. Semantics: pattern-dsl.md § "Timing semantics,
     precisely"; these bound the motif's own span, NOT position relative to the
     account's end (that's the observation window from Phase 0).
   - **Negate**: add `absent` tokens (e.g. fraud motif *without* `kyc=passed`).
   - **Semantics**: use domain reasoning about what the tokens *mean* to propose motifs
     mining missed (e.g. "escalating amounts" as a chain of increasing bins).
   - **Split/merge**: two mined patterns with high match-overlap → one cleaner pattern.
3. **Verify** on the train split:
   ```bash
   python scripts/verify_patterns.py data.jsonl --patterns hypotheses.json \
     --pos-label fraud --split 0.3 --seed 42 --overlap
   ```
4. **Keep** hypotheses that improve WRAcc/precision at comparable recall over their
   parents; drop the rest. Record every kept pattern's lineage (mined parent → edit →
   result) in a scratch log so the final report can explain provenance.

Stop when a round yields no kept improvements, or you have 10–20 strong, low-overlap
patterns.

## Phase 3 — Rule-set selection

Prune to a final set: drop patterns with pairwise match-set Jaccard > 0.6 (keep the
higher-WRAcc one), then greedily pick patterns by *additional* positives covered until
marginal gain < 1% of positives. Aim for ≤ 12 rules.

## Phase 4 — Holdout validation

Run the verifier once with the final set on the holdout. Report per-pattern precision,
recall, lift, Fisher p and BH-FDR q on holdout. If timestamps exist, also do a temporal
split (train on early, validate on late) — behavioral fraud patterns drift.
A pattern that collapses on holdout gets dropped, not re-tuned (that would burn the split).

## Phase 5 — Deliverable

Produce a report with, for each surviving pattern:
- **Rule card**: one-sentence plain-English description, the DSL JSON, holdout stats,
  2 example matching sequences (ids only if data is sensitive), lineage.
- **Rule-engine translation**: pseudocode (`IF seq contains device=new THEN within 3
  events txn_amt in {high, very_high} AND never kyc=passed THEN flag`).
- Caveats: leakage risks checked, drift sensitivity, overlap with other rules.
