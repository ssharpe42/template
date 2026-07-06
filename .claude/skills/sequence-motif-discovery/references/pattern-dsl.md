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
  "constraints": {"max_gap": 3, "window": 10, "scope": "anywhere"},
  "absent": [{"token": "kyc=passed"}],
  "min_count": 1
}
```

## Semantics

- **steps**: matched *in order* as a subsequence of the account's events. Each step is one
  predicate evaluated against a single event (an event = set of tokens):
  - `{"token": T}` — event contains exactly token T.
  - `{"any_of": [T1, T2]}` — event contains any listed token.
  - `{"feature": F}` — event contains any token of feature F (value wildcard).
  - `{"feature": F, "values": [v1, v2]}` — event contains `F=v1` or `F=v2`.
- **constraints** (all optional):
  - `max_gap`: max number of *intervening* events between consecutive matched steps
    (0 = strictly adjacent). Omit for unlimited.
  - `window`: max span in events from first to last matched step (inclusive).
  - `scope`: `"anywhere"` (default), `"prefix"` (match must start in first `window`
    events), `"suffix"` (must end in last `window` events; requires `window`).
- **absent**: list of predicates (same forms as steps); the pattern only matches if NO
  event in the whole sequence satisfies any of them. Keep to ≤ 1 per pattern.
- **min_count**: pattern must occur at least this many times as non-overlapping matches
  (greedy left-to-right count; default 1).

Matching uses backtracking, so gap/window constraints are exact, not greedy-approximate.

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
- Add `max_gap`/`window` only when verification shows it *raises precision*; unconstrained
  patterns are easier to deploy.
- An `absent` clause on a whole history is expensive in some engines — mention that in
  the rule card when used.
