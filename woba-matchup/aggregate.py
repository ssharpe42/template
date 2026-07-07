"""Aggregate multi-seed results into summary tables (markdown)."""

import glob
import json
import numpy as np

files = sorted(glob.glob("results/results_seed*.json"))
runs = [json.load(open(f)) for f in files]
print(f"seeds: {[f.split('seed')[1].split('.')[0] for f in files]}\n")

for exp in ("realistic", "oracle"):
    names = [r["name"] for r in runs[0][exp]["results"]]
    print(f"## {exp} experiment — holdout RMSE vs true E[wOBA], wOBA points x1000")
    print("| candidate | mean | min | max | params (seed mean) |")
    print("|---|---|---|---|---|")
    for i, name in enumerate(names):
        vals = [r[exp]["results"][i]["rmse_true"] * 1000 for r in runs]
        ps = np.array([r[exp]["results"][i]["params"] for r in runs])
        pm = ", ".join(f"{v:.3f}" for v in ps.mean(axis=0)) if ps.size else "-"
        print(f"| {name} | {np.mean(vals):.2f} | {min(vals):.2f} | {max(vals):.2f} | {pm} |")
    print()

# subgroup bias for key candidates, averaged over seeds (realistic experiment)
keys = ["additive (overall-league reference)", "additive (cell reference)",
        "odds ratio (s=1)", "free log-odds"]
groups = list(runs[0]["realistic"]["results"][0]["subgroup_bias"].keys())
for exp in ("realistic", "oracle"):
    print(f"## {exp}: mean bias (pred - true) x1000 by subgroup")
    print("| subgroup | " + " | ".join(k.replace(" reference)", ")") for k in keys) + " |")
    print("|---" * (len(keys) + 1) + "|")
    for g in groups:
        row = [g]
        for k in keys:
            entry = next(r for r in runs[0][exp]["results"] if r["name"] == k)
            vals = [next(rr for rr in r[exp]["results"] if rr["name"] == k)["subgroup_bias"][g]
                    for r in runs]
            row.append(f"{np.mean(vals):+.1f}")
        print("| " + " | ".join(row) + " |")
    print()
