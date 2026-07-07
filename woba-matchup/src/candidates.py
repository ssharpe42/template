"""Candidate matchup formulas.

Every candidate maps (B, P, L_cell, L_overall, PF) -> expected matchup wOBA,
with a small vector of free parameters fit on training data.

Notation: B = batter projected wOBA vs the pitcher's hand, P = pitcher
projected wOBA-against vs the batter's side, L_cell = league wOBA for that
handedness cell, L = overall league wOBA, PF = park wOBA factor (ratio, ~1.0).
"""

import numpy as np
from scipy.special import ndtr, ndtri

EPS = 1e-6


def _logit(x, s=1.0):
    x = np.clip(x / s, EPS, 1 - EPS)
    return np.log(x / (1 - x))


def _inv_logit(z, s=1.0):
    return s / (1.0 + np.exp(-z))


class Candidate:
    name = ""
    p0 = np.array([])          # initial params
    reference = "cell"         # which league baseline it uses

    def predict(self, params, B, P, Lc, L, PF):
        raise NotImplementedError


class LeagueOnly(Candidate):
    name = "league-only baseline"
    p0 = np.array([1.0])

    def predict(self, th, B, P, Lc, L, PF):
        return Lc * PF ** th[0]


class BatterOnly(Candidate):
    name = "batter-only baseline"
    p0 = np.array([1.0])

    def predict(self, th, B, P, Lc, L, PF):
        return B * PF ** th[0]


class Additive(Candidate):
    """Marcel-style: E = (B + P - L_cell) * PF^k"""
    name = "additive (cell reference)"
    p0 = np.array([1.0])

    def predict(self, th, B, P, Lc, L, PF):
        return (B + P - Lc) * PF ** th[0]


class AdditiveOverallL(Candidate):
    """Same but with the *overall* league reference: platoon double-count demo."""
    name = "additive (overall-league reference)"
    reference = "overall"
    p0 = np.array([1.0])

    def predict(self, th, B, P, Lc, L, PF):
        return (B + P - L) * PF ** th[0]


class Multiplicative(Candidate):
    """E = L_cell * (B/L_cell) * (P/L_cell) * PF^k"""
    name = "multiplicative"
    p0 = np.array([1.0])

    def predict(self, th, B, P, Lc, L, PF):
        return B * P / Lc * PF ** th[0]


class OddsRatio(Candidate):
    """Tango odds-ratio / log5 with wOBA treated as a rate on (0,1):
    odds(E) = odds(B)*odds(P)/odds(L_cell); then E *= PF^k."""
    name = "odds ratio (s=1)"
    p0 = np.array([1.0])

    def predict(self, th, B, P, Lc, L, PF):
        z = _logit(B) + _logit(P) - _logit(Lc)
        return _inv_logit(z) * PF ** th[0]


class OddsRatioFreeScale(Candidate):
    """Odds ratio on wOBA/s with the ceiling s a free parameter."""
    name = "odds ratio (free scale s)"
    p0 = np.array([1.0, 1.0])

    def predict(self, th, B, P, Lc, L, PF):
        k, s = th[0], np.clip(th[1], 0.7, 3.0)
        z = _logit(B, s) + _logit(P, s) - _logit(Lc, s)
        return _inv_logit(z, s) * PF ** k


class MoreyZ(Candidate):
    """Morey-Z (Morey & Cohen 2015): probit analogue of log5.
    E = Phi( (z_B + z_P - 2*z_L)/sqrt(2) + z_L ) with z = ndtri(rate).
    Implemented in the paper's form: zE = (zB - zL)/sqrt2 + (zP - zL)/sqrt2 + zL.
    """
    name = "Morey-Z (probit)"
    p0 = np.array([1.0])

    def predict(self, th, B, P, Lc, L, PF):
        zB, zP, zL = (ndtri(np.clip(x, EPS, 1 - EPS)) for x in (B, P, Lc))
        z = (zB - zL) / np.sqrt(2) + (zP - zL) / np.sqrt(2) + zL
        return ndtr(z) * PF ** th[0]


class FreeLogOdds(Candidate):
    """Generalized log-odds regression (nests odds ratio at a=b=1, c0=0):
    logit(E) = logit(L_cell) + a*(logit B - logit L_cell)
                             + b*(logit P - logit L_cell) + c0;  E *= PF^k
    """
    name = "free log-odds"
    p0 = np.array([1.0, 1.0, 0.0, 1.0])

    def predict(self, th, B, P, Lc, L, PF):
        a, b, c0, k = th
        z = _logit(Lc) + a * (_logit(B) - _logit(Lc)) + b * (_logit(P) - _logit(Lc)) + c0
        return _inv_logit(z) * PF ** k


class FreeLinear(Candidate):
    """E = L_cell + a(B-L_cell) + b(P-L_cell) + c0 + k*L_cell*(PF-1)"""
    name = "free linear"
    p0 = np.array([1.0, 1.0, 0.0, 1.0])

    def predict(self, th, B, P, Lc, L, PF):
        a, b, c0, k = th
        return Lc + a * (B - Lc) + b * (P - Lc) + c0 + k * Lc * (PF - 1.0)


class FreeLinearInteraction(Candidate):
    """Linear plus batter x pitcher interaction:
    E = Lc + a(B-Lc) + b(P-Lc) + g(B-Lc)(P-Lc)/Lc + c0 + k*Lc*(PF-1).
    The fitted g measures the empirical interaction directly. Implied values:
    additive g=0; odds ratio g=(1-2Lc)/(1-Lc) ~ 0.55 at Lc=.31; multiplicative
    g=1. So g locates the truth between the classic functional forms."""
    name = "free linear + interaction"
    p0 = np.array([1.0, 1.0, 0.5, 0.0, 1.0])

    def predict(self, th, B, P, Lc, L, PF):
        a, b, g, c0, k = th
        dB, dP = B - Lc, P - Lc
        return Lc + a * dB + b * dP + g * dB * dP / Lc + c0 + k * Lc * (PF - 1.0)


ALL_CANDIDATES = [
    LeagueOnly(), BatterOnly(), AdditiveOverallL(), Additive(),
    Multiplicative(), MoreyZ(), OddsRatio(), OddsRatioFreeScale(),
    FreeLinear(), FreeLogOdds(), FreeLinearInteraction(),
]
