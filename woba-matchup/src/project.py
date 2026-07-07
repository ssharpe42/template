"""Marcel-style projection layer.

Produces the inputs the matchup formula is 'given':
  - batter projected wOBA vs LHP and vs RHP
  - pitcher projected wOBA-against vs LHB and vs RHB
  - league wOBA (overall and by handedness cell)
  - estimated park factors (empirical-Bayes shrunk)

Built only from *observed* prior-season data (never true talent), park-adjusted,
using The Book's approach: project overall wOBA (regress toward league), then
add a platoon split regressed toward the league-mean split for that hand
(LHB k=1000, RHB k=2200 same-hand PA; pitchers LHP k=450, RHP k=700).
"""

import numpy as np

MARCEL_W = (5.0, 4.0)     # weights for t-1, t-2
# Regression constants are in *weighted* PA units (see MARCEL_W); defaults are
# placeholders — run_study tunes them on training data via tune_k().
K_BAT, K_PIT = 250.0, 400.0
K_SPLIT_BAT = {1: 1000.0, 0: 2200.0, 2: 1e12}   # by batter hand (switch: none)
K_SPLIT_PIT = {1: 450.0, 0: 700.0}


def _wsum(seasons, key, weights, val=None, mask_fn=None, n_ids=None):
    """Weighted (count, sum-of-woba) per id over seasons."""
    cnt = np.zeros(n_ids)
    tot = np.zeros(n_ids)
    for s, w in zip(seasons, weights):
        m = mask_fn(s) if mask_fn else np.ones(len(s["woba"]), bool)
        ids = s[key][m]
        v = s["adj_woba"][m] if val is None else s[val][m]
        cnt += w * np.bincount(ids, minlength=n_ids)
        tot += w * np.bincount(ids, weights=v, minlength=n_ids)
    return cnt, tot


def estimate_park_factors(seasons, n_park):
    """Empirical-Bayes park factor estimates from observed wOBA by park."""
    cnt = np.zeros(n_park)
    tot = np.zeros(n_park)
    for s in seasons:
        cnt += np.bincount(s["park"], minlength=n_park)
        tot += np.bincount(s["park"], weights=s["woba"], minlength=n_park)
    lg = tot.sum() / cnt.sum()
    obs = (tot / np.maximum(cnt, 1)) / lg
    # method-of-moments shrinkage: Var(obs) = sig^2 + mean noise var
    noise_var = np.mean((s["woba"].std() / lg) ** 2 / np.maximum(cnt, 1))
    sig_var = max(obs.var() - noise_var, 1e-6)
    shrink = sig_var / (sig_var + noise_var)
    return 1.0 + shrink * (obs - 1.0)


def park_adjust(seasons, pf_hat):
    """Divide each PA's woba value by its park's estimated factor."""
    for s in seasons:
        s["adj_woba"] = s["woba"] / pf_hat[s["park"]]


def project(seasons, pop, k_bat=K_BAT, k_pit=K_PIT):
    """Project from two prior seasons. Returns dict of projection arrays."""
    k_overall = {"bat": k_bat, "pit": k_pit}
    n_bat, n_pit, n_park = pop.n_bat, pop.n_pit, pop.n_park
    pf_hat = estimate_park_factors(seasons, n_park)
    park_adjust(seasons, pf_hat)

    lg_cnt = sum(len(s["woba"]) for s in seasons)
    lg = sum(s["adj_woba"].sum() for s in seasons) / lg_cnt

    # league wOBA by handedness cell (park-adjusted); switch treated as opp-hand
    def eff_same(s):
        return (s["bat_hand"] == s["pit_hand"]) & (s["bat_hand"] != 2)

    lg_cell = {}
    for bh in (0, 1, 2):
        for ph in (0, 1):
            c = t = 0.0
            for s in seasons:
                m = (s["bat_hand"] == bh) & (s["pit_hand"] == ph)
                c += m.sum()
                t += s["adj_woba"][m].sum()
            lg_cell[(bh, ph)] = t / max(c, 1)

    def side_proj(key, hands, k_overall, k_split, opp_of, n_ids):
        cnt, tot = _wsum(seasons, key, MARCEL_W, n_ids=n_ids)
        overall = (tot + k_overall * lg) / (cnt + k_overall)

        same_cnt, same_tot = _wsum(seasons, key, MARCEL_W, n_ids=n_ids,
                                   mask_fn=eff_same)
        opp_cnt, opp_tot = cnt - same_cnt, tot - same_tot
        obs_split = (opp_tot / np.maximum(opp_cnt, 1)
                     - same_tot / np.maximum(same_cnt, 1))
        obs_split[(same_cnt < 1) | (opp_cnt < 1)] = 0.0

        # league mean split by hand
        lg_split = {}
        for h in np.unique(hands):
            m = hands == h
            sc, so = same_cnt[m].sum(), same_tot[m].sum()
            oc, oo = opp_cnt[m].sum(), opp_tot[m].sum()
            lg_split[h] = (oo / max(oc, 1)) - (so / max(sc, 1))
        lg_split_v = np.array([lg_split.get(h, 0.0) for h in hands])
        if 2 in lg_split:
            lg_split_v[hands == 2] = 0.0

        k = np.array([k_split[h] for h in hands])
        reg_split = (same_cnt * obs_split + k * lg_split_v) / (same_cnt + k)

        f_same = same_cnt.sum() / max(cnt.sum(), 1)  # league share same-hand
        vs_same = overall - (1 - f_same) * reg_split
        vs_opp = overall + f_same * reg_split
        return overall, vs_same, vs_opp

    b_overall, b_same, b_opp = side_proj(
        "bat", pop.bat_hand, k_overall["bat"], K_SPLIT_BAT, None, n_bat)
    p_overall, p_same, p_opp = side_proj(
        "pit", pop.pit_hand, k_overall["pit"], K_SPLIT_PIT, None, n_pit)

    # express as vs-L / vs-R
    def to_vs_hand(hands, same, opp, overall, two_hands):
        vs = {}
        for h in two_hands:  # opponent hand
            is_same = hands == h
            v = np.where(is_same, same, opp)
            if 2 in np.unique(hands):
                v = np.where(hands == 2, overall, v)
            vs[h] = v
        return vs

    bat_vs = to_vs_hand(pop.bat_hand, b_same, b_opp, b_overall, (0, 1))
    pit_vs = to_vs_hand(pop.pit_hand, p_same, p_opp, p_overall, (0, 1))

    return dict(bat_vs=bat_vs, pit_vs=pit_vs, lg=lg, lg_cell=lg_cell,
                pf_hat=pf_hat, bat_overall=b_overall, pit_overall=p_overall)


def tune_k(prior_seasons, target_season, pop,
           grid=(250, 500, 1000, 2000, 4000, 8000, 16000)):
    """Calibrate overall regression constants on observable data only:
    pick (k_bat, k_pit) minimizing MSE of the one-sided projections against
    realized wOBA in the target (training) season. This mimics how a real
    projection vendor calibrates, and yields approximately unbiased inputs
    so the matchup formula isn't asked to fix projection miscalibration."""
    y = target_season["woba"]

    def side_mse(k_bat, k_pit):
        proj = project(prior_seasons, pop, k_bat=k_bat, k_pit=k_pit)
        B, P, Lc, L, PF = matchup_inputs(proj, target_season)
        return np.mean((B - y) ** 2), np.mean((P - y) ** 2)

    best_b = min(grid, key=lambda k: side_mse(k, K_PIT)[0])
    best_p = min(grid, key=lambda k: side_mse(best_b, k)[1])
    return best_b, best_p


def matchup_inputs(proj, season):
    """Per-PA formula inputs for a target season: B, P, L_cell, L, PF."""
    b, p = season["bat"], season["pit"]
    bh, ph = season["bat_hand"], season["pit_hand"]
    B = np.where(ph == 1, proj["bat_vs"][1][b], proj["bat_vs"][0][b])
    # pitcher vs batter side: switch hitters bat opposite the pitcher
    eff_bh = np.where(bh == 2, 1 - ph, bh)
    P = np.where(eff_bh == 1, proj["pit_vs"][1][p], proj["pit_vs"][0][p])
    L_cell = np.empty(len(b))
    for bhv in (0, 1, 2):
        for phv in (0, 1):
            m = (bh == bhv) & (ph == phv)
            L_cell[m] = proj["lg_cell"][(bhv, phv)]
    PF = proj["pf_hat"][season["park"]]
    return B, P, L_cell, np.full(len(b), proj["lg"]), PF
