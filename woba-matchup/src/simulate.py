"""Event-level Monte Carlo generator for MLB plate appearances.

The generative model lives at the *event* level (uBB/HBP/1B/2B/3B/HR/out) with
additive batter / pitcher / park / platoon effects in multinomial-logit space.
No wOBA-scale matchup formula is exactly "true" under this generator, so
comparing wOBA-scale candidate formulas against it is a meaningful test.

Calibration targets (2023 MLB / published sabermetric estimates):
  - league event rates per PA: uBB .0810, HBP .0115, 1B .1415, 2B .0447,
    3B .0039, HR .0319  -> league wOBA ~ .315
  - SD of true batter wOBA talent  ~ .033
  - SD of true pitcher wOBA-against talent ~ .022 (pitchers influence less; DIPS)
  - mean platoon split (opp-hand minus same-hand wOBA): LHB ~ .030, RHB ~ .014
  - SD of true platoon talent: LHB ~ .010, RHB ~ .006 (The Book)
  - SD of true park wOBA factor ~ .02 (ratio scale), HR factors most variable
  - year-to-year talent AR(1) rho = .90
"""

from dataclasses import dataclass, field
import numpy as np

EVENTS = ["uBB", "HBP", "1B", "2B", "3B", "HR"]  # reference category: out
W = np.array([0.696, 0.726, 0.883, 1.244, 1.569, 2.004])  # 2023 wOBA weights
Q = np.array([0.0810, 0.0115, 0.1415, 0.0447, 0.0039, 0.0319])  # league rates
LOGIT_BASE = np.log(Q / (1.0 - Q.sum()))  # log-odds vs "out"

# category loadings for a "power profile" talent axis
POWER = np.array([0.30, 0.00, -0.40, 0.50, 0.20, 1.00])

RNG = np.random.default_rng


def softmax_probs(eta):
    """eta: (n,6) non-out logits vs out. Returns (n,7) probs [events..., out]."""
    z = np.exp(eta)
    denom = 1.0 + z.sum(axis=1, keepdims=True)
    p = z / denom
    return np.concatenate([p, 1.0 - p.sum(axis=1, keepdims=True)], axis=1)


def woba_of_eta(eta):
    """Expected wOBA for logit rows eta (n,6)."""
    p = softmax_probs(eta)[:, :6]
    return p @ W


def _uniform_shift_scale():
    """d(wOBA)/d(uniform log-odds shift) at league baseline (numeric)."""
    e = 1e-4
    base = woba_of_eta(LOGIT_BASE[None, :])[0]
    up = woba_of_eta((LOGIT_BASE + e)[None, :])[0]
    return (up - base) / e


@dataclass
class Population:
    """True talent for one universe of batters, pitchers, parks."""
    n_bat: int
    n_pit: int
    n_park: int
    bat_eff: np.ndarray      # (n_bat, 6) log-odds effects
    pit_eff: np.ndarray      # (n_pit, 6)
    park_eff: np.ndarray     # (n_park, 6)
    bat_hand: np.ndarray     # 0=R, 1=L, 2=switch
    pit_hand: np.ndarray     # 0=R, 1=L
    bat_platoon: np.ndarray  # individual same-hand penalty (uniform log-odds)
    pit_platoon: np.ndarray
    bat_home: np.ndarray     # park index per batter
    platoon_mu: np.ndarray   # mean same-hand penalty by batter hand [R, L]
    bat_pa_mean: np.ndarray  # expected PA per season
    pit_pa_mean: np.ndarray


def make_population(n_bat=800, n_pit=900, n_park=30, seed=1):
    rng = RNG(seed)
    scale = _uniform_shift_scale()  # ~0.21 wOBA per unit uniform shift

    def talent(n, woba_sd, power_sd, cat_sd, rng):
        a = rng.normal(0, woba_sd / scale, n)           # overall axis
        c = rng.normal(0, power_sd, n)                  # power profile axis
        eps = rng.normal(0, cat_sd, (n, 6))             # idiosyncratic
        eff = a[:, None] + c[:, None] * POWER[None, :] + eps
        # re-center and rescale the overall axis so SD(true wOBA) hits target
        w = woba_of_eta(LOGIT_BASE[None, :] + eff)
        adj = (w - w.mean()) / scale
        eff += ((woba_sd / max(w.std(), 1e-9)) - 1.0) * adj[:, None]
        return eff

    bat_eff = talent(n_bat, 0.033, 0.22, 0.08, rng)
    pit_eff = talent(n_pit, 0.022, 0.12, 0.06, rng)

    park_eff = np.zeros((n_park, 6))
    park_sd = np.array([0.010, 0.0, 0.030, 0.060, 0.080, 0.100])
    park_eff += rng.normal(0, 1, (n_park, 6)) * park_sd[None, :]
    park_eff += rng.normal(0, 0.020, (n_park, 1))  # common run-environment axis
    park_eff -= park_eff.mean(axis=0, keepdims=True)

    bat_hand = rng.choice([0, 1, 2], size=n_bat, p=[0.55, 0.35, 0.10])
    pit_hand = rng.choice([0, 1], size=n_pit, p=[0.72, 0.28])

    # mean same-hand penalty by batter hand, calibrated to wOBA splits
    platoon_mu = np.array([0.014, 0.030]) / scale  # [RHB, LHB]
    bat_platoon = np.where(
        bat_hand == 1,
        rng.normal(0, 0.010 / scale, n_bat),
        rng.normal(0, 0.006 / scale, n_bat),
    )
    bat_platoon[bat_hand == 2] = 0.0
    pit_platoon = np.where(
        pit_hand == 1,
        rng.normal(0, 0.010 / scale, n_pit),
        rng.normal(0, 0.006 / scale, n_pit),
    )

    bat_pa_mean = np.clip(rng.gamma(3.0, 150.0, n_bat), 60, 700)
    pit_pa_mean = np.clip(rng.gamma(3.0, 127.0, n_pit), 60, 950)

    return Population(
        n_bat, n_pit, n_park, bat_eff, pit_eff, park_eff, bat_hand, pit_hand,
        bat_platoon, pit_platoon, rng.integers(0, n_park, n_bat), platoon_mu,
        bat_pa_mean, pit_pa_mean,
    )


def drift(pop, rho=0.90, seed=2):
    """AR(1) year-to-year talent drift for batters and pitchers."""
    rng = RNG(seed)
    scale = _uniform_shift_scale()
    s = np.sqrt(1 - rho ** 2)

    def step(eff, woba_sd, power_sd, cat_sd, rng):
        n = eff.shape[0]
        a = rng.normal(0, woba_sd / scale, n)
        c = rng.normal(0, power_sd, n)
        eps = rng.normal(0, cat_sd, (n, 6))
        innov = a[:, None] + c[:, None] * POWER[None, :] + eps
        return rho * eff + s * innov

    pop.bat_eff = step(pop.bat_eff, 0.033, 0.22, 0.08, rng)
    pop.pit_eff = step(pop.pit_eff, 0.022, 0.12, 0.06, rng)


def simulate_season(pop, season_pa=370_000, seed=3):
    """Simulate one season of PAs. Returns dict of per-PA arrays."""
    rng = RNG(seed)
    b = rng.choice(pop.n_bat, size=season_pa, p=pop.bat_pa_mean / pop.bat_pa_mean.sum())
    p = rng.choice(pop.n_pit, size=season_pa, p=pop.pit_pa_mean / pop.pit_pa_mean.sum())
    home = rng.random(season_pa) < 0.5
    park = np.where(home, pop.bat_home[b], rng.integers(0, pop.n_park, season_pa))

    bh, ph = pop.bat_hand[b], pop.pit_hand[p]
    same = (bh == ph) & (bh != 2)

    eta = (LOGIT_BASE[None, :]
           + pop.bat_eff[b]
           + pop.pit_eff[p]
           + pop.park_eff[park])
    pen = pop.platoon_mu[np.where(bh == 2, 0, bh)] + pop.bat_platoon[b] + pop.pit_platoon[p]
    eta -= (same * pen)[:, None]

    probs = softmax_probs(eta)          # (n, 7)
    true_mu = probs[:, :6] @ W          # true expected wOBA of each matchup
    # Gumbel-max trick for vectorized multinomial draw
    g = rng.gumbel(size=probs.shape)
    outcome = np.argmax(np.log(probs + 1e-300) + g, axis=1)  # 6 = out
    woba_val = np.where(outcome < 6, W[np.minimum(outcome, 5)], 0.0)

    return dict(bat=b, pit=p, park=park, bat_hand=bh, pit_hand=ph, same=same,
                outcome=outcome, woba=woba_val, true_mu=true_mu)


def oracle_inputs(pop, snapshot, season):
    """Perfect-information formula inputs from true talent.

    B = batter's true expected wOBA vs a league-average pitcher of the
    opposing hand in a neutral park (the definition a projection targets);
    P likewise for the pitcher; L_cell = season true mean by handedness cell;
    PF = true park factor. Isolates functional form from projection noise.
    """
    bat_eff, pit_eff = snapshot
    b, p = season["bat"], season["pit"]
    bh, ph = season["bat_hand"], season["pit_hand"]
    same = season["same"]

    mu_hand = pop.platoon_mu[np.where(bh == 2, 0, bh)]
    pen_b = mu_hand + pop.bat_platoon[b]          # batter's own platoon penalty
    pen_p = mu_hand + pop.pit_platoon[p]          # pitcher's own platoon edge

    eta_b = LOGIT_BASE[None, :] + bat_eff[b] - (same * pen_b)[:, None]
    eta_p = LOGIT_BASE[None, :] + pit_eff[p] - (same * pen_p)[:, None]
    B = woba_of_eta(eta_b)
    P = woba_of_eta(eta_p)

    L_cell = np.empty(len(b))
    for bhv in (0, 1, 2):
        for phv in (0, 1):
            m = (bh == bhv) & (ph == phv)
            if m.any():
                L_cell[m] = season["true_mu"][m].mean()
    PF = true_park_factors(pop)[season["park"]]
    L = np.full(len(b), season["true_mu"].mean())
    return B, P, L_cell, L, PF


def true_park_factors(pop):
    """True wOBA park factor per park (ratio to neutral)."""
    base = woba_of_eta(LOGIT_BASE[None, :])[0]
    pf = woba_of_eta(LOGIT_BASE[None, :] + pop.park_eff) / base
    return pf
