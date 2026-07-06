#!/usr/bin/env python3
"""Generate a synthetic labeled sequence dataset with planted fraud motifs.
Used to smoke-test the pipeline end to end.

    python make_synthetic.py out.jsonl [--n-good 800] [--n-fraud 150] [--seed 7]

Planted signal in fraud accounts:
  M1 (70%): device=new .. txn_amt in {high, very_high} .. pwd_reset=1  (in order, gaps)
  M2 (40%): three login_geo=mismatch within a short burst
  Protective (good, 60%): kyc=passed early in the sequence
"""

from __future__ import annotations

import argparse
import json
import random

FEATURES = {
    "txn_amt": ["low", "med", "high", "very_high"],
    "login_geo": ["home", "roam", "mismatch"],
    "device": ["known", "new"],
    "pwd_reset": ["0", "1"],
    "kyc": ["passed", "pending", "none"],
    "session_len": ["short", "med", "long"],
}


def noise_event(rng):
    f = rng.choice(list(FEATURES))
    return f"{f}={rng.choice(FEATURES[f])}"


def base_seq(rng, lo=15, hi=60):
    return [noise_event(rng) for _ in range(rng.randint(lo, hi))]


def inject(seq, gaps, rng, motif, max_gap=4, burst_secs=(30, 300)):
    """Overwrite events with the motif tokens; compress the time gaps between
    consecutive motif events so it also reads as a burst in time."""
    pos = rng.randint(0, max(0, len(seq) - len(motif) * (max_gap + 1) - 1))
    prev = None
    for tok in motif:
        pos += rng.randint(1, max_gap)
        pos = min(pos, len(seq) - 1)
        seq[pos] = tok
        if prev is not None:
            for j in range(prev + 1, pos + 1):
                gaps[j] = rng.uniform(*burst_secs) / max(1, pos - prev)
        prev = pos
    return seq


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("out")
    ap.add_argument("--n-good", type=int, default=800)
    ap.add_argument("--n-fraud", type=int, default=150)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    t0 = 1750000000.0

    def times_from(gaps):
        ts, t = [], t0
        for g in gaps:
            t += g
            ts.append(round(t, 1))
        return ts

    recs = []
    for i in range(args.n_fraud):
        seq = base_seq(rng)
        gaps = [rng.uniform(3600, 48 * 3600) for _ in seq]  # noise: 1h-2d apart
        if rng.random() < 0.7:
            amt = rng.choice(["high", "very_high"])
            inject(seq, gaps, rng, ["device=new", f"txn_amt={amt}", "pwd_reset=1"])
        if rng.random() < 0.4:
            inject(seq, gaps, rng, ["login_geo=mismatch"] * 3, max_gap=2)
        recs.append({"id": f"f{i:04d}", "label": "fraud", "events": seq,
                     "times": times_from(gaps)})
    for i in range(args.n_good):
        seq = base_seq(rng)
        gaps = [rng.uniform(3600, 48 * 3600) for _ in seq]
        if rng.random() < 0.6:
            seq[rng.randint(0, min(5, len(seq) - 1))] = "kyc=passed"
        recs.append({"id": f"g{i:04d}", "label": "good", "events": seq,
                     "times": times_from(gaps)})
    rng.shuffle(recs)
    with open(args.out, "w") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")
    print(f"wrote {len(recs)} accounts to {args.out}")


if __name__ == "__main__":
    main()
