#!/usr/bin/env python3
"""Verify Pattern-DSL hypotheses against the data: per-pattern contrast stats on
train/holdout splits, FDR across the set, match overlap, and example matches.

    python verify_patterns.py data.jsonl --patterns hypos.json --pos-label fraud \
        --split 0.3 --seed 42 --overlap [--show-matches 3] [--out results.json]

Patterns file: JSON array of DSL objects (see references/pattern-dsl.md). Plain
mined candidates ({"pattern": [tok, ...]}) are also accepted and auto-wrapped.
"""

from __future__ import annotations

import argparse
import json

from seqlib import bh_fdr, contrast_stats, load_dataset, pattern_matches, stratified_split


def as_dsl(p, i):
    if "steps" in p:
        return p
    return {"id": p.get("id", f"M{i:03d}"),
            "name": " → ".join(p["pattern"]),
            "steps": [{"token": t} for t in p["pattern"]]}


def evaluate(ds, idxs, patterns, pos_label):
    n_pos = sum(1 for i in idxs if ds.labels[i] == pos_label)
    n_neg = len(idxs) - n_pos
    out = []
    for pat in patterns:
        matched = [i for i in idxs if pattern_matches(ds.seqs[i], pat)]
        a = sum(1 for i in matched if ds.labels[i] == pos_label)
        st = contrast_stats(a, n_pos, len(matched) - a, n_neg)
        out.append((pat, st, set(matched)))
    qs = bh_fdr([st["fisher_p"] for _, st, _ in out]) if out else []
    for (_, st, _), q in zip(out, qs):
        st["fdr_q"] = round(q, 6)
        st["fisher_p"] = round(st["fisher_p"], 8)
    return out, n_pos, n_neg


def print_table(title, rows, n_pos, n_neg):
    print(f"\n## {title} (n_pos={n_pos}, n_neg={n_neg})\n")
    print("| id | name | sup_pos | sup_neg | prec | lift | wracc | fdr_q |")
    print("|---|---|---|---|---|---|---|---|")
    for pat, st, _ in rows:
        print(f"| {pat.get('id','?')} | {pat.get('name','')[:48]} "
              f"| {st['support_pos']:.3f} | {st['support_neg']:.3f} "
              f"| {st['precision']:.3f} | {st['lift']:.2f} "
              f"| {st['wracc']:.4f} | {st['fdr_q']:.4f} |")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("data")
    ap.add_argument("--patterns", required=True)
    ap.add_argument("--pos-label", required=True)
    ap.add_argument("--split", type=float, default=None,
                    help="holdout fraction; stats reported for both splits")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--holdout-only", action="store_true",
                    help="Phase 4: report holdout split only")
    ap.add_argument("--exclude-tokens", nargs="*", default=[])
    ap.add_argument("--overlap", action="store_true",
                    help="report pattern pairs with match-set Jaccard > 0.6")
    ap.add_argument("--show-matches", type=int, default=0,
                    help="print N matching + N non-matching pos-class ids per pattern")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    ds = load_dataset(args.data, exclude_tokens=args.exclude_tokens)
    with open(args.patterns) as f:
        patterns = [as_dsl(p, i) for i, p in enumerate(json.load(f))]

    if args.split:
        train, test = stratified_split(ds, args.split, args.seed)
    else:
        train, test = list(range(len(ds))), []

    results = {}
    splits = [("holdout", test)] if args.holdout_only else (
        [("train", train)] + ([("holdout", test)] if test else []))
    for name, idxs in splits:
        rows, n_pos, n_neg = evaluate(ds, idxs, patterns, args.pos_label)
        print_table(name.upper(), rows, n_pos, n_neg)
        results[name] = rows

    ref = results.get("train") or results.get("holdout")
    if args.overlap and ref:
        print("\n## Overlap (train match-set Jaccard > 0.6 — consider merging)\n")
        any_pair = False
        for i in range(len(ref)):
            for j in range(i + 1, len(ref)):
                mi, mj = ref[i][2], ref[j][2]
                if not mi or not mj:
                    continue
                jac = len(mi & mj) / len(mi | mj)
                if jac > 0.6:
                    any_pair = True
                    print(f"- {ref[i][0].get('id')} vs {ref[j][0].get('id')}: "
                          f"J={jac:.2f}")
        if not any_pair:
            print("- none")

    if args.show_matches and ref:
        print("\n## Example ids (train)")
        for pat, _, matched in ref:
            pos_hit = [ds.ids[i] for i in sorted(matched)
                       if ds.labels[i] == args.pos_label][: args.show_matches]
            pos_miss = [ds.ids[i] for i in sorted(set(train) - matched)
                        if ds.labels[i] == args.pos_label][: args.show_matches]
            print(f"- {pat.get('id')}: pos matches {pos_hit}; pos misses {pos_miss}")

    if args.out:
        dump = {name: [{"id": p.get("id"), "name": p.get("name"), **st}
                       for p, st, _ in rows]
                for name, rows in results.items()}
        with open(args.out, "w") as f:
            json.dump(dump, f, indent=1)
        print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
