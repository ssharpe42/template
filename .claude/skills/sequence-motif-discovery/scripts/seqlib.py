"""Shared helpers: data loading, pattern matching, and contrast statistics.

Data format (JSONL, one account per line):
    {"id": "a1", "label": "fraud", "events": ["device=new", ["txn=high", "geo=us"]],
     "times": [1710000000, 1710000345]}
Each event is a token string, a list of token strings (itemset event), or a
composite string "[EVT:type]--feat1:v1--feat2:v2--feat3:v3" ('--' separates
the tokens; token text must not itself contain '--', single '-' is fine).
Key aliases are accepted: account_id/event_tokens/event_times.
"label" is required per record under any key set; numeric labels (0/1) are
compared as strings, so pass --pos-label 1.
"times" is optional: epoch seconds (numbers) or ISO-8601 strings, one per event.
Token separators: feat=val and feat:val both parse (first '=' wins, then ':');
bracketed [EVT:xxx] tokens parse as feature EVT, value xxx.
Long CSV is also accepted: columns id,label,order,token with optional time column
(epoch seconds or ISO-8601); order breaks ties / substitutes when time is absent.
"""

from __future__ import annotations

import csv
import json
import math
import random
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Dataset:
    ids: list = field(default_factory=list)
    labels: list = field(default_factory=list)
    # seqs[i] = list of frozenset(tokens)
    seqs: list = field(default_factory=list)
    # times[i] = list of epoch-second floats aligned with seqs[i], or None
    times: list = field(default_factory=list)

    def __len__(self):
        return len(self.ids)

    @property
    def has_times(self):
        return any(t is not None for t in self.times)


TIME_UNITS = {"seconds": 1.0, "ms": 0.001, "minutes": 60.0, "hours": 3600.0,
              "days": 86400.0}


def parse_time(v, scale=1.0):
    """Numeric times are multiplied by scale (e.g. 86400 for day-float data) so
    all times are seconds internally; ISO-8601 strings are already absolute."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v) * scale
    try:
        return float(v) * scale
    except ValueError:
        return datetime.fromisoformat(str(v)).timestamp()


_DURATION_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800,
                   "mo": 2629800, "y": 31557600}


def parse_duration(v):
    """'6mo', '90d', '12h', '30m', '45s', or a plain number of seconds."""
    if v is None or isinstance(v, (int, float)):
        return v
    s = str(v).strip().lower()
    for unit in sorted(_DURATION_UNITS, key=len, reverse=True):
        if s.endswith(unit):
            return float(s[: -len(unit)]) * _DURATION_UNITS[unit]
    return float(s)


def _norm_event(ev):
    if isinstance(ev, str):
        if "--" in ev:  # composite: "[EVT:x]--f1:v1--f2:v2"
            return frozenset(p for p in ev.split("--") if p)
        return frozenset([ev])
    return frozenset(str(t) for t in ev)


def humanize_seconds(s):
    for div, unit in ((86400, "d"), (3600, "h"), (60, "m")):
        if s >= div:
            return f"{s / div:g}{unit}"
    return f"{s:g}s"


def add_gap_tokens(seq, times, edges):
    """Merge a gap=<bucket> token into each event (after the first) describing the
    time since the previous event. edges: ascending seconds, e.g. [60, 3600, 86400]
    -> gap=lt_1m / gap=lt_1h / gap=lt_1d / gap=ge_1d."""
    out = [seq[0]]
    for i in range(1, len(seq)):
        delta = times[i] - times[i - 1]
        tok = f"gap=ge_{humanize_seconds(edges[-1])}"
        for e in edges:
            if delta < e:
                tok = f"gap=lt_{humanize_seconds(e)}"
                break
        out.append(seq[i] | {tok})
    return out


def load_dataset(path, exclude_tokens=(), recent_seconds=None, recent_events=None,
                 gap_buckets=None, random_cut_label=None, random_cut_seed=0,
                 min_span_seconds=None, time_unit="seconds"):
    """Load and optionally window each sequence to its recent tail.

    recent_seconds: keep only events within this duration of the account's
        last event (requires times). recent_events: keep only the last N events.
    Both cut mining/matching cost roughly linearly in what they discard.
    gap_buckets: ascending seconds edges; adds gap=... tokens (requires times).
    random_cut_label: truncate each account with this label at a uniformly random
        cut point (a "random view"), mimicking the censoring of the other class
        whose sequences end at a determined cutoff (e.g. fraud pre-truncated
        before label leakage). One view per account keeps significance stats
        valid; vary random_cut_seed across runs to check pattern stability.
    min_span_seconds: DROP accounts whose history (after any random cut, before
        recent windowing) spans less than this duration — pair with
        recent_seconds so every kept account contributes the same observation
        period and window length can't leak the label.
    Durations may be given as '6mo'/'90d'-style strings.
    time_unit: unit of NUMERIC time values in the data ('seconds', 'ms',
        'minutes', 'hours', 'days'). Decimal day-floats like 1.1 (= 1 day +
        2.4h) scale linearly to seconds internally, so duration strings and
        DSL time constraints keep meaning real time regardless of input unit.
    """
    excl = set(exclude_tokens)
    recent_seconds = parse_duration(recent_seconds)
    min_span_seconds = parse_duration(min_span_seconds)
    tscale = TIME_UNITS[time_unit]
    cut_rng = random.Random(random_cut_seed)
    ds = Dataset()

    def add(aid, label, events, times):
        if times is not None and len(times) == len(events):
            order = sorted(range(len(events)), key=lambda i: times[i])
            events = [events[i] for i in order]
            times = [times[i] for i in order]
        else:
            times = None
        if times is None and (recent_seconds is not None
                              or min_span_seconds is not None):
            raise ValueError(f"account {aid} has no event times but a "
                             "time-based window/filter was requested")
        if random_cut_label is not None and label == random_cut_label and len(events) > 1:
            k = cut_rng.randint(1, len(events))
            events = events[:k]
            times = times[:k] if times else None
        if min_span_seconds is not None:
            if len(times) < 2 or times[-1] - times[0] < min_span_seconds:
                return  # drop: not enough observed history for a fair window
        if recent_seconds is not None and times:
            cut = times[-1] - recent_seconds
            k = next((i for i, t in enumerate(times) if t >= cut), len(times) - 1)
            events, times = events[k:], times[k:]
        if recent_events is not None:
            events = events[-recent_events:]
            times = times[-recent_events:] if times else None
        if gap_buckets and times and len(events) > 1:
            events = add_gap_tokens(events, times, gap_buckets)
        if excl:
            keep = [i for i, e in enumerate(events) if e - excl]
            events = [events[i] - excl for i in keep]
            times = [times[i] for i in keep] if times else None
        ds.ids.append(str(aid))
        ds.labels.append(str(label))
        ds.seqs.append(events)
        ds.times.append(times)

    if path.endswith(".csv"):
        rows = {}
        with open(path, newline="") as f:
            for r in csv.DictReader(f):
                t = parse_time(r.get("time"), tscale)
                key = (float(r["order"]), t or 0.0)
                rows.setdefault(r["id"], (r["label"], []))[1].append(
                    (key, frozenset([r["token"]]), t)
                )
        for aid, (label, evs) in rows.items():
            evs.sort(key=lambda x: x[0])
            times = [t for _, _, t in evs]
            add(aid, label, [e for _, e, _ in evs],
                times if all(t is not None for t in times) else None)
    else:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                aid = rec.get("id", rec.get("account_id"))
                events = rec.get("events", rec.get("event_tokens"))
                times = rec.get("times", rec.get("event_times"))
                if aid is None or events is None:
                    raise ValueError(f"record missing id/account_id or "
                                     f"events/event_tokens: {line[:120]}")
                if "label" not in rec:
                    raise ValueError(f"account {aid} has no 'label' field — every "
                                     "record needs one (e.g. fraud/good)")
                add(aid, rec["label"], [_norm_event(e) for e in events],
                    [parse_time(t, tscale) for t in times] if times else None)
    return ds


def stratified_split(ds, test_frac, seed):
    """Returns (train_idx, test_idx), stratified by label."""
    rng = random.Random(seed)
    by_label = {}
    for i, lab in enumerate(ds.labels):
        by_label.setdefault(lab, []).append(i)
    train, test = [], []
    for idxs in by_label.values():
        rng.shuffle(idxs)
        k = int(round(len(idxs) * test_frac))
        test.extend(idxs[:k])
        train.extend(idxs[k:])
    return sorted(train), sorted(test)


# ---------------------------------------------------------------- predicates

def token_split(token, sep="="):
    """(feature, value) for a token. Bracketed type tokens like '[EVT:login]'
    parse as ('EVT', 'login'); plain tokens split on sep, falling back to ':'
    (so feat=val and feat:val styles both work); else (token, token)."""
    if token.startswith("[") and token.endswith("]") and ":" in token:
        return tuple(token[1:-1].split(":", 1))
    if sep in token:
        return tuple(token.split(sep, 1))
    if ":" in token:
        return tuple(token.split(":", 1))
    return token, token


def token_feature(token, sep="="):
    return token_split(token, sep)[0]


def pred_match(event, pred, sep="="):
    if isinstance(pred, str):
        pred = {"token": pred}
    if "token" in pred:
        return pred["token"] in event
    if "any_of" in pred:
        return any(t in event for t in pred["any_of"])
    if "all_of" in pred:
        # conjunction over the SAME event (itemset events)
        return all(pred_match(event, p, sep) for p in pred["all_of"])
    if "feature" in pred:
        vals = pred.get("values")
        for tok in event:
            f, v = token_split(tok, sep)
            if f == pred["feature"] and (vals is None or v in vals):
                return True
        return False
    raise ValueError(f"unknown predicate: {pred}")


# ------------------------------------------------------------------ matching

def _step_ok(seq, times, cons, i, prev, first):
    """Constraint checks for matching steps[si] at index i (prev/first = indices
    of previous/first matched step, or None). Returns 'stop' when no later i can
    satisfy either (positions and times are both increasing)."""
    if prev is not None:
        mg = cons.get("max_gap")
        if mg is not None and i - prev - 1 > mg:
            return "stop"
        mtg = cons.get("max_time_gap")
        if mtg is not None and times and times[i] - times[prev] > mtg:
            return "stop"
    if first is not None:
        w = cons.get("window")
        if w is not None and i - first + 1 > w:
            return "stop"
        tw = cons.get("time_window")
        if tw is not None and times and times[i] - times[first] > tw:
            return "stop"
    return "ok"


def _find_from(seq, times, steps, cons, si, prev, first):
    """Backtracking search; returns matched index of the last step, or None."""
    if si == len(steps):
        return prev
    for i in range((prev + 1) if prev is not None else 0, len(seq)):
        if _step_ok(seq, times, cons, i, prev, first) == "stop":
            break
        if not pred_match(seq[i], steps[si]):
            continue
        end = _find_from(seq, times, steps, cons, si + 1, i,
                         first if first is not None else i)
        if end is not None:
            return end
    return None


def pattern_matches(seq, pattern, times=None):
    cons = dict(pattern.get("constraints", {}) or {})
    for k in ("max_time_gap", "time_window"):
        if k in cons:
            cons[k] = parse_duration(cons[k])  # allow '10m' / '6h' in the DSL
    steps = pattern["steps"]
    for pred in pattern.get("absent", []) or []:
        if any(pred_match(ev, pred) for ev in seq):
            return False
    scope = cons.get("scope", "anywhere")
    win = cons.get("window")
    if scope == "prefix" and win is not None:
        seq, times = seq[:win], times[:win] if times else None
    elif scope == "suffix" and win is not None:
        seq, times = seq[-win:], times[-win:] if times else None

    need = pattern.get("min_count", 1)
    start, found = 0, 0
    while start < len(seq):
        sub_t = times[start:] if times else None
        end = _find_from(seq[start:], sub_t, steps, cons, 0, None, None)
        if end is None:
            return False
        found += 1
        if found >= need:
            return True
        start += end + 1
    return False


# ---------------------------------------------------------------- statistics

def _log_comb(n, k):
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)


def fisher_greater(a, n_pos, c, n_neg):
    """One-sided Fisher exact: P(matched positives >= a) under hypergeometric."""
    n, big_n, big_k = a + c, n_pos + n_neg, n_pos
    denom = _log_comb(big_n, n)
    p = 0.0
    for k in range(a, min(n, big_k) + 1):
        if n - k > big_n - big_k:
            continue
        p += math.exp(_log_comb(big_k, k) + _log_comb(big_n - big_k, n - k) - denom)
    return min(1.0, p)


def _entropy(p):
    if p <= 0 or p >= 1:
        return 0.0
    return -(p * math.log2(p) + (1 - p) * math.log2(1 - p))


def contrast_stats(a, n_pos, c, n_neg):
    """All contrast metrics for a pattern matching a/n_pos positives, c/n_neg negatives."""
    big_n = n_pos + n_neg
    b, d = n_pos - a, n_neg - c
    n_match = a + c
    sup_pos = a / n_pos if n_pos else 0.0
    sup_neg = c / n_neg if n_neg else 0.0
    prec = a / n_match if n_match else 0.0
    base = n_pos / big_n
    wracc = (n_match / big_n) * (prec - base) if n_match else 0.0
    lift = ((a + 0.5) / (n_pos + 1)) / ((c + 0.5) / (n_neg + 1))
    odds = ((a + 0.5) * (d + 0.5)) / ((b + 0.5) * (c + 0.5))
    ig = _entropy(base)
    if n_match and n_match < big_n:
        ig -= (n_match / big_n) * _entropy(a / n_match)
        ig -= ((big_n - n_match) / big_n) * _entropy(b / (big_n - n_match))
    return {
        "n_pos_match": a, "n_neg_match": c,
        "support_pos": round(sup_pos, 4), "support_neg": round(sup_neg, 4),
        "precision": round(prec, 4), "recall_pos": round(sup_pos, 4),
        "lift": round(lift, 3), "odds_ratio": round(odds, 3),
        "wracc": round(wracc, 5), "info_gain": round(ig, 5),
        "fisher_p": fisher_greater(a, n_pos, c, n_neg),
    }


def bh_fdr(pvals):
    """Benjamini-Hochberg q-values, preserving input order."""
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    q = [0.0] * m
    prev = 1.0
    for rank_from_end, i in enumerate(reversed(order)):
        rank = m - rank_from_end
        prev = min(prev, pvals[i] * m / rank)
        q[i] = prev
    return q


def is_subsequence(small, big):
    """True if token-list `small` is a subsequence of token-list `big`."""
    it = iter(big)
    return all(tok in it for tok in small)


def add_windowing_args(ap):
    """Shared CLI flags for time-aware preprocessing (all scripts)."""
    ap.add_argument("--recent-seconds", default=None,
                    help="keep only events within this duration of each "
                         "account's last event, e.g. '6mo', '90d', or seconds "
                         "(needs times; cuts compute)")
    ap.add_argument("--recent-events", type=int, default=None,
                    help="keep only each account's last N events")
    ap.add_argument("--min-span", default=None,
                    help="drop accounts with less observed history than this "
                         "duration (after random cut), e.g. '6mo' — pair with "
                         "--recent-seconds for equal observation windows")
    ap.add_argument("--gap-buckets", default=None,
                    help="comma-separated ascending gap edges, e.g. "
                         "'60,1h,1d' or seconds: adds gap=lt_1m/... tokens "
                         "(needs times)")
    ap.add_argument("--random-cut-label", default=None,
                    help="truncate accounts with this label at a random cut "
                         "point (random view), e.g. 'good' — mimics fraud "
                         "sequences pre-truncated at a leak cutoff (D2c)")
    ap.add_argument("--random-cut-seed", type=int, default=0)
    ap.add_argument("--time-unit", default="seconds", choices=sorted(TIME_UNITS),
                    help="unit of numeric time values in the data (e.g. 'days' "
                         "for decimal day-floats like 1.1); everything is "
                         "converted to seconds on load so duration strings "
                         "('6mo', '1h') stay meaningful")


def windowing_kwargs(args):
    return {
        "recent_seconds": args.recent_seconds,
        "recent_events": args.recent_events,
        "min_span_seconds": args.min_span,
        "gap_buckets": ([parse_duration(x) for x in args.gap_buckets.split(",")]
                        if args.gap_buckets else None),
        "random_cut_label": args.random_cut_label,
        "random_cut_seed": args.random_cut_seed,
        "time_unit": args.time_unit,
    }
