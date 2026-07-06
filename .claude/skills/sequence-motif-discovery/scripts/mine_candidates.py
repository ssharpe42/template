#!/usr/bin/env python3
"""Class-aware PrefixSpan: mine subsequences enriched in one class vs the other.

Example:
    python mine_candidates.py data.jsonl --pos-label fraud --direction both \
        --min-pos-support 0.05 --max-len 4 --top 50 --metric wracc --out cands.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict

from seqlib import (add_jobs_arg, add_windowing_args, bh_fdr, contrast_stats,
                    is_subsequence, load_dataset, parallel_env, resolve_jobs,
                    run_parallel, stratified_split, windowing_kwargs)


def _extend(prefix, proj, env, results):
    """One PrefixSpan extension level (recursive, serial within a worker).
    Projections carry all valid end positions when a gap constraint is set
    (needed for correctness); only the earliest otherwise (sufficient for
    unconstrained gaps)."""
    if len(results) >= env["max_patterns"]:
        return
    seqs, times, is_pos = env["seqs"], env["times"], env["is_pos"]
    max_gap, max_time_gap = env["max_gap"], env["max_time_gap"]
    constrained = env["constrained"]
    occ = defaultdict(dict)  # token -> {sid: [positions]}
    for sid, ends in proj:
        seq, ts = seqs[sid], times[sid]
        found = {}
        idxs = set()
        for p in ends:
            hi = len(seq) if max_gap is None else min(len(seq), p + max_gap + 2)
            for i in range(p + 1, hi):
                if (max_time_gap is not None and ts
                        and ts[i] - ts[p] > max_time_gap):
                    break
                idxs.add(i)
        for i in sorted(idxs):
            for tok in seq[i]:
                found.setdefault(tok, []).append(i)
        for tok, positions in found.items():
            occ[tok][sid] = positions if constrained else positions[:1]

    for tok, bysid in occ.items():
        a = sum(1 for sid in bysid if is_pos[sid])
        if a < env["min_pos"]:
            continue
        pat = prefix + [tok]
        c = len(bysid) - a
        results.append((pat, a, c))
        if len(pat) < env["max_len"]:
            _extend(pat, list(bysid.items()), env, results)


def _mine_token_group(group):
    """Worker: mine the full subtree under each starting token in `group`,
    using the root projections built once by the parent (inherited via fork,
    copy-on-write — never pickled)."""
    env = parallel_env()
    is_pos, root_occ = env["is_pos"], env["root_occ"]
    results = []
    for tok in group:
        bysid = root_occ[tok]
        a = sum(1 for sid in bysid if is_pos[sid])
        results.append(([tok], a, len(bysid) - a))
        if env["max_len"] > 1 and len(results) < env["max_patterns"]:
            _extend([tok], list(bysid.items()), env, results)
    return results[: env["max_patterns"]]


def mine(seqs, times, is_pos, min_pos, max_len, max_gap, max_time_gap,
         max_patterns, jobs=0):
    """Class-aware PrefixSpan, parallelized over starting tokens: one pass in
    the parent builds every frequent token's root projections (the same work
    the serial level-1 step always did), then each token roots an independent
    projected-database subtree mined in a worker process. Workers cover
    disjoint regions of the pattern space, so results merge by concatenation;
    the dataset and root projections are shared via fork (copy-on-write),
    never pickled."""
    n_pos = sum(is_pos)
    constrained = max_gap is not None or max_time_gap is not None

    # level 1: single pass — positions of every token in every sequence
    root_occ = defaultdict(dict)   # token -> {sid: [positions]}
    pos_count = Counter()          # token -> pos-class account presence
    for sid, seq in enumerate(seqs):
        found = {}
        for i, ev in enumerate(seq):
            for tok in ev:
                found.setdefault(tok, []).append(i)
        if is_pos[sid]:
            pos_count.update(found.keys())
        for tok, positions in found.items():
            root_occ[tok][sid] = positions if constrained else positions[:1]
    frequent = sorted((t for t, a in pos_count.items() if a >= min_pos),
                      key=lambda t: (-pos_count[t], t))
    root_occ = {t: root_occ[t] for t in frequent}

    env = {"seqs": seqs, "times": times, "is_pos": is_pos, "min_pos": min_pos,
           "max_len": max_len, "max_gap": max_gap, "max_time_gap": max_time_gap,
           "max_patterns": max_patterns, "constrained": constrained,
           "root_occ": root_occ}
    # Small round-robin token groups (frequency-ordered) + dynamic dispatch:
    # subtree costs vary wildly, so fine granularity is what balances load.
    n_groups = min(len(frequent), resolve_jobs(jobs) * 4)
    groups = [frequent[g::n_groups] for g in range(n_groups)]
    results = []
    for part in run_parallel(_mine_token_group, groups, jobs, env):
        results.extend(part)
    return results[:max_patterns], n_pos, len(seqs) - n_pos


def closed_filter(rows):
    """Drop a pattern if a superpattern has identical (a, c) support."""
    by_support = defaultdict(list)
    for pat, a, c in rows:
        by_support[(a, c)].append(pat)
    keep = []
    for pat, a, c in rows:
        group = by_support[(a, c)]
        if any(p is not pat and len(p) > len(pat) and is_subsequence(pat, p)
               for p in group):
            continue
        keep.append((pat, a, c))
    return keep


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("data")
    ap.add_argument("--pos-label", required=True)
    ap.add_argument("--direction", choices=["pos", "neg", "both"], default="pos",
                    help="mine patterns enriched in pos, in neg, or both")
    ap.add_argument("--min-pos-support", type=float, default=0.05)
    ap.add_argument("--max-len", type=int, default=4)
    ap.add_argument("--max-gap", type=int, default=None,
                    help="max intervening events between consecutive steps")
    ap.add_argument("--max-time-gap", default=None,
                    help="max time between consecutive steps, e.g. '1h', '30m' "
                         "or seconds (needs times)")
    ap.add_argument("--top", type=int, default=50)
    ap.add_argument("--metric", default="wracc",
                    choices=["wracc", "lift", "odds_ratio", "info_gain", "precision"])
    ap.add_argument("--max-patterns", type=int, default=200000)
    ap.add_argument("--exclude-tokens", nargs="*", default=[])
    ap.add_argument("--split", type=float, default=None,
                    help="holdout fraction to EXCLUDE from mining (stratified)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default=None)
    add_jobs_arg(ap)
    add_windowing_args(ap)
    args = ap.parse_args()

    from seqlib import parse_duration
    args.max_time_gap = parse_duration(args.max_time_gap)
    ds = load_dataset(args.data, exclude_tokens=args.exclude_tokens,
                      **windowing_kwargs(args))
    if args.max_time_gap is not None and not ds.has_times:
        ap.error("--max-time-gap requires event times in the data")
    idx = list(range(len(ds)))
    if args.split:
        idx, _ = stratified_split(ds, args.split, args.seed)
    seqs = [ds.seqs[i] for i in idx]
    times = [ds.times[i] for i in idx]
    labels = [ds.labels[i] for i in idx]

    directions = ["pos", "neg"] if args.direction == "both" else [args.direction]
    all_out = []
    for direction in directions:
        target = args.pos_label if direction == "pos" else None
        is_pos = ([l == args.pos_label for l in labels] if direction == "pos"
                  else [l != args.pos_label for l in labels])
        n_pos_total = sum(is_pos)
        min_pos = max(2, math.ceil(args.min_pos_support * n_pos_total))
        rows, n_pos, n_neg = mine(seqs, times, is_pos, min_pos, args.max_len,
                                  args.max_gap, args.max_time_gap,
                                  args.max_patterns, jobs=args.jobs)
        rows = closed_filter(rows)
        mined_cons = {}
        if args.max_gap is not None:
            mined_cons["max_gap"] = args.max_gap
        if args.max_time_gap is not None:
            mined_cons["max_time_gap"] = args.max_time_gap
        scored = []
        for pat, a, c in rows:
            st = contrast_stats(a, n_pos, c, n_neg)
            if st["lift"] <= 1.0:
                continue
            rec = {"pattern": pat, "direction": direction, **st}
            if mined_cons:
                rec["constraints"] = mined_cons
            scored.append(rec)
        scored.sort(key=lambda r: r[args.metric], reverse=True)
        scored = scored[: args.top]
        qs = bh_fdr([r["fisher_p"] for r in scored]) if scored else []
        for r, q in zip(scored, qs):
            r["fdr_q"] = round(q, 6)
            r["fisher_p"] = round(r["fisher_p"], 8)
        all_out.extend(scored)

        enriched_in = args.pos_label if direction == "pos" else f"NOT-{args.pos_label}"
        print(f"\n## Top patterns enriched in {enriched_in} "
              f"(n_target={n_pos}, n_other={n_neg}, min_target_matches={min_pos})\n")
        print("| pattern | sup_tgt | sup_oth | lift | wracc | prec | fdr_q |")
        print("|---|---|---|---|---|---|---|")
        for r in scored[:min(args.top, 40)]:
            print(f"| {' → '.join(r['pattern'])} | {r['support_pos']:.3f} "
                  f"| {r['support_neg']:.3f} | {r['lift']:.2f} | {r['wracc']:.4f} "
                  f"| {r['precision']:.3f} | {r['fdr_q']:.4f} |")

    if args.out:
        with open(args.out, "w") as f:
            json.dump(all_out, f, indent=1)
        print(f"\nWrote {len(all_out)} candidates to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
