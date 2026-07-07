"""Run the full matchup-wOBA formula study.

Pipeline:
  seasons 1-2  ->  projections for season 3 (train)
  seasons 2-3  ->  projections for season 4 (holdout)
  fit candidate params on season 3, evaluate frozen params on season 4.

Everything downstream of the generator uses only observable quantities;
the generator's true expected wOBA is used solely for holdout diagnostics.
"""

import json
import sys
import numpy as np

sys.path.insert(0, "src")
import simulate as sim
import project as prj
from candidates import ALL_CANDIDATES
import fit_eval as fe

SEASON_PA = 370_000
SEED = int(sys.argv[1]) if len(sys.argv) > 1 else 42


def main():
    rng = np.random.default_rng(SEED)
    pop = sim.make_population(seed=SEED)

    seasons, snapshots = [], []
    for t in range(4):
        seasons.append(sim.simulate_season(pop, SEASON_PA, seed=SEED + 10 + t))
        snapshots.append((pop.bat_eff.copy(), pop.pit_eff.copy()))
        if t < 3:
            sim.drift(pop, seed=SEED + 100 + t)
        # NOTE: drift after simulating season t means season arrays reflect
        # talent as of that season; projections only ever see observed data.

    # sanity stats
    lg_woba = seasons[0]["woba"].mean()
    true_pf = sim.true_park_factors(pop)
    print(f"league wOBA season 1: {lg_woba:.4f}")
    print(f"true batter wOBA SD (season-4 talent): "
          f"{seasons[3]['true_mu'].std():.4f} (incl. matchup variation)")
    print(f"true park factor SD: {true_pf.std():.4f}")

    # calibrate projection regression constants on train season only
    k_bat, k_pit = prj.tune_k([seasons[1], seasons[0]], seasons[2], pop)
    print(f"tuned regression constants: k_bat={k_bat}, k_pit={k_pit} (weighted PA)")

    proj_train = prj.project([seasons[1], seasons[0]], pop, k_bat, k_pit)  # season 3
    proj_hold = prj.project([seasons[2], seasons[1]], pop, k_bat, k_pit)   # season 4

    train, hold = seasons[2], seasons[3]
    X_tr = prj.matchup_inputs(proj_train, train)
    X_ho = prj.matchup_inputs(proj_hold, hold)
    y_tr, y_ho = train["woba"], hold["woba"]
    mu_ho = hold["true_mu"]

    def run_experiment(tag, X_tr, X_ho):
        results, calib = [], {}
        for cand in ALL_CANDIDATES:
            th, train_mse = fe.fit(cand, X_tr, y_tr)
            pred, metrics = fe.evaluate(cand, th, X_ho, y_ho, mu_ho)
            entry = dict(
                name=cand.name,
                params=[round(float(v), 4) for v in np.atleast_1d(th)],
                train_mse=round(train_mse, 6),
                **{k: round(v, 6) for k, v in metrics.items()},
                subgroup_bias=fe.subgroup_bias(pred, mu_ho, hold, X_ho),
            )
            results.append(entry)
            calib[cand.name] = fe.calibration(pred, mu_ho)
            print(f"\n[{tag}] {cand.name}")
            print(f"  params: {entry['params']}")
            print(f"  holdout RMSE vs true E[wOBA]: {metrics['rmse_true']*1000:.3f} pts")
            print(f"  holdout MSE vs realized:      {metrics['mse_realized']:.6f}")
        best = min(results[2:], key=lambda r: r["rmse_true"])
        print(f"\n[{tag}] BEST (holdout RMSE vs truth): {best['name']}")
        return dict(results=results, calibration=calib)

    out = dict(league_woba=float(lg_woba), true_pf_sd=float(true_pf.std()),
               k_bat=k_bat, k_pit=k_pit)
    out["realistic"] = run_experiment("realistic projections", X_tr, X_ho)

    # oracle experiment: perfect-information inputs isolate functional form
    Xo_tr = sim.oracle_inputs(pop, snapshots[2], train)
    Xo_ho = sim.oracle_inputs(pop, snapshots[3], hold)
    out["oracle"] = run_experiment("oracle inputs", Xo_tr, Xo_ho)

    path = f"results/results_seed{SEED}.json"
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
