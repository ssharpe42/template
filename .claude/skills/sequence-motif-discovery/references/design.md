# System design: LLM-guided discriminative sequence motif discovery

## Problem statement

Input: two sets of event sequences (e.g. fraud vs good-standing accounts). Each event is
one or more tokens of the form `feature=discretized_value`. Output: a small set of
**simple sequential motifs** (≤ ~4 steps, optional gap/window constraints, optional
absence conditions) that are statistically enriched in one class, understandable by a
human, and implementable in a rule engine.

## Why a hybrid architecture (and not "just ask the LLM" or "just mine")

- **Pure LLM**: an LLM reading raw sequences cannot reliably count support across
  thousands of accounts; it will hallucinate plausible-sounding patterns and misestimate
  their frequency. Context windows also can't hold a realistic dataset.
- **Pure mining**: classic sequential pattern mining (PrefixSpan, SPADE, BIDE, SPAM) and
  its class-aware variants (contrast/discriminative/emerging sequential pattern mining)
  produce thousands of redundant, syntactic candidates. They cannot merge semantically
  equivalent bins, propose negations, reason about what tokens *mean*, or decide which of
  500 statistically-similar patterns a fraud analyst would actually want.

The literature on LLM rule discovery converges on the same split: **the LLM is a semantic
proposal mechanism inside a deterministic, data-grounded verification loop** (cf.
Hypotheses-to-Theories rule libraries, RLIE, LLM-agent scoring-system construction). The
mining algorithms guarantee coverage and statistical honesty; the LLM contributes
abstraction, domain semantics, and taste.

## Architecture

```
                ┌─────────────────────────────────────────────┐
                │ Phase 0: Profile + audit (profile_data.py)   │
                │  stats, vocab, leakage scan, split creation  │
                └──────────────────┬──────────────────────────┘
                                   ▼
 ┌───────────────────────────────────────────────────────────┐
 │ Phase 1: Candidate generation (mine_candidates.py)        │
 │  class-aware PrefixSpan → frequent subsequences with      │
 │  per-class support → WRAcc/lift/OR/IG/Fisher scoring →    │
 │  closed-pattern dedup → top-k both directions             │
 └──────────────────┬────────────────────────────────────────┘
                    ▼
 ┌───────────────────────────────────────────────────────────┐
 │ Phase 2: LLM loop (2–4 rounds)                            │
 │   study candidates + matched/unmatched samples            │
 │   propose DSL hypotheses (generalize/tighten/negate/…)    │◄──┐
 │   verify_patterns.py on TRAIN → keep improvements         │───┘
 └──────────────────┬────────────────────────────────────────┘
                    ▼
 ┌───────────────────────────────────────────────────────────┐
 │ Phase 3: Rule-set selection (overlap prune + greedy cover)│
 │ Phase 4: One-shot HOLDOUT validation (+ temporal split)   │
 │ Phase 5: Rule cards + rule-engine translation             │
 └───────────────────────────────────────────────────────────┘
```

### Why this candidate generator

- **PrefixSpan** (projection-based frequent subsequence mining) is simple, complete, and
  easy to make class-aware: track per-class support during projection and prune on
  minimum support *in the target class* — this is the standard trick behind
  discriminative/contrast sequential pattern mining and emerging-pattern mining.
- Mining runs **unconstrained-gap** first. Gap constraints during mining require
  multi-position projections (implemented, `--max-gap`), but the cheaper route is: mine
  loose, then let the LLM tighten with `max_gap`/`window` in the DSL where it sharpens
  precision — the verifier does full backtracking gap-aware matching.
- **Closed-pattern filtering** (drop a pattern if a superpattern has identical per-class
  support) removes most redundancy before the LLM ever sees candidates.
- Alternatives if scale demands: SPAM/BIDE bitmap miners via the SPMF Java library;
  top-k contrast SPM with self-adaptive gap; or a simple discriminative k-mer pass
  (n-gram contrast) as a cheap first cut. The DSL and verifier are miner-agnostic.

### Why these metrics

For pattern P with `a` = matching positives of `n_pos`, `c` = matching negatives of
`n_neg` (b, d complements):

| Metric | Formula (sketch) | Role |
|---|---|---|
| support_pos / support_neg | a/n_pos, c/n_neg | readability, floor filters |
| **WRAcc** | (a+c)/N · (a/(a+c) − n_pos/N) | primary ranking: balances lift and coverage; standard in subgroup discovery |
| lift | (a/n_pos)/(c/n_neg), Laplace-smoothed | intuition for analysts |
| odds ratio | (a+½)(d+½)/((b+½)(c+½)) | effect size robust to imbalance |
| Fisher exact p (one-sided) | hypergeometric tail | significance |
| BH-FDR q | across the tested pattern set | multiple-testing control — mandatory, since mining tests thousands of hypotheses |
| info gain | H(class) − H(class \| match) | tie-breaker |

Report all; rank by WRAcc by default. Rules destined for a rule engine usually get a
precision floor instead (e.g. precision ≥ 0.5 at recall ≥ 0.02) — confirm with the user.

### Why the LLM loop is shaped this way

Each LLM move maps to a known weakness of syntactic mining:

| LLM move | What mining can't do |
|---|---|
| merge value bins / wildcard values | doesn't know `amt=high` and `amt=very_high` are semantically adjacent |
| add `max_gap`/`window` | burstiness is a semantic hypothesis ("probing happens fast") |
| `absent` conditions | absence patterns explode the search space combinatorially |
| propose unmined motifs from domain sense | mining only finds what clears the support floor |
| merge overlapping patterns | redundancy is statistical, but *which* survivor is meaningful is semantic |

The loop is a beam search where the LLM is the successor function and the verifier is the
objective. Keep lineage (parent pattern → edit → stats delta) so the final report can
justify every rule.

### Guardrails

- **Train/holdout discipline**: all iteration on train; holdout used once. With
  timestamps, add a temporal split — fraud drifts, and a motif that only worked in Q1 is
  a trap.
- **Leakage scan**: profile flags tokens near-perfectly correlated with the label
  (support ratio > 50× and present in >30% of positives) as leakage suspects — these are
  usually outcome encodings, and the user must confirm before they're excluded.
- **FDR control** on every verifier run, because the LLM+miner jointly test many
  hypotheses.
- **Complexity budget**: ≤ 4 steps, ≤ 1 absence clause, ≤ 12 final rules. Anything
  richer defeats the "human can read it / rule engine can run it" requirement.

## Decisions that require looking at the data

These are the points where the operator (LLM) must inspect the profile/samples — and
possibly ask the user — before proceeding. Options listed roughly by preference.

**D1. Event granularity.** Is an event one token or a bundle of feature-tokens?
  - (a) If events are single tokens, use as-is.
  - (b) If multiple features fire per event (e.g. an event carries `[EVT:type]` plus 3–5
    feature tokens), keep them as **itemset events** — supported natively. A DSL step
    matches one token in the event by default; use `all_of` for within-event
    conjunctions ("txn event AND high amount") and `{"feature": "EVT", ...}` to anchor
    on event type. Mining proposes single-token steps; conjunctive steps come from the
    LLM loop, seeded by the profiler's `--event-pairs` within-event contrast table.
  - (c) **Do NOT merge each event's tokens into one composite token** when the composite
    vocabulary explodes (e.g. ~2k feature tokens → millions of event-level combinations):
    nothing clears a support floor, and patterns can't generalize across events that
    differ in one feature. Merged tokens are only viable when the composite vocab stays
    in the low thousands.
  - (d) Flatten to consecutive tokens only if the per-event feature order is meaningful,
    which it usually isn't.

**D2. Anchoring & truncation.** Fraud sequences often end at detection; good sequences
are right-censored at extraction time. Compare length distributions per class in the
profile — a large gap means length itself leaks the label.
  - (a) Truncate both classes to the last N events before a *neutral* anchor.
  - (b) Time-window (last 30/60/90 days) if timestamps exist.
  - (c) **Random views**: fraud sequences are pre-truncated at a determined cutoff
    before label information leaks; each good account is truncated at a uniformly
    random cut point so both classes look "cut mid-history". Built in:
    `--random-cut-label good --random-cut-seed 0` (the fraud-side cutoff is applied
    upstream by the user, who knows the leak time). Take ONE view per account per run —
    multiple simultaneous views of the same account are not independent samples and
    corrupt Fisher/FDR stats. Instead, re-run with several `--random-cut-seed` values
    and keep patterns whose stats are stable across seeds.
  Ask the user how labels were assigned in time before choosing.

**D3. Label leakage tokens.** Needs eyes on the vocabulary: any token that encodes the
outcome or its investigation (chargeback, review, closure, block) must be excluded.
Profile flags suspects; the user confirms.

**D4. Class imbalance & sample size.** Read n_pos from the profile.
  - n_pos < ~200: raise `--min-pos-support` to 0.10+, expect wide CIs, keep patterns to
    2–3 steps.
  - Heavy imbalance (>50:1): consider downsampling negatives for *mining speed only* —
    verification always runs on the full data.

**D5. Timestamps / inter-event gaps.** All supported natively when the data carries
`times`; the profile prints per-class gap distributions to choose among:
  - (a) Discretize gaps into tokens (`--gap-buckets "60,3600,86400"` → `gap=lt_1m`…)
    so "velocity" motifs become *minable* — often the single best move for fraud.
  - (b) Time constraints on patterns: `max_time_gap`/`time_window` in the DSL, and
    `--max-time-gap` during mining ("A then B within an hour").
  - (c) Event-count `max_gap`/`window` only (no data change).
  - (d) Ignore time. Pick after seeing whether gap distributions differ by class.
  (a) and (b) compose: mine with gap tokens, tighten with time windows.

**D5b. Recency windowing for scope + compute.** If full histories are long, restrict to
each account's recent tail with `--recent-seconds 6mo` (durations: s/m/h/d/w/mo/y or raw
seconds) or `--recent-events N` — supported by all three scripts. Cost of mining and
matching drops roughly linearly with discarded events, and recent behavior is usually
where the fraud signal lives. Compare a windowed vs full-history profile before
committing; beware interaction with D2 (if fraud histories end at detection, "recent
tail" means different things per class).

**Recommended anchoring recipe (equal observation windows).** Combine D2c + D5b so every
account contributes the *same time period* of history ending at its cut point:

```bash
--random-cut-label good --random-cut-seed 0 --recent-seconds 6mo --min-span 6mo
```

Order of operations in the loader: sort by time → random cut (good) → `--min-span` drops
accounts with < 6mo of observed history (otherwise window *length* itself leaks the
label via account age) → keep the last 6mo before the cut. Fraud sequences arrive
pre-truncated at the user's leak cutoff, so their "cut point" is that cutoff. Check the
post-window profile: per-class event *counts* inside the window may still differ — that
is genuine activity-level signal, not an artifact, but the report should say which
patterns depend on it. Dropped-account counts per class are visible by comparing
profiles with and without `--min-span`; if the drop rate differs wildly by class,
revisit the window length with the user.

**D6. Vocabulary size & bin quality.** Vocab > ~5k tokens or features with >20 bins →
mining drowns.
  - (a) Coarsen bins (LLM proposes merges from the profile's per-feature distributions).
  - (b) Drop features with near-zero single-token contrast on train.
  - (c) Mine per feature-group first, then combine.

**D7. Direction of deployment.** Are rules for *flagging fraud* (precision-first) or
*whitelisting good behavior* (recall-first)? Changes ranking metric and which direction's
patterns matter most. Ask the user.

## Scaling notes

The bundled miner is pure-stdlib Python and comfortable to ~100k sequences × ~100 events.
First lever when it's slow: shrink sequences with `--recent-seconds`/`--recent-events`
(D5b) and/or constrain mining with `--max-gap`/`--max-time-gap`, which prunes projections
hard. Beyond that: sample for mining (stratified, verify on full), or swap Phase 1 for SPMF
(Java, has CM-SPADE/BIDE/contrast miners) keeping the same DSL/verifier. The verifier is
linear in (patterns × events) and rarely the bottleneck.

## Key references

- Pei et al., *PrefixSpan: Mining sequential patterns by prefix-projected growth*.
- Dong & Li, *Emerging patterns* (contrast mining foundations).
- Novak, Lavrač & Webb, *Supervised descriptive rule discovery* (WRAcc, subgroup discovery).
- Interpretable SPM for classification: https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12604564/
- Discriminative k-mers for sequence classification: https://arxiv.org/pdf/2310.10321
- LLM rule discovery surveys & loops: https://arxiv.org/pdf/2505.21935 ,
  https://arxiv.org/pdf/2510.19698 (RLIE), https://arxiv.org/pdf/2601.22324
- SPMF pattern-mining library: https://www.philippe-fournier-viger.com/spmf/
