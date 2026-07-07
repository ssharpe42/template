"""Fit candidate parameters on training PAs; evaluate on holdout PAs.

Fitting minimizes mean squared error against *realized* per-PA wOBA values
(the only thing observable with real data). Holdout evaluation reports:
  - RMSE vs the generator's true expected wOBA (sensitive; sim-only luxury)
  - MSE vs realized values (what a real-data study would see)
  - calibration and subgroup bias diagnostics
"""

import numpy as np
from scipy.optimize import minimize


def fit(cand, inputs, y):
    B, P, Lc, L, PF = inputs

    def loss(th):
        pred = cand.predict(th, B, P, Lc, L, PF)
        return np.mean((pred - y) ** 2)

    if len(cand.p0) == 0:
        return np.array([]), loss(np.array([]))
    res = minimize(loss, cand.p0, method="Nelder-Mead",
                   options=dict(xatol=1e-5, fatol=1e-12, maxiter=4000))
    return res.x, res.fun


def evaluate(cand, params, inputs, y, true_mu):
    pred = cand.predict(params, *inputs)
    out = dict(
        rmse_true=float(np.sqrt(np.mean((pred - true_mu) ** 2))),
        mse_realized=float(np.mean((pred - y) ** 2)),
        mean_bias=float(np.mean(pred - true_mu)),
    )
    return pred, out


def subgroup_bias(pred, true_mu, season, inputs):
    """Mean (pred - true) x1000 within diagnostic subgroups."""
    B, P, Lc, L, PF = inputs
    groups = {}
    bh, ph, same = season["bat_hand"], season["pit_hand"], season["same"]
    groups["same-hand PAs"] = same
    groups["opp-hand PAs"] = ~same
    qB_hi, qB_lo = np.quantile(B, [0.9, 0.1])
    qP_hi, qP_lo = np.quantile(P, [0.9, 0.1])
    groups["elite batters (top 10% B)"] = B >= qB_hi
    groups["weak batters (bottom 10% B)"] = B <= qB_lo
    groups["weak pitchers (top 10% P)"] = P >= qP_hi
    groups["elite pitchers (bottom 10% P)"] = P <= qP_lo
    groups["elite bat vs weak pit"] = (B >= qB_hi) & (P >= qP_hi)
    groups["weak bat vs elite pit"] = (B <= qB_lo) & (P <= qP_lo)
    groups["hitter parks (PF top 10%)"] = PF >= np.quantile(PF, 0.9)
    groups["pitcher parks (PF bot 10%)"] = PF <= np.quantile(PF, 0.1)
    return {k: float(np.mean(pred[m] - true_mu[m]) * 1000) for k, m in groups.items()}


def calibration(pred, true_mu, n_bins=10):
    """Decile calibration: mean predicted vs mean true by predicted decile."""
    qs = np.quantile(pred, np.linspace(0, 1, n_bins + 1))
    qs[0] -= 1e-9
    idx = np.searchsorted(qs, pred, side="right") - 1
    idx = np.clip(idx, 0, n_bins - 1)
    rows = []
    for i in range(n_bins):
        m = idx == i
        rows.append((float(pred[m].mean()), float(true_mu[m].mean()), int(m.sum())))
    return rows
