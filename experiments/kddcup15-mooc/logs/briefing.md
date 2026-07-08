# Briefing: sequential motif discovery on MOOC dropout data (KDD Cup 2015)

## The task
Each record is one student **enrollment** in a 30-day online course: a time-ordered
sequence of log events. Label = `dropout` (79% — the student had NO activity in the 10
days after the course ended) vs `persist` (21%). Your job: propose **simple, readable
sequential patterns** (JSON DSL below) that discriminate the classes. Patterns are
verified by an exact matching engine on held-out data — never guess statistics yourself.
Both directions are wanted: patterns enriched in `dropout` AND patterns enriched in
`persist` (protective engagement habits).

## Event vocabulary (the ONLY tokens that exist)
- `navigate`, `access` (course materials), `problem` (assignment work), `video`,
  `page_close`, `discussion` (forum), `wiki` — raw log events
- `course_end` — synthetic final event stamped at the course's official last day
- `gap=lt_1h` / `gap=lt_1d` / `gap=lt_7d` / `gap=ge_7d` — attached to every event
  (except each sequence's first) describing the time SINCE THE PREVIOUS event:
  same-session (<1h), same-day return, same-week return, or a 7+ day absence.
  An event is a SET of tokens, e.g. {access, gap=lt_1d}. So
  `{"all_of": ["course_end", "gap=ge_7d"]}` = "went silent ≥7 days before course end".

## Facts from the data profile (train split)
- dropout median 13 events (mean 35); persist median 135 events (mean 197) — engagement
  volume is the big signal; your patterns should capture *behavioral shape*, e.g.
  repeats (min_count), session structure, returns, problem work, trailing silence.
- median within-session gap 5s; histories span ~23-30 days.
- account-level token presence: problem in 24% of dropout vs 74% of persist;
  discussion 26% vs 63%; wiki 20% vs 48%; video 57% vs 86%.

## Pattern DSL (JSON). A hypotheses file = JSON array of these objects.
{
  "id": "P01", "name": "short human-readable name",
  "steps": [ <predicate>, ... ],            // matched IN ORDER as a subsequence
  "constraints": { ... },                    // optional
  "absent": [ <predicate> ],                 // optional: NO event anywhere may match
  "min_count": 3                             // optional: >= N non-overlapping matches
}
Predicates (per step, evaluated on ONE event = a token set):
  {"token": "problem"}                       — event contains this token
  {"any_of": ["video", "problem"]}           — contains any of these
  {"all_of": ["problem", "gap=lt_1d"]}       — contains ALL (same event!)
Constraints:
  "max_gap": N        — ≤ N other events between consecutive matched steps
  "window": N         — first→last matched step spans ≤ N events
  "max_time_gap": "3d" — time between consecutive matched steps (durations: '2h','3d','1w')
  "time_window": "1d"  — whole motif within this time span
Guidance: ≤ 4 steps; prefer any_of over near-duplicate patterns; use min_count for
"did X repeatedly"; only add constraints that plausibly RAISE precision; patterns must
read aloud as an analyst rule. Use ONLY tokens from the vocabulary above.

## Mined candidate subsequences (deterministic PrefixSpan, train subsample)
These are statistically solid starting points — your job is to GENERALIZE / TIGHTEN /
COMBINE / NEGATE them into better hypotheses, and to propose semantically motivated
patterns mining cannot express (repeats via min_count, all_of conjunctions, absent).
sup_tgt/sup_oth = fraction of target/other class matching; prec = precision for target.

### Unconstrained, max 3 steps

## Top patterns enriched in dropout (n_target=6339, n_other=1661, min_target_matches=317)

| pattern | sup_tgt | sup_oth | lift | wracc | prec | fdr_q |
|---|---|---|---|---|---|---|
| gap=ge_7d | 0.863 | 0.596 | 1.45 | 0.0439 | 0.847 | 0.0000 |
| navigate → gap=ge_7d | 0.863 | 0.596 | 1.45 | 0.0439 | 0.847 | 0.0000 |
| gap=lt_1h → gap=ge_7d | 0.706 | 0.577 | 1.22 | 0.0212 | 0.824 | 0.0000 |
| navigate → gap=lt_1h → gap=ge_7d | 0.705 | 0.577 | 1.22 | 0.0211 | 0.824 | 0.0000 |
| navigate → navigate → gap=ge_7d | 0.652 | 0.551 | 1.18 | 0.0167 | 0.819 | 0.0000 |
| gap=lt_1h → gap=lt_1h → gap=ge_7d | 0.656 | 0.567 | 1.16 | 0.0147 | 0.816 | 0.0000 |
| access → gap=ge_7d | 0.614 | 0.556 | 1.10 | 0.0094 | 0.808 | 0.0000 |
| navigate → access → gap=ge_7d | 0.613 | 0.556 | 1.10 | 0.0094 | 0.808 | 0.0000 |
| access → gap=lt_1h → gap=ge_7d | 0.613 | 0.556 | 1.10 | 0.0093 | 0.808 | 0.0000 |
| gap=lt_1h → access → gap=ge_7d | 0.613 | 0.556 | 1.10 | 0.0093 | 0.808 | 0.0000 |
| access → access → gap=ge_7d | 0.606 | 0.554 | 1.09 | 0.0084 | 0.806 | 0.0002 |
| page_close → gap=ge_7d | 0.560 | 0.524 | 1.07 | 0.0059 | 0.803 | 0.0068 |
| navigate → page_close → gap=ge_7d | 0.559 | 0.524 | 1.07 | 0.0059 | 0.803 | 0.0068 |
| gap=lt_1h → page_close → gap=ge_7d | 0.559 | 0.524 | 1.07 | 0.0059 | 0.803 | 0.0068 |
| access → page_close → gap=ge_7d | 0.559 | 0.524 | 1.07 | 0.0059 | 0.803 | 0.0068 |
| navigate → video → gap=ge_7d | 0.493 | 0.472 | 1.04 | 0.0034 | 0.799 | 0.0772 |
| video → gap=ge_7d | 0.493 | 0.473 | 1.04 | 0.0034 | 0.799 | 0.0772 |
| gap=lt_1h → video → gap=ge_7d | 0.493 | 0.473 | 1.04 | 0.0034 | 0.799 | 0.0772 |
| access → video → gap=ge_7d | 0.493 | 0.473 | 1.04 | 0.0034 | 0.799 | 0.0772 |
| page_close → gap=lt_1h → gap=ge_7d | 0.507 | 0.506 | 1.00 | 0.0001 | 0.793 | 0.4953 |

## Top patterns enriched in NOT-dropout (n_target=1661, n_other=6339, min_target_matches=84)

| pattern | sup_tgt | sup_oth | lift | wracc | prec | fdr_q |
|---|---|---|---|---|---|---|
| access → navigate → gap=lt_7d | 0.746 | 0.203 | 3.67 | 0.0893 | 0.491 | 0.0000 |
| access → navigate → gap=lt_1d | 0.705 | 0.171 | 4.12 | 0.0878 | 0.519 | 0.0000 |
| page_close → access → gap=lt_7d | 0.732 | 0.198 | 3.69 | 0.0878 | 0.492 | 0.0000 |
| page_close → navigate → gap=lt_7d | 0.713 | 0.182 | 3.92 | 0.0874 | 0.507 | 0.0000 |
| page_close → page_close → gap=lt_7d | 0.728 | 0.201 | 3.63 | 0.0867 | 0.487 | 0.0000 |
| page_close → access → gap=lt_1d | 0.706 | 0.179 | 3.95 | 0.0867 | 0.509 | 0.0000 |
| gap=lt_1h → navigate → gap=lt_1d | 0.727 | 0.202 | 3.61 | 0.0865 | 0.486 | 0.0000 |
| page_close → navigate → gap=lt_1d | 0.676 | 0.152 | 4.45 | 0.0863 | 0.539 | 0.0000 |
| gap=lt_1h → navigate → gap=lt_7d | 0.758 | 0.234 | 3.24 | 0.0862 | 0.459 | 0.0000 |
| access → gap=lt_7d → gap=lt_7d | 0.628 | 0.105 | 6.00 | 0.0862 | 0.611 | 0.0000 |
| access → access → gap=lt_7d | 0.785 | 0.262 | 3.00 | 0.0861 | 0.440 | 0.0000 |
| page_close → gap=lt_1h → gap=lt_1d | 0.720 | 0.197 | 3.65 | 0.0860 | 0.489 | 0.0000 |
| gap=lt_7d → gap=lt_7d | 0.638 | 0.115 | 5.53 | 0.0860 | 0.592 | 0.0000 |
| navigate → gap=lt_7d → gap=lt_7d | 0.638 | 0.115 | 5.53 | 0.0859 | 0.592 | 0.0000 |
| access → gap=lt_1h → gap=lt_7d | 0.786 | 0.264 | 2.98 | 0.0858 | 0.438 | 0.0000 |
| gap=lt_1h → gap=lt_7d → gap=lt_7d | 0.633 | 0.111 | 5.69 | 0.0858 | 0.599 | 0.0000 |
| gap=lt_7d → access → gap=lt_7d | 0.629 | 0.107 | 5.85 | 0.0858 | 0.605 | 0.0000 |
| navigate → problem → gap=lt_7d | 0.641 | 0.119 | 5.38 | 0.0858 | 0.585 | 0.0000 |
| gap=lt_1h → problem → gap=lt_7d | 0.641 | 0.119 | 5.38 | 0.0858 | 0.585 | 0.0000 |
| access → problem → gap=lt_7d | 0.641 | 0.119 | 5.38 | 0.0858 | 0.585 | 0.0000 |
| problem → gap=lt_1h → gap=lt_7d | 0.641 | 0.119 | 5.38 | 0.0858 | 0.585 | 0.0000 |
| navigate → access → gap=lt_7d | 0.786 | 0.265 | 2.97 | 0.0857 | 0.438 | 0.0000 |
| gap=lt_1h → access → gap=lt_7d | 0.786 | 0.265 | 2.97 | 0.0857 | 0.438 | 0.0000 |
| page_close → page_close → gap=lt_1d | 0.694 | 0.173 | 4.02 | 0.0857 | 0.513 | 0.0000 |
| gap=lt_7d → gap=lt_1h → gap=lt_7d | 0.632 | 0.112 | 5.66 | 0.0857 | 0.598 | 0.0000 |
| navigate → page_close → gap=lt_1d | 0.730 | 0.209 | 3.48 | 0.0856 | 0.477 | 0.0000 |
| gap=lt_1h → page_close → gap=lt_1d | 0.730 | 0.209 | 3.48 | 0.0856 | 0.477 | 0.0000 |
| access → page_close → gap=lt_1d | 0.730 | 0.209 | 3.48 | 0.0856 | 0.477 | 0.0000 |
| page_close → gap=lt_1h → gap=lt_7d | 0.751 | 0.232 | 3.24 | 0.0854 | 0.459 | 0.0000 |

### With max_gap=3 (bursts), max 4 steps

## Top patterns enriched in dropout (n_target=6339, n_other=1661, min_target_matches=317)

| pattern | sup_tgt | sup_oth | lift | wracc | prec | fdr_q |
|---|---|---|---|---|---|---|
| gap=ge_7d | 0.863 | 0.596 | 1.45 | 0.0439 | 0.847 | 0.0000 |
| navigate → gap=ge_7d | 0.474 | 0.276 | 1.72 | 0.0326 | 0.868 | 0.0000 |
| navigate → course_end | 0.527 | 0.375 | 1.41 | 0.0251 | 0.843 | 0.0000 |
| gap=lt_1h → gap=ge_7d | 0.706 | 0.576 | 1.23 | 0.0214 | 0.824 | 0.0000 |
| navigate → gap=lt_1h → gap=ge_7d | 0.478 | 0.350 | 1.37 | 0.0211 | 0.839 | 0.0000 |
| navigate → gap=lt_1h → gap=lt_1h → gap=ge_7d | 0.501 | 0.382 | 1.31 | 0.0196 | 0.834 | 0.0000 |
| navigate → access → gap=lt_1h → gap=ge_7d | 0.399 | 0.293 | 1.36 | 0.0174 | 0.839 | 0.0000 |
| navigate → navigate → gap=lt_1h → gap=ge_7d | 0.306 | 0.201 | 1.52 | 0.0172 | 0.853 | 0.0000 |
| video → gap=ge_7d | 0.344 | 0.241 | 1.43 | 0.0170 | 0.845 | 0.0000 |
| gap=lt_1h → gap=lt_1h → video → gap=ge_7d | 0.344 | 0.241 | 1.42 | 0.0169 | 0.845 | 0.0000 |
| gap=lt_1h → access → video → gap=ge_7d | 0.331 | 0.233 | 1.42 | 0.0162 | 0.845 | 0.0000 |
| access → gap=lt_1h → video → gap=ge_7d | 0.338 | 0.240 | 1.41 | 0.0161 | 0.843 | 0.0000 |
| navigate → access → page_close → gap=ge_7d | 0.308 | 0.211 | 1.46 | 0.0159 | 0.848 | 0.0000 |
| access → access → video → gap=ge_7d | 0.316 | 0.222 | 1.43 | 0.0156 | 0.845 | 0.0000 |
| gap=lt_1h → gap=lt_1h → gap=ge_7d | 0.656 | 0.565 | 1.16 | 0.0149 | 0.816 | 0.0000 |
| navigate → gap=lt_1h → video → gap=ge_7d | 0.211 | 0.121 | 1.74 | 0.0148 | 0.870 | 0.0000 |
| navigate → gap=lt_1h → page_close → gap=ge_7d | 0.324 | 0.234 | 1.38 | 0.0147 | 0.841 | 0.0000 |
| navigate → gap=lt_1h → access → gap=ge_7d | 0.351 | 0.265 | 1.33 | 0.0142 | 0.835 | 0.0000 |
| navigate → access → video → gap=ge_7d | 0.185 | 0.101 | 1.82 | 0.0138 | 0.875 | 0.0000 |
| navigate → access → access → gap=ge_7d | 0.327 | 0.244 | 1.34 | 0.0136 | 0.836 | 0.0000 |
| gap=lt_1h → access → page_close → gap=ge_7d | 0.480 | 0.398 | 1.21 | 0.0135 | 0.821 | 0.0000 |
| page_close → video → gap=ge_7d | 0.298 | 0.217 | 1.37 | 0.0133 | 0.840 | 0.0000 |
| gap=lt_1h → page_close → video → gap=ge_7d | 0.298 | 0.217 | 1.37 | 0.0133 | 0.840 | 0.0000 |
| access → access → page_close → gap=ge_7d | 0.458 | 0.378 | 1.21 | 0.0133 | 0.823 | 0.0000 |
| access → page_close → video → gap=ge_7d | 0.292 | 0.212 | 1.37 | 0.0131 | 0.840 | 0.0000 |
| navigate → gap=lt_1h → video → course_end | 0.230 | 0.151 | 1.52 | 0.0130 | 0.853 | 0.0000 |
| access → gap=lt_1h → gap=ge_7d | 0.573 | 0.494 | 1.16 | 0.0129 | 0.816 | 0.0000 |
| navigate → access → video → course_end | 0.202 | 0.125 | 1.61 | 0.0127 | 0.861 | 0.0000 |
| navigate → navigate → gap=ge_7d | 0.248 | 0.171 | 1.45 | 0.0126 | 0.847 | 0.0000 |
| gap=lt_1h → access → gap=lt_1h → gap=ge_7d | 0.569 | 0.493 | 1.15 | 0.0125 | 0.815 | 0.0000 |
| navigate → access → gap=ge_7d | 0.278 | 0.203 | 1.37 | 0.0124 | 0.840 | 0.0000 |
| navigate → navigate → access → gap=ge_7d | 0.194 | 0.119 | 1.62 | 0.0122 | 0.861 | 0.0000 |
| navigate → navigate → gap=lt_1h → course_end | 0.330 | 0.256 | 1.29 | 0.0122 | 0.831 | 0.0000 |
| gap=lt_1h → gap=lt_1h → gap=lt_1h → gap=ge_7d | 0.634 | 0.562 | 1.13 | 0.0120 | 0.812 | 0.0000 |

## Sample sequences (stratified; study the class differences)

Rendering: events in time order; `|lt_1d|`/`|lt_7d|`/`|ge_7d|` marks a NEW-SESSION gap since the previous event (>1h/>1d/>7d); no marker = same session (<1h).

- [dropout] #115913 (110 events over 30d): navigate access access navigate access access access page_close video access page_close video access page_close access video access video access page_close video navigate page_close access access discussion page_close discussion discussion discussion discussion discussion discussion discussion discussion discussion discussion discussion navigate access access access page_close video access page_close access |lt_1d| navigate access access access page_close access discussion discussion video navigate page_close access access …
- [dropout] #61377 (16 events over 30d): navigate access access navigate access access access page_close video page_close |lt_7d| navigate access access access page_close |ge_7d| course_end
- [dropout] #139448 (2 events over 10d): navigate |ge_7d| course_end
- [dropout] #23238 (26 events over 24d): navigate |lt_1d| access access page_close |lt_7d| navigate navigate access access access page_close access page_close video access access page_close video access access page_close video navigate page_close video access |ge_7d| course_end
- [dropout] #34091 (87 events over 29d): navigate navigate navigate navigate navigate navigate wiki access wiki access wiki navigate access access navigate navigate navigate navigate navigate navigate navigate |lt_7d| navigate navigate navigate navigate navigate navigate wiki access access navigate navigate navigate navigate navigate navigate navigate navigate access access page_close access navigate access wiki access page_close access navigate |lt_1d| page_close |lt_1d| navigate access access access page_close access access page_close access access …
- [dropout] #179798 (3 events over 0d): navigate navigate |lt_1d| course_end
- [persist] #13297 (407 events over 29d): navigate |lt_1d| access access discussion page_close video navigate discussion discussion discussion navigate access access access page_close access page_close video access page_close video |lt_1d| page_close video |lt_1d| navigate access access access page_close access page_close video access access access access access access access page_close |lt_1d| access page_close video access discussion discussion discussion discussion discussion discussion discussion discussion access page_close video problem problem access access problem problem …
- [persist] #69767 (3 events over 20d): navigate |ge_7d| navigate |ge_7d| course_end
- [persist] #149886 (9 events over 8d): navigate navigate access access access problem problem page_close |ge_7d| course_end
- [persist] #7274 (421 events over 22d): access access access navigate navigate access access access access navigate navigate access access access access access access access access access access access page_close access access problem problem access problem problem access access problem problem problem problem access access access access access access navigate wiki |lt_7d| wiki navigate navigate access access access problem problem problem problem problem problem problem problem problem problem …
- [persist] #120896 (73 events over 24d): navigate navigate access access page_close video navigate navigate access access navigate page_close |lt_1d| navigate access access access page_close access access access page_close video access page_close video access page_close video access page_close video access page_close |ge_7d| navigate navigate access access access page_close access page_close video access access page_close video page_close video access access access page_close access access page_close video access access page_close access …
- [persist] #31350 (280 events over 19d): navigate navigate access access access access access access access access access access access page_close video |ge_7d| navigate access access access page_close access access page_close video access access page_close video access access page_close video access access access page_close video access access access access page_close access access page_close video problem problem access access access page_close access access page_close access page_close access navigate page_close …
