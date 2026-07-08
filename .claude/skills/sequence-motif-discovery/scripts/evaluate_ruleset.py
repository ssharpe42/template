#!/usr/bin/env python3
"""Score accounts with a verified rule set and report classification metrics
(ROC AUC first) so a motif rule set can be compared against published
sequence-classification benchmarks.

    # fit weights on train.jsonl, evaluate on test.jsonl (benchmark mode)
    python evaluate_ruleset.py test.jsonl --patterns final.json \
        --pos-label dropout --fit-data train.jsonl

    # no separate test file: fit on the train split, evaluate on the holdout
    python evaluate_ruleset.py data.jsonl --patterns final.json \
        --pos-label fraud --split 0.3 --seed 42

Scoring: each pattern is a binary feature (does it match the sequence?).
  - logodds (default): naive-Bayes — fired patterns add their fit-split
    log-odds-ratio; interpretable, instant, no dependencies.
  - logistic: pure-python L2 logistic regression on the same binary features
    (handles correlated/overlapping rules better).
  - count: signed rule count (+1 for rules whose fit-split lift > 1, else -1).
The AUC is computed rank-based (Mann-Whitney, tie-corrected).
"""

from __future__ import annotations

import argparse
import json
import math

from seqlib import (add_jobs_arg, add_windowing_args, chunk_bounds,
                    contrast_stats, load_dataset, parallel_env,
                    pattern_matches, resolve_jobs, run_parallel,
                    stratified_split, windowing_kwargs)
from verify_patterns import as_dsl


def match_matrix(ds, idxs, patterns, jobs=0):
    """fired[k] = set of account indices (into ds) matched by pattern k."""
    chunks = [idxs[lo:hi]
              for lo, hi in chunk_bounds(len(idxs), resolve_jobs(jobs) * 8)]
    fired = [set() for _ in patterns]
    for part in run_parallel(_match_chunk, chunks, jobs,
                             {"ds": ds, "patterns": patterns}):
        for k, hits in enumerate(part):
            fired[k].update(hits)
    return fired


def _match_chunk(chunk):
    env = parallel_env()
    ds, patterns = env["ds"], env["patterns"]
    return [[i for i in chunk if pattern_matches(ds.seqs[i], pat, ds.times[i])]
            for pat in patterns]


def auc_score(scores, ys):
    """Rank-based ROC AUC with tie correction."""
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    ranks = [0.0] * len(scores)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        r = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = r
        i = j + 1
    n_pos = sum(ys)
    n_neg = len(ys) - n_pos
    if not n_pos or not n_neg:
        return float("nan")
    rank_sum = sum(r for r, y in zip(ranks, ys) if y)
    return (rank_sum - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def fit_logodds(fired, idxs, ys_of):
    """Per-pattern smoothed log odds ratio on the fit split."""
    n_pos = sum(1 for i in idxs if ys_of[i])
    n_neg = len(idxs) - n_pos
    idx_set = set(idxs)
    w = []
    for hits in fired:
        a = sum(1 for i in hits if i in idx_set and ys_of[i])
        c = sum(1 for i in hits if i in idx_set) - a
        b, d = n_pos - a, n_neg - c
        w.append(math.log(((a + 0.5) * (d + 0.5)) / ((b + 0.5) * (c + 0.5))))
    return w


def fit_logistic(feats, ys, l2=1e-3, iters=300, lr=0.5):
    """Full-batch GD on binary features; feats[i] = list of fired pattern ids."""
    n, k = len(ys), 1 + max((max(f) + 1 if f else 0) for f in feats)
    w = [0.0] * k  # w[0] is the intercept
    base = sum(ys) / n
    w[0] = math.log(base / (1 - base))
    for _ in range(iters):
        g = [0.0] * k
        for f, y in zip(feats, ys):
            z = w[0] + sum(w[j + 1] for j in f)
            p = 1 / (1 + math.exp(-max(-30, min(30, z))))
            e = p - y
            g[0] += e
            for j in f:
                g[j + 1] += e
        for j in range(k):
            w[j] -= lr * (g[j] / n + (l2 * w[j] if j else 0.0))
    return w


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("data", help="evaluation data (holdout/test)")
    ap.add_argument("--patterns", required=True)
    ap.add_argument("--pos-label", required=True)
    ap.add_argument("--fit-data", default=None,
                    help="separate file to fit weights on (e.g. the official "
                         "train split of a benchmark)")
    ap.add_argument("--split", type=float, default=None,
                    help="without --fit-data: fit on the train part of this "
                         "stratified split of `data`, evaluate on the holdout")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--score", default="logodds",
                    choices=["logodds", "logistic", "count"])
    ap.add_argument("--exclude-tokens", nargs="*", default=[])
    ap.add_argument("--out", default=None)
    add_jobs_arg(ap)
    add_windowing_args(ap)
    args = ap.parse_args()

    with open(args.patterns) as f:
        patterns = [as_dsl(p, i) for i, p in enumerate(json.load(f))]
    kw = dict(exclude_tokens=args.exclude_tokens, **windowing_kwargs(args))
    ds_eval = load_dataset(args.data, **kw)

    if args.fit_data:
        ds_fit = load_dataset(args.fit_data, **kw)
        fit_idx = list(range(len(ds_fit)))
        eval_idx = list(range(len(ds_eval)))
    elif args.split:
        ds_fit = ds_eval
        fit_idx, eval_idx = stratified_split(ds_eval, args.split, args.seed)
    else:
        ap.error("need --fit-data or --split (weights must not be fit on "
                 "the evaluation accounts)")

    ys_fit = [1 if ds_fit.labels[i] == args.pos_label else 0 for i in fit_idx]
    ys_eval = [1 if ds_eval.labels[i] == args.pos_label else 0 for i in eval_idx]
    if ds_fit is ds_eval:
        fired_fit = match_matrix(ds_fit, fit_idx + eval_idx, patterns,
                                 args.jobs)
        fired_eval = fired_fit
    else:
        fired_fit = match_matrix(ds_fit, fit_idx, patterns, args.jobs)
        fired_eval = match_matrix(ds_eval, eval_idx, patterns, args.jobs)

    ys_of_fit = {i: y for i, y in zip(fit_idx, ys_fit)}
    if args.score == "logistic":
        by_acct = {i: [] for i in fit_idx}
        for k, hits in enumerate(fired_fit):
            for i in hits:
                if i in by_acct:
                    by_acct[i].append(k)
        w = fit_logistic([by_acct[i] for i in fit_idx], ys_fit)
        b, wp = w[0], w[1:]
    else:
        wp = fit_logodds(fired_fit, fit_idx, ys_of_fit)
        if args.score == "count":
            wp = [1.0 if x > 0 else -1.0 for x in wp]
        b = 0.0

    fired_by_acct = {i: [] for i in eval_idx}
    for k, hits in enumerate(fired_eval):
        for i in hits:
            if i in fired_by_acct:
                fired_by_acct[i].append(k)
    scores = [b + sum(wp[k] for k in fired_by_acct[i]) for i in eval_idx]
    auc = auc_score(scores, ys_eval)

    n_pos, n_neg = sum(ys_eval), len(ys_eval) - sum(ys_eval)
    print(f"# Rule-set evaluation: {len(patterns)} patterns, "
          f"score={args.score}\n")
    print(f"- eval accounts: {len(eval_idx)} (pos={n_pos}, neg={n_neg})")
    print(f"- **ROC AUC: {auc:.4f}**")

    print("\n| id | name | weight | eval sup_pos | eval sup_neg | eval lift |")
    print("|---|---|---|---|---|---|")
    eval_set = set(eval_idx)
    ys_of_eval = {i: y for i, y in zip(eval_idx, ys_eval)}
    per_pattern = []
    for k, pat in enumerate(patterns):
        hits = [i for i in fired_eval[k] if i in eval_set]
        a = sum(1 for i in hits if ys_of_eval[i])
        st = contrast_stats(a, n_pos, len(hits) - a, n_neg)
        per_pattern.append({"id": pat.get("id"), "name": pat.get("name"),
                            "weight": round(wp[k], 4), **st})
        print(f"| {pat.get('id','?')} | {pat.get('name','')[:44]} "
              f"| {wp[k]:+.3f} | {st['support_pos']:.3f} "
              f"| {st['support_neg']:.3f} | {st['lift']:.2f} |")

    if args.out:
        with open(args.out, "w") as f:
            json.dump({"auc": auc, "score_mode": args.score,
                       "n_eval": len(eval_idx), "n_pos": n_pos,
                       "patterns": per_pattern}, f, indent=1)
        print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
