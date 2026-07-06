"""Shared helpers: data loading, pattern matching, and contrast statistics.

Data format (JSONL, one account per line):
    {"id": "a1", "label": "fraud", "events": ["device=new", ["txn=high", "geo=us"]]}
Each event is a token string or a list of token strings (itemset event).
Long CSV is also accepted: columns id,label,order,token (header required).
"""

from __future__ import annotations

import csv
import json
import math
import random
from dataclasses import dataclass, field


@dataclass
class Dataset:
    ids: list = field(default_factory=list)
    labels: list = field(default_factory=list)
    # seqs[i] = list of frozenset(tokens)
    seqs: list = field(default_factory=list)

    def __len__(self):
        return len(self.ids)


def _norm_event(ev):
    if isinstance(ev, str):
        return frozenset([ev])
    return frozenset(str(t) for t in ev)


def load_dataset(path, exclude_tokens=()):
    excl = set(exclude_tokens)
    ds = Dataset()
    if path.endswith(".csv"):
        rows = {}
        with open(path, newline="") as f:
            for r in csv.DictReader(f):
                rows.setdefault(r["id"], (r["label"], []))[1].append(
                    (float(r["order"]), r["token"])
                )
        for aid, (label, evs) in rows.items():
            evs.sort(key=lambda x: x[0])
            ds.ids.append(aid)
            ds.labels.append(label)
            ds.seqs.append([frozenset([t]) - excl or frozenset() for _, t in evs])
    else:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                ds.ids.append(str(rec["id"]))
                ds.labels.append(str(rec["label"]))
                ds.seqs.append([_norm_event(e) - excl for e in rec["events"]])
    if excl:
        ds.seqs = [[e for e in seq if e] for seq in ds.seqs]
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

def _find_from(seq, steps, si, pos, first_pos, max_gap, window):
    """Backtracking search for steps[si:] with steps[si] at index >= pos."""
    if si == len(steps):
        return True
    lo = pos
    hi = len(seq) if (max_gap is None or si == 0) else min(len(seq), pos + max_gap + 1)
    for i in range(lo, hi):
        if not pred_match(seq[i], steps[si]):
            continue
        fp = i if si == 0 else first_pos
        if window is not None and i - fp + 1 > window:
            break
        if _find_from(seq, steps, si + 1, i + 1, fp, max_gap, window):
            return True
    return False


def _match_once(seq, steps, max_gap, window, scope, win):
    if scope == "prefix" and win is not None:
        seq = seq[:win]
    elif scope == "suffix" and win is not None:
        seq = seq[-win:]
    return _find_from(seq, steps, 0, 0, 0, max_gap, window)


def _count_matches(seq, steps, max_gap, window):
    """Greedy count of non-overlapping matches (left to right)."""
    count, start = 0, 0
    while start < len(seq):
        end = _match_end(seq, steps, 0, start, 0, max_gap, window)
        if end is None:
            break
        count += 1
        start = end + 1
    return count


def _match_end(seq, steps, si, pos, first_pos, max_gap, window):
    if si == len(steps):
        return first_pos - 1  # caller adds nothing; overwritten below
    lo = pos
    hi = len(seq) if (max_gap is None or si == 0) else min(len(seq), pos + max_gap + 1)
    for i in range(lo, hi):
        if not pred_match(seq[i], steps[si]):
            continue
        fp = i if si == 0 else first_pos
        if window is not None and i - fp + 1 > window:
            break
        if si == len(steps) - 1:
            return i
        sub = _match_end(seq, steps, si + 1, i + 1, fp, max_gap, window)
        if sub is not None:
            return sub
    return None


def pattern_matches(seq, pattern):
    cons = pattern.get("constraints", {}) or {}
    max_gap = cons.get("max_gap")
    window = cons.get("window")
    scope = cons.get("scope", "anywhere")
    steps = pattern["steps"]
    for pred in pattern.get("absent", []) or []:
        if any(pred_match(ev, pred) for ev in seq):
            return False
    min_count = pattern.get("min_count", 1)
    if min_count <= 1:
        return _match_once(seq, steps, max_gap, window, scope, window)
    return _count_matches(seq, steps, max_gap, window) >= min_count


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
