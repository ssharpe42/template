# Pattern DSL

A pattern is a JSON object. A file of hypotheses is a JSON array of them.
Design goal: everything expressible here is trivially portable to a rule engine.

```json
{
  "id": "F03",
  "name": "new device then rapid high-value spend, no KYC",
  "steps": [
    {"token": "device=new"},
    {"any_of": ["txn_amt=high", "txn_amt=very_high"]},
    {"feature": "login_geo", "values": ["mismatch", "new_country"]}
  ],
  "constraints": {"max_gap": 3, "window": 10, "max_time_gap": 3600, "scope": "anywhere"},
  "absent": [{"token": "kyc=passed"}],
  "min_count": 1
}
```

## Semantics

- **steps**: matched *in order* as a subsequence of the account's events. Each step is one
  predicate evaluated against a single event (an event = set of tokens):
  - `{"token": T}` — event contains exactly token T.
  - `{"any_of": [T1, T2]}` — event contains any listed token.
  - `{"all_of": [p1, p2, ...]}` — event satisfies ALL sub-predicates (conjunction over
    the SAME itemset event; sub-predicates are any form here, bare token strings OK).
    This is how "a transaction event with a high amount on a new device" is written for
    multi-token events: `{"all_of": ["[EVT:txn]", "txn_amt=high", "device=new"]}`.
  - `{"feature": F}` — event contains any token of feature F (value wildcard).
  - `{"feature": F, "values": [v1, v2]}` — event contains `F=v1` or `F=v2`.

Token parsing: `feat=val` splits on `=`; bracketed type tokens `[EVT:xxx]` parse as
feature `EVT`, value `xxx` — so `{"feature": "EVT", "values": ["login", "txn"]}` anchors
a step on event *type* regardless of its other feature tokens.
- **constraints** (all optional; see "Timing semantics, precisely" below):
  - `max_gap`: max number of *intervening* events between **consecutive** matched steps
    (0 = strictly adjacent). Omit for unlimited.
  - `window`: max span **in events** from the **first to the last** matched step
    (inclusive). This is about the motif's extent — NOT about position within the
    account's history (that is the observation window, a preprocessing concept).
  - `max_time_gap`: max time between **consecutive** matched steps (requires event
    times in the data; ignored when an account has no times).
  - `time_window`: max time from the **first to the last** matched step — i.e. "the
    whole motif happens within X". Durations accept `'10m'`/`'6h'`-style strings or
    seconds.
  - `scope`: `"anywhere"` (default), `"prefix"` (match must start in first `window`
    events), `"suffix"` (must end in last `window` events; requires `window`).
- **absent**: list of predicates (same forms as steps); the pattern only matches if NO
  event in the whole sequence satisfies any of them. Keep to ≤ 1 per pattern.
- **min_count**: pattern must occur at least this many times as non-overlapping matches
  (greedy left-to-right count; default 1).

Matching uses backtracking, so gap/window constraints are exact, not greedy-approximate.
It stays fast on very long sequences (10k+ events): each step's predicate is evaluated
at most once per event (memoized candidate cursors), and constraints become scan bounds
rather than per-event checks, so tight windows only ever touch their neighborhoods.

## Timing semantics, precisely

Three distinct concepts; do not conflate them.

Say a pattern's steps S1..Sk match events e1..ek at times t1..tk. All four DSL
constraints apply to the **matched events only** — events in between are irrelevant
except through `max_gap`:

| constraint | applies to | unit | meaning |
|---|---|---|---|
| `max_gap` | consecutive pairs (e_i, e_i+1) | events | ≤ N unmatched events strictly between them |
| `max_time_gap` | consecutive pairs (e_i, e_i+1) | time | t_(i+1) − t_i ≤ D, for EVERY pair |
| `window` | first → last (e1, ek) | events | motif spans ≤ N events, inclusive |
| `time_window` | first → last (e1, ek) | time | t_k − t_1 ≤ D ("whole motif within D") |

**Events vs time — `max_gap` vs `max_time_gap`.** These are the same constraint
measured in different units. Matching pattern `A → B` against:

```
event:  A     x     x     B
time:   9:00  9:01  9:02  11:30
```

- `max_gap` counts *other events between the matched steps*: two here (`x`, `x`), so
  `max_gap: 1` fails and `max_gap: 2` matches. The clock is irrelevant — those events
  could be minutes or months apart.
- `max_time_gap` measures *elapsed time between the matched steps*: 2.5h here, so
  `max_time_gap: "1h"` fails and `max_time_gap: "3h"` matches. The number of
  intervening events is irrelevant — zero or fifty.

They capture different behaviors: `max_gap: 0` means "B is the *very next thing* the
account did after A" (nothing in between, however long the wait); `max_time_gap: "10m"`
means "B happened *quickly* after A" (even if the account did ten other things in those
ten minutes). For an active account these diverge sharply — many events per minute
consumes an event-count gap fast while a time gap stays open; a dormant account is the
reverse. The same units distinction holds for `window` (events, first→last inclusive)
vs `time_window` (time, first→last). When the data has timestamps, prefer the time
versions; the event-count versions exist for datasets without times.

**Per-hop vs total span — `max_time_gap` vs `time_window`.** Also not interchangeable:
3 steps with `max_time_gap: "1h"` may span up to 2h total; `time_window: "1h"` bounds
the total span regardless of how the gaps are distributed. Use `time_window` for
"burst" motifs (this is the classic "gap between first and last event of the motif"
definition); use `max_time_gap` for "chain" motifs where every hand-off must be quick.

**The observation window is a different thing entirely.** `--recent-seconds 6mo`
(preprocessing, all scripts) decides how much history before each account's END —
fraud: the pre-leak cutoff; good: the random cut point — is kept in the dataset at all.
It anchors at the sequence end and applies before any matching. DSL constraints never
reference the sequence end unless you explicitly use `scope: "suffix"`.

Worked example — account history (observation window already applied), pattern
`A → B → C`:

```
time:    day 0      day 3      day 4      day 4+10min   day 9        <- END (cut)
event:   A          x          B          C             y
```

- matched events: A(day 0), B(day 4), C(day 4 + 10min)
- `max_gap: 0` fails (x sits between A and B); `max_gap: 1` matches
- `max_time_gap: "2d"` fails (A→B is 4d); `max_time_gap: "5d"` matches
- `time_window: "3d"` fails (A→C spans ~4d); `time_window: "5d"` matches
- `window: 4` matches (A..C spans 4 events inclusive)
- the trailing y and the distance to the END (day 9) are irrelevant to all of the above

## Rule-engine translation

Each construct maps 1:1 to streaming rule-engine primitives: `steps`+`max_gap`/`window`
is a CEP "followed-by within N events" chain; `absent` is a NOT-exists guard;
`min_count` is an occurrence counter. When writing the final report, emit for each rule:

```
IF   event(device=new)
THEN WITHIN 3 events: event(txn_amt IN {high, very_high})
THEN WITHIN 3 events: event(login_geo IN {mismatch, new_country})
AND  NEVER event(kyc=passed)            -- over account history
=>   FLAG F03
```

## Authoring guidance for the LLM

- Prefer `any_of`/`values` over separate near-duplicate patterns.
- Add `max_gap`/`window` (or their time variants) only when verification shows it
  *raises precision*; unconstrained patterns are easier to deploy.
- When event times exist, prefer `max_time_gap`/`time_window` over event-count gaps —
  "within 10 minutes" is more meaningful to analysts and rule engines than "within 3
  events", and burstiness is usually the real fraud signal.
- An `absent` clause on a whole history is expensive in some engines — mention that in
  the rule card when used.
