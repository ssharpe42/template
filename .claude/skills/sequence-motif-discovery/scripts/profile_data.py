#!/usr/bin/env python3
"""Profile a labeled sequence dataset before mining: sizes, lengths, vocabulary,
single-token contrast, and label-leakage suspects.

    python profile_data.py data.jsonl --pos-label fraud [--samples 3]
"""

from __future__ import annotations

import argparse
from collections import Counter

from seqlib import (add_windowing_args, contrast_stats, humanize_seconds,
                    load_dataset, token_feature, windowing_kwargs)


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("data")
    ap.add_argument("--pos-label", required=True)
    ap.add_argument("--sep", default="=")
    ap.add_argument("--samples", type=int, default=3)
    add_windowing_args(ap)
    args = ap.parse_args()

    ds = load_dataset(args.data, **windowing_kwargs(args))
    labels = set(ds.labels)
    print(f"# Dataset profile: {args.data}\n")
    print(f"- accounts: {len(ds)}; labels: "
          + ", ".join(f"{l}={ds.labels.count(l)}" for l in sorted(labels)))
    n_pos = ds.labels.count(args.pos_label)
    n_neg = len(ds) - n_pos
    if n_pos == 0:
        print(f"!! pos label '{args.pos_label}' not found; labels are {labels}")
        return
    print(f"- imbalance: 1 {args.pos_label} : {n_neg / max(n_pos, 1):.1f} other")

    print("\n## Sequence lengths (check class gap → censoring/leakage risk, D2)")
    for lab in sorted(labels):
        ls = [len(s) for s, l in zip(ds.seqs, ds.labels) if l == lab]
        print(f"- {lab}: min={min(ls)} p50={pct(ls, .5)} p90={pct(ls, .9)} "
              f"max={max(ls)} mean={sum(ls)/len(ls):.1f}")

    if ds.has_times:
        print("\n## Inter-event time gaps (informs gap buckets D5 / time windows)")
        for lab in sorted(labels):
            gaps = [t2 - t1
                    for ts, l in zip(ds.times, ds.labels) if l == lab and ts
                    for t1, t2 in zip(ts, ts[1:])]
            if gaps:
                print(f"- {lab}: p10={humanize_seconds(pct(gaps, .1))} "
                      f"p50={humanize_seconds(pct(gaps, .5))} "
                      f"p90={humanize_seconds(pct(gaps, .9))}")
        spans = [ts[-1] - ts[0] for ts in ds.times if ts and len(ts) > 1]
        if spans:
            print(f"- history span: p50={humanize_seconds(pct(spans, .5))} "
                  f"p90={humanize_seconds(pct(spans, .9))}")
    else:
        print("\n(no event times found — time-based options D5 unavailable)")

    # vocabulary & features
    tok_pos, tok_neg = Counter(), Counter()  # account-level presence
    feat_vals = {}
    multi = 0
    for seq, lab in zip(ds.seqs, ds.labels):
        seen = set()
        for ev in seq:
            multi += len(ev) > 1
            seen.update(ev)
        for t in seen:
            (tok_pos if lab == args.pos_label else tok_neg)[t] += 1
        for t in seen:
            feat_vals.setdefault(token_feature(t, args.sep), set()).add(t)

    vocab = set(tok_pos) | set(tok_neg)
    print(f"\n## Vocabulary\n- tokens: {len(vocab)}; features: {len(feat_vals)}; "
          f"itemset events: {'yes' if multi else 'no'}")
    big = sorted(feat_vals.items(), key=lambda kv: -len(kv[1]))[:15]
    print("- feature cardinalities (top): "
          + ", ".join(f"{f}={len(v)}" for f, v in big))
    if len(vocab) > 5000:
        print("!! vocab > 5000: coarsen bins or prune features before mining (D6)")

    print("\n## Single-token contrast (account-level presence)")
    rows = []
    for t in vocab:
        a, c = tok_pos.get(t, 0), tok_neg.get(t, 0)
        if a + c < 3:
            continue
        st = contrast_stats(a, n_pos, c, n_neg)
        rows.append((t, st))
    rows.sort(key=lambda r: r[1]["wracc"], reverse=True)
    print(f"\n### Enriched in {args.pos_label}")
    print("| token | sup_pos | sup_neg | lift |")
    print("|---|---|---|---|")
    for t, st in rows[:20]:
        print(f"| {t} | {st['support_pos']:.3f} | {st['support_neg']:.3f} "
              f"| {st['lift']:.2f} |")
    print(f"\n### Enriched in other (candidate protective/absence tokens)")
    print("| token | sup_pos | sup_neg | 1/lift |")
    print("|---|---|---|---|")
    for t, st in sorted(rows, key=lambda r: r[1]["wracc"])[:15]:
        print(f"| {t} | {st['support_pos']:.3f} | {st['support_neg']:.3f} "
              f"| {1/max(st['lift'], 1e-9):.2f} |")

    leaks = [t for t, st in rows
             if st["lift"] > 50 and st["support_pos"] > 0.3]
    if leaks:
        print("\n!! LEAKAGE SUSPECTS (near-perfect label correlation — confirm with "
              "user, likely outcome encodings, D3):")
        for t in leaks:
            print(f"   - {t}")

    print(f"\n## Sample sequences ({args.samples}/class, truncated to 30 events)")
    for lab in sorted(labels):
        shown = 0
        for i, l in enumerate(ds.labels):
            if l != lab or shown >= args.samples:
                continue
            shown += 1
            evs = [("{" + ",".join(sorted(e)) + "}") if len(e) > 1
                   else next(iter(e), "∅") for e in ds.seqs[i][:30]]
            more = "…" if len(ds.seqs[i]) > 30 else ""
            print(f"- [{lab}] {ds.ids[i]}: {' '.join(evs)}{more}")


if __name__ == "__main__":
    main()
