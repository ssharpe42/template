#!/usr/bin/env python3
"""Standard-feature baseline for KDD Cup 2015 dropout: pure-python logistic
regression on classic engagement count features (the kind every leaderboard
entry started from). Gives local context for the motif rule-set AUC.

    python baseline_counts.py train.jsonl test.jsonl

Features per enrollment (from the JSONL alone):
  log1p counts of each base event type, log1p total events, active days,
  history span (days), silence before course_end (days), session count
  (gaps > 1h), log1p events per active day.
"""

from __future__ import annotations

import json
import math
import sys

EVENTS = ["navigate", "access", "problem", "video", "page_close",
          "discussion", "wiki"]


def featurize(path):
    xs, ys, ids = [], [], []
    with open(path) as f:
        for line in f:
            r = json.loads(line)
            ev, ts = r["events"], r["times"]
            body = [(e, t) for e, t in zip(ev, ts) if e != "course_end"]
            end = ts[-1]
            counts = {e: 0 for e in EVENTS}
            for e, _ in body:
                if e in counts:
                    counts[e] += 1
            days = sorted({int(t // 86400) for _, t in body})
            sessions = 1 + sum(1 for (_, t1), (_, t2) in zip(body, body[1:])
                               if t2 - t1 > 3600)
            span = (body[-1][1] - body[0][1]) / 86400 if len(body) > 1 else 0.0
            silence = max(0.0, (end - body[-1][1]) / 86400)
            x = ([math.log1p(counts[e]) for e in EVENTS]
                 + [math.log1p(len(body)), float(len(days)), span, silence,
                    float(sessions), math.log1p(len(body) / max(1, len(days)))])
            xs.append(x)
            ys.append(1 if r["label"] == "dropout" else 0)
            ids.append(r["id"])
    return xs, ys, ids


def standardize(xs, mu=None, sd=None):
    k = len(xs[0])
    if mu is None:
        n = len(xs)
        mu = [sum(x[j] for x in xs) / n for j in range(k)]
        sd = [max(1e-9, math.sqrt(sum((x[j] - mu[j]) ** 2 for x in xs) / n))
              for j in range(k)]
    return [[(x[j] - mu[j]) / sd[j] for j in range(k)] for x in xs], mu, sd


def fit_logistic(xs, ys, l2=1e-4, iters=250, lr=0.3):
    n, k = len(xs), len(xs[0])
    w = [0.0] * (k + 1)
    base = sum(ys) / n
    w[0] = math.log(base / (1 - base))
    for it in range(iters):
        g = [0.0] * (k + 1)
        for x, y in zip(xs, ys):
            z = w[0] + sum(wj * xj for wj, xj in zip(w[1:], x))
            p = 1 / (1 + math.exp(-max(-30, min(30, z))))
            e = p - y
            g[0] += e
            for j in range(k):
                g[j + 1] += e * x[j]
        for j in range(k + 1):
            w[j] -= lr * (g[j] / n + (l2 * w[j] if j else 0.0))
    return w


def auc_score(scores, ys):
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    ranks = [0.0] * len(scores)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    n_pos = sum(ys)
    n_neg = len(ys) - n_pos
    return (sum(r for r, y in zip(ranks, ys) if y)
            - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def main():
    train_path, test_path = sys.argv[1], sys.argv[2]
    xtr, ytr, _ = featurize(train_path)
    xte, yte, _ = featurize(test_path)
    xtr, mu, sd = standardize(xtr)
    xte, _, _ = standardize(xte, mu, sd)

    # trivial single-feature baseline: activity volume
    print(f"log-total-events alone: "
          f"AUC={auc_score([-x[7] for x in xte], yte):.4f}")

    w = fit_logistic(xtr, ytr)
    scores = [w[0] + sum(wj * xj for wj, xj in zip(w[1:], x)) for x in xte]
    print(f"logistic regression on {len(xtr[0])} count features: "
          f"AUC={auc_score(scores, yte):.4f}")
    names = EVENTS + ["log_total", "active_days", "span_d", "silence_d",
                      "sessions", "log_ev_per_day"]
    print("weights:", {n: round(x, 3) for n, x in zip(names, w[1:])})


if __name__ == "__main__":
    main()
