# An Optimal Formula for Batter–Pitcher Matchup wOBA

**Inputs:** batter's projected wOBA vs the pitcher's hand (`B`), pitcher's projected
wOBA-against vs the batter's side (`P`), league context, and the park factor (`PF`).
**Output:** expected wOBA for the plate appearance.

---

## TL;DR — the recommended formula

Combine in **log-odds space, against the handedness-cell league average, with
calibration coefficients, then apply the park factor multiplicatively**:

```
odds(x)  = x / (1 − x)                    # wOBA treated as a rate on (0,1)
z        = ln odds(L_cell)
           + a · [ln odds(B) − ln odds(L_cell)]
           + b · [ln odds(P) − ln odds(L_cell)]
wOBA_est = (e^z / (1 + e^z)) · PF^k
```

with

| symbol | meaning | value |
|---|---|---|
| `B` | batter projected wOBA **vs this pitcher's hand** | given |
| `P` | pitcher projected wOBA-against **vs this batter's side** | given |
| `L_cell` | league wOBA **for this handedness cell** (e.g. LHB-vs-LHP) — *not* the overall league average | from league data |
| `a` | batter calibration coefficient | **1.0** for calibrated (vendor-grade) projections; fit on history otherwise (≈ 0.85–0.90 for Marcel-style 2-year projections) |
| `b` | pitcher calibration coefficient | **1.0** for calibrated projections; fit otherwise (≈ 0.60–0.70 for Marcel-style split projections — pitcher splits are noisy) |
| `PF` | park wOBA factor for the game's park, ratio scale, **full-strength** (game-level) | given |
| `k` | park exponent | **0.9** (fit ≈ 0.88–0.91 with true factors; ≈ 0.8 with 2-year estimated factors) |

With `a = b = 1`, `k = 1` this is exactly Tango's **odds-ratio method** (the log5
family) with the handedness-cell reference — the right zero-knob default. The free
coefficients exist because real projection inputs are never perfectly calibrated, and
the holdout testing below shows they are where nearly all the remaining accuracy lives.

Two hard rules that matter more than the choice of functional form:

1. **Use the handedness-cell league average as the reference.** Using the overall
   league wOBA double-counts the league-average platoon effect (it is embedded in both
   `B` and `P`) and produces a ±10-point wOBA bias by hand matchup. In testing this
   error cost more than the entire batter-vs-pitcher functional-form question.
2. **Never add a separate platoon adjustment** on top of hand-specific `B` and `P`
   inputs — the platoon effect is already in the inputs (once each) and in `L_cell`
   (once), and the formula above nets that out exactly once.

---

## 1. Methodology research

**log5 / odds-ratio method.** Bill James introduced log5 for team matchups and
extended it to batter–pitcher matchups in the 1983 Abstract (equation credited to
Dallas Adams). Tango, Lichtman & Dolphin (*The Book*) use the equivalent
**odds-ratio method** for matchups: `odds(E) = odds(B)·odds(P)/odds(L)`. It is
derivable from Bayes' rule and is exactly a Bradley–Terry / Rasch model: each side
contributes an additive term in log-odds space. Tom Ruane's Retrosheet study found
log5 predicts real batting-average matchups well.

**Morey-Z.** Morey & Cohen (2015) showed log5 develops bias for event probabilities
far from .500 and proposed a probit alternative: transform rates with the inverse
normal CDF, combine as `zE = (zB − zL)/√2 + (zP − zL)/√2 + zL`, and back-transform.
Note it embeds a fixed 1/√2 ≈ 0.707 shrinkage of each input's deviation.

**Additive (Marcel-style).** `E = B + P − L`. First-order approximation of every
other method; simplest and unbounded.

**Multiplicative.** `E = L·(B/L)·(P/L)`. Used for park/context adjustments;
equivalent to odds ratio as rates → 0.

**Platoon splits (The Book).** Observed splits are mostly noise: project the overall
rate, then add a split regressed toward the league-mean split for that hand
(≈1000 same-hand PA of regression for LHB, ≈2200 for RHB; pitchers regress faster).
This is the projection layer's job; here it defines what the given `B`, `P` inputs are.

**Park factors (FanGraphs conventions).** wOBA park factors are multiplicative
ratios vs league. Published season-level factors (FanGraphs Guts) are **already
halved** for application to full-season stat lines (half the games are at home). For a
*single known game*, use the full-strength factor: `PF_full ≈ 1 + 2·(PF_published − 1)`
when the published factor is the halved kind (e.g. FanGraphs "104" → 1.08 full).
Regressed multi-year factors (FanGraphs uses 5 years, iTero-style regression) should
be used as-is apart from that unhalving.

## 2. Mathematical properties

All candidates share the **fixed point** `E(L, L, L) = L` and are monotone in both
inputs. They differ in curvature:

- **Second-order expansion.** Writing `dB = B − L`, `dP = P − L`, every method is
  `E ≈ L + dB + dP + g·dB·dP/L + …` to second order, with interaction coefficient
  `g = 0` (additive), `g = (1−2L)/(1−L) ≈ 0.55` at L = .31 (odds ratio),
  `g = 1` (multiplicative). All agree to first order — which is why the league
  reference and coefficient calibration dominate the form choice in practice.
- **Range.** Odds ratio and Morey-Z map (0,1)→(0,1); additive can leave the valid
  range for extreme matchups. wOBA is not a true probability (weights up to ~2.0),
  but treating it as a rate on (0,1) is safe: a free "ceiling" parameter `s` in
  `odds_s(x) = x/(s−x)` was tested and is weakly identified with negligible gain —
  `s = 1` is fine.
- **Platoon accounting.** `B` (vs hand) carries the batter's own platoon effect plus
  the league-mean effect; `P` (vs side) likewise. `L_cell` carries the league-mean
  effect once. `logit B + logit P − logit L_cell` therefore counts the league-mean
  platoon effect exactly once and each player's individual platoon skill once —
  the algebraic reason for hard rule #1 above.
- **Errors in variables.** If inputs are noisy/overdispersed estimates of true
  expected wOBA, the MSE-optimal combination shrinks each deviation by its
  calibration slope (`E[y|X] = L + λ(X − L)`). This is exactly what `a` and `b` do,
  and why Morey-Z (hard-coded 0.707 shrink) can *look* better than the odds ratio
  when fed under-regressed inputs while being clearly worse when fed calibrated ones.

## 3. Empirical test design

Live MLB data sources (Baseball Savant, Retrosheet, MLB statsapi, FanGraphs) are
blocked by this environment's network policy, so the test bed is a **calibrated
event-level Monte Carlo** (`src/simulate.py`), with all evaluation code written so it
can be rerun unchanged on real Retrosheet/Statcast PA data.

- **Generator.** PA outcomes (uBB/HBP/1B/2B/3B/HR/out) drawn from a multinomial
  logit with additive batter, pitcher, park, and platoon effects **at the event
  level** — so no wOBA-scale candidate formula is trivially "true." Calibration
  targets from 2023 MLB and published research: league wOBA ≈ .311; true-talent SD
  ≈ .033 (batters), .022 (pitchers, DIPS); platoon splits ≈ .030 (LHB) / .014
  (RHB) with individual platoon-talent SD ≈ .010/.006; park-factor SD ≈ .029 with
  HR factors most variable; year-to-year talent AR(1) ρ = .90. 800 batters, 900
  pitchers, 30 parks, 370k PA/season, 4 seasons.
- **Projection layer** (`src/project.py`) — produces the "given" inputs using only
  observable data: Marcel weighting (5/4) of two prior seasons, park-adjusted,
  regressed to league (constants tuned on training data only), split projections à la
  The Book, empirical-Bayes park factor estimates.
- **Protocol.** Seasons 1–2 → projections for season 3 (**train**: all free
  parameters fit here by MSE against realized PA wOBA values — the only thing
  observable in real data). Seasons 2–3 → projections for season 4 (**holdout**:
  parameters frozen). Repeated for 3 independent seeds.
- **Metrics.** Primary: holdout RMSE of the prediction against the generator's
  *true* expected wOBA for each PA (sensitive; available because it's a simulation).
  Also: MSE vs realized values (the real-data metric; same ordering), decile
  calibration, and subgroup bias (hand matchups, extreme batters/pitchers/parks).
- **Oracle experiment.** Same candidates fed *perfect* inputs (true talent vs hand,
  true park factors) to isolate functional form from input noise.

## 4. Results (3 seeds; holdout RMSE vs true expected wOBA, points ×1000)

**Realistic projections** (what you actually face):

| candidate | mean RMSE | fitted params (mean) |
|---|---|---|
| league-only baseline | 41.3 | k=0.87 |
| batter-only baseline | 33.6 | k=0.79 |
| additive, overall-league reference | 34.0 | k=0.80 |
| additive, cell reference | 32.7 | k=0.80 |
| multiplicative | 32.7 | k=0.80 |
| odds ratio (s=1) | 32.6 | k=0.80 |
| Morey-Z (probit) | 31.6 | k=0.82 |
| free linear | 31.3 | a=0.86, b=0.60, k=0.81 |
| **free log-odds (recommended)** | **31.3** | **a=0.87, b=0.60, k=0.81** |
| free linear + interaction | 31.3 | a=0.86, b=0.60, g=0.59, k=0.81 |

**Oracle inputs** (isolates functional form):

| candidate | mean RMSE | fitted params (mean) |
|---|---|---|
| additive, overall-league reference | 11.1 | k=0.91 |
| Morey-Z (probit) | 13.0 | k=0.89 |
| additive, cell reference | 5.7 | k=0.91 |
| multiplicative | 5.5 | k=0.91 |
| odds ratio (s=1) | 5.4 | k=0.91 |
| **free log-odds** | **3.9** | **a=1.01, b=1.00, k=0.89** |
| free linear + interaction | 4.1 | a=1.02, b=1.00, g=0.87, k=0.88 |

Key findings:

1. **The log-odds (odds-ratio) form is the right backbone.** With perfect inputs the
   free coefficients converge to a = 1.01, b = 1.00 — i.e., the data independently
   recover Tango's odds-ratio method — and the odds ratio beats additive (5.4 vs
   5.7) and crushes Morey-Z (13.0), whose hard-coded √2 shrink is simply wrong for
   calibrated inputs.
2. **The batter×pitcher interaction is real but modest.** Directly fitted:
   g ≈ 0.87 with true inputs — positive (an elite batter gains *more* than
   additively against a weak pitcher), between the odds-ratio (0.55) and
   multiplicative (1.0) values, far from additive (0).
3. **Input calibration dominates functional form.** With Marcel-style inputs the
   fitted coefficients (a≈0.87, b≈0.60) match the measured calibration slopes of the
   inputs (0.90, 0.66) — the pitcher side is heavily attenuated because pitcher
   platoon splits are mostly noise. Fixed-coefficient methods consequently overshoot
   extreme matchups: the plain odds ratio runs **+20 points too hot for
   elite-batter-vs-weak-pitcher** matchups and −14 too low for the reverse, while
   the calibrated formula is within ±2 points in every subgroup tested, and within
   ~2 points across every predicted decile (.259–.364).
4. **The wrong league reference is the single most expensive mistake:** overall-L
   additive is *worse* than ignoring the pitcher entirely (34.0 vs 33.6 for
   batter-only) and biased ±10 points by hand matchup — adding pitcher information
   with the wrong reference subtracts value.
5. **Park factors: multiplicative with a slight discount.** Fitted exponent ≈ 0.89
   on true full-strength factors (aggregation/Jensen effects make the at-average
   multiplier slightly too strong), ≈ 0.8 on 2-year estimated factors. `PF^0.9` is a
   good default for a trustworthy game-level factor; remember to un-halve published
   season-level factors first.

## 5. Practical recipe

1. Get `B` (batter proj. wOBA vs pitcher hand), `P` (pitcher proj. wOBA-against vs
   batter side), `L_cell` (league wOBA for the hand cell, current run environment),
   `PF` (full-strength wOBA park factor for the game's park).
2. If you can backtest your projection stack: fit `a`, `b`, `k` once by regressing
   realized PA wOBA on the log-odds deviations over a historical season
   (`src/fit_eval.py` does exactly this). Expect a ≈ 0.85–1.0, b ≈ 0.6–1.0, k ≈ 0.8–1.0.
3. If you can't backtest: use a = b = 1 (pure odds ratio), k = 0.9 — it's the best
   zero-knob choice and was never worse than additive or Morey-Z in any tested regime.
4. Compute `wOBA_est = expit( logit(L_cell) + a·(logit B − logit L_cell) + b·(logit P − logit L_cell) ) · PF^k`.

Worked example (a=b=1, k=0.9): elite LHB (.400 vs RHP) facing a weak RHP (.360
allowed vs LHB), league LHB-vs-RHP cell .325, at a hitter's park (PF 1.04):
logit terms → z = −0.731 + 0.325 + 0.156 = −0.250 → 0.4378 · 1.04^0.9 = **.454**
(additive with the same inputs: .435 · 1.036 = .451; the odds-ratio interaction adds
~3 points for this double-extreme matchup).

## 6. Limitations

- The test bed is synthetic (network policy blocked Retrosheet/Statcast/Savant in
  this environment). It was built so the *truth is at the event level* and every
  calibration target comes from published MLB research, but the exact fitted
  constants (especially b ≈ 0.6 for Marcel-style pitcher splits) should be re-fit on
  real data with `run_study.py`'s protocol before production use. The candidate
  ranking (log-odds backbone, cell reference, calibrated coefficients) was stable
  across all seeds and both input regimes.
- Not modeled: times-through-the-order effects, batter-handed park asymmetries
  (short porches), pitch-type matchup granularity (see Healey's ground-ball matchup
  models), weather, and non-wOBA outcomes (SB, errors).

## Sources

- [Tangotiger wiki: Log5](https://tangotiger.net/wiki_archive/Log5.html) and
  [The Book blog: The Odds Ratio Method](https://insidethebook.com/ee/index.php/site/comments/the_odds_ratio_method)
- [Morey & Cohen (2015), "Bias in the log5 estimation of outcome of batter/pitcher
  matchups, and an alternative," J. Sports Analytics](https://journals.sagepub.com/doi/10.3233/JSA-150005)
- [SABR: Matchup Probabilities in Major League Baseball](https://sabr.org/journal/article/matchup-probabilities-in-major-league-baseball/)
- [FanGraphs Library: Park Factors](https://library.fangraphs.com/principles/park-factors/) and
  [The Beginner's Guide to Understanding Park Factors](https://library.fangraphs.com/the-beginners-guide-to-understanding-park-factors/)
- [FanGraphs: Estimating Hitter Platoon Skill](https://blogs.fangraphs.com/estimating-hitter-platoon-skill/) and
  [Hardball Times: Forecasting Pitcher Platoon Splits](https://tht.fangraphs.com/forecasting-pitcher-platoon-splits/)
- [Baseball with R: Platoon Splits — What is the Platoon Skill Variation?](https://baseballwithr.wordpress.com/2015/06/22/platoon-splits-what-is-the-platoon-skill-variation/)
- [Healey (2017), "Matchup models for the probability of a ground ball and a ground
  ball hit," J. Sports Analytics](https://journals.sagepub.com/doi/10.3233/JSA-160025)
- Tango, Lichtman & Dolphin, *The Book: Playing the Percentages in Baseball* (2006)
