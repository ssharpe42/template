# Does the mining + LLM feedback loop work on real data? (KDD Cup 2015 MOOC dropout)

**TL;DR — yes, and in an instructive way.** On the official test split of a public
continuous-time event benchmark, the propose→verify loop with *weaker* models as the
in-loop LLM produced tiny, fully human-readable rule sets that reach **0.80–0.82 ROC
AUC** — recovering ~96% of a count-feature logistic-regression's discrimination
(0.851) with 4–5 auditable rules. The LLM's contribution is qualitatively necessary
here: after leakage cleanup, deterministic mining finds **zero** dropout-direction
subsequences, so every dropout rule in the final sets is an LLM-authored `absent`
negation ("never returned after a day away") that PrefixSpan cannot express.

## Setup

- **Data**: KDD Cup 2015 (XuetangX MOOC dropout). One sequence per enrollment: 7 raw
  event types with second-resolution timestamps over ~30-day courses; label `dropout`
  (79%) = no activity in the 10 days after course end. This mirror is a consistent
  subset of the original release: 72,395 train / 24,013 test enrollments (official
  split), 39 courses, 6.5M events, dropout rate matching the original. Test labels are
  the post-competition release, so evaluation is on the **official test split**.
- **Format**: generic single-token events (`problem`, `video`, …) + epoch times — the
  simple open-data shape; the skill's composite customer format is untouched and
  smoke-tested. `--gap-buckets '1h,1d,7d'` adds session/return-gap tokens on load.
- **In-loop LLMs**: Claude **Haiku** (3 rounds) and Claude **Sonnet** (2 rounds) as
  independent arms, each given the same briefing (profile, mined candidate tables,
  sample sequences, DSL spec). Every proposal was verified with the matching engine on
  the train split; only verified stats were fed back. The orchestrator did no creative
  pattern-writing — selection is the deterministic `select_ruleset.py` for all arms.
- **Splits**: iteration on 70% of official train; 30% internal holdout touched once
  (Phase 4); weights fit on full official train; AUC reported on official test.

## Leakage decision (user call, mid-experiment)

The first pass included a synthetic `course_end` calendar event, and the strongest
"dropout" motifs were all trailing-silence-before-course-end shapes (e.g. *silent ≥7d
into course end*, precision 0.91). That is recency, and the label itself is "10 more
days of silence" — leakage-adjacent, so it was **removed**: no `course_end` token, no
recency features in the baseline. Quantified cost of that honesty, on the same test
split: count-LR drops 0.871 → 0.851; mined-only rules drop 0.825 → 0.800. Published
full-data models (winner ensemble ≈0.91, CFIN ≈0.90, LR ≈0.87) all *use* recency and
calendar features, so they sit above anything in the cleaned regime by construction.

## Results (official test split, 24,013 enrollments)

| approach | rules | test AUC |
|---|---|---|
| majority-class trivial | — | 0.500 |
| mined-only (PrefixSpan → selection, no LLM) | 2 | 0.7996 |
| mined + **Haiku** loop | 4 | 0.8031 |
| mined + **Sonnet** loop | 5 | **0.8174** |
| activity volume alone (log total events) | — | 0.8386 |
| logistic regression, 13 count features | — | 0.8507 |
| *with-recency variants (for reference)* | | |
| mined-only incl. course_end | 3 | 0.8246 |
| count-LR incl. silence-before-end feature | — | 0.8713 |
| *full-data literature (recency + course features + ensembles)* | | *≈0.87–0.91* |

Reading: five plain-English rules recover 96% of the count-feature model's AUC and
~90% of the full-data deep-model scores' level, despite the subset, the leakage
handicap, and total auditability. The LLM loop's lift over mined-only is +0.4pt
(Haiku) / +1.8pt (Sonnet) AUC — modest numerically, but it is 100% of the
dropout-direction signal (see below), and both models' rule sets replicated across
holdout and test with no drift on any rule.

## Why the LLM matters here (the clean finding)

On the cleaned data, class-aware PrefixSpan returns an **empty dropout-direction
table**: dropouts do *less* of everything, so no subsequence is enriched in them.
Sequence mining is structurally blind to "the absence of behavior". Both weaker models,
given the verifier's feedback, independently converged on the negation family that
carries the dropout direction:

- **S17/H23 "Never returned after a day away"** — a student who never comes back on a
  later day can never carry a `gap≥1d` return token: 71% of dropouts, precision 0.93.
- **S18 "No work, no comeback"** (never problem/discussion AND never a day-plus
  return): train-split precision **0.946** at 54% dropout coverage — the strongest
  single rule found (later Jaccard-merged into S14/S17's family during selection).
- **S06/H03/S19** content negations (never problem / never discussion / video-but-
  never-problem).

The feedback loop also *corrected* both models' round-1 misconceptions with data: they
predicted multiple long absences meant dropout; verification showed the opposite (a
visible mid-course `gap≥7d` means the student **came back** — returning is
persistence), and both models rewrote those rules accordingly in the next round.

## Final rule set (Sonnet arm, 5 rules — holdout and test stats per rule)

| id | rule (read aloud) | direction | holdout sup pos/neg | test lift |
|---|---|---|---|---|
| S14 | navigated, but never a week-plus gap anywhere in the log | dropout | 0.869 / 0.594 | 1.44 |
| M016 | access, then a within-week return, then a same-session event | persist | 0.182 / 0.710 | 0.27 |
| S07 | navigated, but never opened the wiki | dropout | 0.797 / 0.523 | 1.55 |
| M019 | access → navigate → problem (browse then work) | persist | 0.152 / 0.667 | 0.23 |
| S19 | watched a video, but never tried a problem | dropout | 0.362 / 0.181 | 2.08 |

Rule-engine form, e.g. S19: `IF event(video) AND NEVER event(problem) => score += w`.
All five have Fisher/BH q ≈ 0 on the untouched holdout. Full DSL JSON with per-rule
selection stats: `rulesets/final_sonnet.json` (also `final_haiku.json`,
`final_mined.json`; all loop rounds with lineage in `rulesets/*_r*.json`).

## Method notes & caveats

- **Selection saturates at 2–5 rules** on this dataset: one return-rhythm rule already
  covers ~71% of persisters, one negation ~71–87% of dropouts; further rules add <0.5%
  new coverage. The `--objective auc` variant shows the same thing more sharply (a
  2–3 rule "discriminative core" ≈ 0.80 train AUC). Small rule counts are a property
  of this data, not a failure mode.
- **Weaker-model behavior**: Haiku needed the feedback loop more — its round-1 set had
  4 dead-on-arrival or sign-flipped rules that the verifier caught; by round 3 its
  negation family matched Sonnet's in kind, though it kept lower-support variants
  (H23 vs S17: 48% vs 71% dropout coverage), costing ~1.4pt AUC vs the Sonnet arm.
  Neither model ever needed its statistics corrected — the verifier-only-stats
  protocol held.
- **Caveats**: single dataset; mirror is a ~48% subset of the original release
  (baseline AUCs land where the literature's simple models do, suggesting it is
  representative); literature numbers are not strictly comparable (full data +
  recency/course features); no temporal split (course dates overlap heavily; the
  official split is enrollment-level, so a user can appear in both splits).
- **Cost**: whole loop ran on a 4-core box with no ML dependencies (pure-python
  mining/matching/LR), ~5 subagent calls totalling ~200k tokens of weaker-model usage.
