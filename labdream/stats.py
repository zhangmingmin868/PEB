"""Pure-Python statistical distributions used by the PBE module.

Only what the FDA PBE procedure needs: the inverse of the Student t and the
chi-square cumulative distribution functions (Excel T.INV / CHISQ.INV).
No third-party packages, so results do not depend on library versions.

Accuracy: relative error < 1e-10 against scipy.stats over the ranges used
(df 1 – 10 000, p 0.0001 – 0.9999), see tests/selftest_pbe.py.
"""
from __future__ import annotations

import math

_EPS = 1e-16
_FPMIN = 1e-300


# ---------------------------------------------------------------- gamma
def _gammainc_series(a: float, x: float) -> float:
    ap, s, d = a, 1.0 / a, 1.0 / a
    for _ in range(100000):
        ap += 1.0
        d *= x / ap
        s += d
        if abs(d) < abs(s) * _EPS:
            break
    return s * math.exp(-x + a * math.log(x) - math.lgamma(a))


def _gammainc_cf(a: float, x: float) -> float:
    """Upper regularized gamma Q(a, x) by Lentz continued fraction."""
    b = x + 1.0 - a
    c = 1.0 / _FPMIN
    d = 1.0 / b
    h = d
    for i in range(1, 100000):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < _FPMIN:
            d = _FPMIN
        c = b + an / c
        if abs(c) < _FPMIN:
            c = _FPMIN
        d = 1.0 / d
        de = d * c
        h *= de
        if abs(de - 1.0) < _EPS:
            break
    return math.exp(-x + a * math.log(x) - math.lgamma(a)) * h


def gammainc_p(a: float, x: float) -> float:
    """Lower regularized incomplete gamma P(a, x)."""
    if x <= 0:
        return 0.0
    if x < a + 1.0:
        return _gammainc_series(a, x)
    return 1.0 - _gammainc_cf(a, x)


def chi2_cdf(x: float, df: float) -> float:
    return gammainc_p(df / 2.0, x / 2.0)


# ---------------------------------------------------------------- beta
def _betacf(a: float, b: float, x: float) -> float:
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < _FPMIN:
        d = _FPMIN
    d = 1.0 / d
    h = d
    for m in range(1, 100000):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < _FPMIN:
            d = _FPMIN
        c = 1.0 + aa / c
        if abs(c) < _FPMIN:
            c = _FPMIN
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < _FPMIN:
            d = _FPMIN
        c = 1.0 + aa / c
        if abs(c) < _FPMIN:
            c = _FPMIN
        d = 1.0 / d
        de = d * c
        h *= de
        if abs(de - 1.0) < _EPS:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta I_x(a, b)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbt = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)
    if x < (a + 1.0) / (a + b + 2.0):
        return math.exp(lbt) * _betacf(a, b, x) / a
    return 1.0 - math.exp(lbt) * _betacf(b, a, 1.0 - x) / b


def t_cdf(t: float, df: float) -> float:
    t2 = t * t
    if t2 < df:
        # central part: P(|T| < t) = I_y(1/2, df/2), y = t²/(df+t²) – no cancellation
        half = 0.5 * betainc(0.5, df / 2.0, t2 / (df + t2))
        return 0.5 + half if t >= 0 else 0.5 - half
    tail = 0.5 * betainc(df / 2.0, 0.5, df / (df + t2))
    return 1.0 - tail if t >= 0 else tail


# ---------------------------------------------------------------- inverses
def _invert(cdf, p: float, lo: float, hi: float) -> float:
    """Monotone inversion: expand bracket, then bisection to full precision."""
    while cdf(hi) < p:
        lo, hi = hi, hi * 2.0 if hi > 0 else 1.0
    while cdf(lo) > p:
        hi, lo = lo, lo * 2.0 if lo < 0 else lo / 2.0
    for _ in range(400):
        mid = 0.5 * (lo + hi)
        if mid == lo or mid == hi:
            break
        if cdf(mid) < p:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def chi2_ppf(p: float, df: float) -> float:
    """Inverse of the chi-square CDF (Excel CHISQ.INV(p, df))."""
    if not 0.0 < p < 1.0 or df <= 0:
        raise ValueError("chi2_ppf: need 0 < p < 1 and df > 0")
    return _invert(lambda x: chi2_cdf(x, df), p, 1e-300, max(1.0, df * 2.0))


def t_ppf(p: float, df: float) -> float:
    """Inverse of the Student t CDF (Excel T.INV(p, df))."""
    if not 0.0 < p < 1.0 or df <= 0:
        raise ValueError("t_ppf: need 0 < p < 1 and df > 0")
    if p == 0.5:
        return 0.0
    if p < 0.5:
        return -t_ppf(1.0 - p, df)
    return _invert(lambda x: t_cdf(x, df), p, 0.0, 10.0)
