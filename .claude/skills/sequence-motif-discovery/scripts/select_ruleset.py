#!/usr/bin/env python3
"""Phase-3 rule-set selection, deterministically: score every candidate pattern
on the selection split, drop near-duplicates (match-set Jaccard), then greedy
forward selection maximizing the rule set's train AUC (log-odds scoring, both
directions contribute with signed weights).

    python select_ruleset.py data.jsonl --patterns cands.json [more.json ...] \
        --pos-label fraud --split 0.3 --seed 42 --max-rules 12 --out final.json

Only the train part of the split is used; the holdout stays untouched for
Phase 4. Accepts both mined-candidate files and DSL hypothesis files (mixed).
"""

from __future__ import annotations

import argparse
import json
import math

from seqlib import (add_jobs_arg, add_windowing_args, contrast_stats,
                    load_dataset, stratified_split, windowing_kwargs)
from evaluate_ruleset import auc_score, match_matrix
from verify_patterns import as_dsl


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("data")
    ap.add_argument("--patterns", nargs="+", required=True)
    ap.add_argument("--pos-label", required=True)
    ap.add_argument("--split", type=float, default=None,
                    help="holdout fraction excluded from selection")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--max-rules", type=int, default=12)
    ap.add_argument("--jaccard", type=float, default=0.6,
                    help="near-duplicate threshold on match sets")
    ap.add_argument("--min-abs-wracc", type=float, default=0.002,
                    help="prefilter: drop patterns with |wracc| below this")
    ap.add_argument("--prefilter-top", type=int, default=80,
                    help="only the strongest N by |wracc| PER DIRECTION enter "
                         "the greedy search (direction-blind filtering would "
                         "let a dominant direction crowd the other out)")
    ap.add_argument("--objective", default="coverage",
                    choices=["coverage", "auc"],
                    help="greedy criterion: 'coverage' adds the rule covering "
                         "the most not-yet-covered accounts of its own enriched "
                         "class (the Phase-3 default; yields a full-size, "
                         "diverse set); 'auc' adds the rule that most improves "
                         "train AUC under fixed log-odds weights (finds the "
                         "minimal discriminative core, then saturates)")
    ap.add_argument("--min-gain", type=float, default=None,
                    help="stop when marginal gain drops below this "
                         "(default: 0.01 for coverage, 0.001 for auc)")
    ap.add_argument("--exclude-tokens", nargs="*", default=[])
    ap.add_argument("--out", required=True)
    add_jobs_arg(ap)
    add_windowing_args(ap)
    args = ap.parse_args()

    patterns, seen = [], set()
    for path in args.patterns:
        with open(path) as f:
            for i, p in enumerate(json.load(f)):
                dsl = as_dsl(p, len(patterns))
                key = json.dumps(
                    {k: dsl[k] for k in
                     ("steps", "constraints", "absent", "min_count")
                     if k in dsl}, sort_keys=True)
                if key not in seen:
                    seen.add(key)
                    patterns.append(dsl)

    ds = load_dataset(args.data, exclude_tokens=args.exclude_tokens,
                      **windowing_kwargs(args))
    idxs = (stratified_split(ds, args.split, args.seed)[0] if args.split
            else list(range(len(ds))))
    ys_of = {i: 1 if ds.labels[i] == args.pos_label else 0 for i in idxs}
    n_pos = sum(ys_of.values())
    n_neg = len(idxs) - n_pos

    fired = match_matrix(ds, idxs, patterns, args.jobs)
    idx_set = set(idxs)
    fired = [hits & idx_set for hits in fired]

    stats, weights = [], []
    for hits in fired:
        a = sum(1 for i in hits if ys_of[i])
        c = len(hits) - a
        st = contrast_stats(a, n_pos, c, n_neg)
        b, d = n_pos - a, n_neg - c
        weights.append(math.log(((a + 0.5) * (d + 0.5))
                                / ((b + 0.5) * (c + 0.5))))
        stats.append(st)

    order = sorted(range(len(patterns)), key=lambda k: -abs(stats[k]["wracc"]))
    order = [k for k in order if abs(stats[k]["wracc"]) >= args.min_abs_wracc]
    by_dir = {True: [], False: []}
    for k in order:
        by_dir[weights[k] > 0].append(k)
    order = sorted(by_dir[True][: args.prefilter_top]
                   + by_dir[False][: args.prefilter_top],
                   key=lambda k: -abs(stats[k]["wracc"]))

    kept = []
    for k in order:  # near-duplicate pruning, strongest-first
        if any(fired[k] and fired[j] and
               len(fired[k] & fired[j]) / len(fired[k] | fired[j]) > args.jaccard
               for j in kept):
            continue
        kept.append(k)

    ys = [ys_of[i] for i in idxs]
    min_gain = args.min_gain if args.min_gain is not None else (
        0.001 if args.objective == "auc" else 0.01)
    chosen = []
    if args.objective == "auc":
        base_scores = {i: 0.0 for i in idxs}
        cur_auc = 0.5
        while len(chosen) < args.max_rules:
            best, best_auc = None, cur_auc
            for k in kept:
                if k in chosen:
                    continue
                scores = [base_scores[i]
                          + (weights[k] if i in fired[k] else 0.0)
                          for i in idxs]
                a = auc_score(scores, ys)
                if a > best_auc + 1e-12:
                    best, best_auc = k, a
            if best is None or best_auc - cur_auc < min_gain:
                break
            chosen.append(best)
            for i in fired[best]:
                base_scores[i] += weights[best]
            cur_auc = best_auc
            print(f"+ {patterns[best].get('id','?'):>6} "
                  f"{patterns[best].get('name','')[:46]:<46} "
                  f"wracc={stats[best]['wracc']:+.4f} "
                  f"-> train AUC {cur_auc:.4f}")
    else:
        # coverage: each rule targets the class it is enriched in; add the rule
        # covering the largest not-yet-covered fraction of its own class
        pos_all = {i for i in idxs if ys_of[i]}
        neg_all = set(idxs) - pos_all
        covered = {True: set(), False: set()}  # is_pos_direction -> accounts
        while len(chosen) < args.max_rules:
            best, best_gain, best_dir = None, min_gain, None
            for k in kept:
                if k in chosen:
                    continue
                is_pos = weights[k] > 0
                target = pos_all if is_pos else neg_all
                gain = (len((fired[k] & target) - covered[is_pos])
                        / max(1, len(target)))
                if gain > best_gain + 1e-12:
                    best, best_gain, best_dir = k, gain, is_pos
            if best is None:
                break
            chosen.append(best)
            covered[best_dir] |= fired[best] & (pos_all if best_dir else neg_all)
            print(f"+ {patterns[best].get('id','?'):>6} "
                  f"{patterns[best].get('name','')[:46]:<46} "
                  f"wracc={stats[best]['wracc']:+.4f} "
                  f"dir={'pos' if best_dir else 'neg'} "
                  f"new_cover=+{best_gain:.1%}")
        scores = [sum(weights[k] for k in chosen if i in fired[k])
                  for i in idxs]
        cur_auc = auc_score(scores, ys)

    out = []
    for k in chosen:
        p = dict(patterns[k])
        p["train_selection_stats"] = stats[k]
        out.append(p)
    with open(args.out, "w") as f:
        json.dump(out, f, indent=1)
    print(f"\nSelected {len(out)} rules (train AUC {cur_auc:.4f}) -> {args.out}")


if __name__ == "__main__":
    main()
