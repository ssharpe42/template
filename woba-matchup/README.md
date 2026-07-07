# wOBA Matchup Formula Study

Research, mathematical analysis, and holdout-tested optimization of a formula for
estimating the expected wOBA of a batter–pitcher matchup from:

- the batter's projected wOBA vs the pitcher's hand,
- the pitcher's projected wOBA-against vs the batter's side,
- league context, and the park factor.

**The findings, recommended formula, and fitted parameters are in [REPORT.md](REPORT.md).**

## Layout

```
run_study.py       full pipeline: simulate -> project -> fit on train -> evaluate holdout
aggregate.py       multi-seed summary tables (markdown)
src/simulate.py    calibrated event-level PA generator (the test bed)
src/project.py     Marcel-style projection layer (produces the formula's inputs)
src/candidates.py  candidate formulas (additive, multiplicative, log5/odds ratio,
                   Morey-Z, free-coefficient log-odds/linear/interaction)
src/fit_eval.py    parameter fitting, holdout metrics, calibration, subgroup bias
results/           per-seed results JSON + run logs
```

## Reproduce

```bash
pip install numpy scipy
python3 run_study.py 42   # one seed (~3 min); repeat with 7, 123
python3 aggregate.py      # summary tables across seeds
```

Baseball data hosts were unreachable from this environment, so the test bed is a
calibrated event-level Monte Carlo (see REPORT.md §3 and §6). To re-run on real data,
replace the simulated season dicts in `run_study.py` with per-PA arrays built from
Retrosheet/Statcast (fields: `bat`, `pit`, `park`, `bat_hand`, `pit_hand`, `woba`);
everything downstream is unchanged.
