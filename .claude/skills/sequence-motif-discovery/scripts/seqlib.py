"""Shared helpers: data loading, pattern matching, and contrast statistics.

Data format (JSONL, one account per line):
    {"id": "a1", "label": "fraud", "events": ["device=new", ["txn=high", "geo=us"]],
     "times": [1710000000, 1710000345]}
Each event is a token string or a list of token strings (itemset event).
"times" is optional: epoch seconds (numbers) or ISO-8601 strings, one per event.
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


def parse_time(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return datetime.fromisoformat(str(v)).timestamp()


def _norm_event(ev):
    if isinstance(ev, str):
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
                 gap_buckets=None):
    """Load and optionally window each sequence to its recent tail.

    recent_seconds: keep only events within this many seconds of the account's
        last event (requires times). recent_events: keep only the last N events.
    Both cut mining/matching cost roughly linearly in what they discard.
    gap_buckets: ascending seconds edges; adds gap=... tokens (requires times).
    """
    excl = set(exclude_tokens)
    ds = Dataset()

    def add(aid, label, events, times):
        if times is not None and len(times) == len(events):
            order = sorted(range(len(events)), key=lambda i: times[i])
            events = [events[i] for i in order]
            times = [times[i] for i in order]
        else:
            times = None
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
                key = (float(r["order"]), parse_time(r.get("time")) or 0.0)
                rows.setdefault(r["id"], (r["label"], []))[1].append(
                    (key, frozenset([r["token"]]), parse_time(r.get("time")))
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
                times = rec.get("times")
                add(rec["id"], rec["label"], [_norm_event(e) for e in rec["events"]],
                    [parse_time(t) for t in times] if times else None)
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

def token_feature(token, sep="="):
    return token.split(sep, 1)[0] if sep in token else token


def pred_match(event, pred, sep="="):
    if "token" in pred:
        return pred["token"] in event
    if "any_of" in pred:
        return any(t in event for t in pred["any_of"])
    if "feature" in pred:
        vals = pred.get("values")
        for tok in event:
            if token_feature(tok, sep) == pred["feature"]:
                if vals is None or tok.split(sep, 1)[-1] in vals:
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
    cons = pattern.get("constraints", {}) or {}
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
    ap.add_argument("--recent-seconds", type=float, default=None,
                    help="keep only events within T seconds of each account's "
                         "last event (needs times; cuts compute)")
    ap.add_argument("--recent-events", type=int, default=None,
                    help="keep only each account's last N events")
    ap.add_argument("--gap-buckets", default=None,
                    help="comma-separated ascending seconds edges, e.g. "
                         "'60,3600,86400': adds gap=lt_1m/... tokens (needs times)")


def windowing_kwargs(args):
    return {
        "recent_seconds": args.recent_seconds,
        "recent_events": args.recent_events,
        "gap_buckets": ([float(x) for x in args.gap_buckets.split(",")]
                        if args.gap_buckets else None),
    }
