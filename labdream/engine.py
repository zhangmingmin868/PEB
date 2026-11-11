"""Aerodynamic particle size calculations.

Implements the log-probit method described for compendial cascade
impaction data analysis (Ph. Eur. 2.9.18, USP <601>):

* cumulative % undersize versus stage cut-off diameter
* MMAD, FPD/FPF (by size or by stage), GSD
* log-probit regression (R², slope, intercept) within probit 4–6
* LOD / NA rules
* group (size-band / stage-range) results
* delivered-dose uniformity comparison (75–125 %, 80–120 %, 85–115 %)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import NormalDist
from typing import List, Optional, Tuple

from .devices import scaled_ecd
from .model import Dataset, GROUP_OFF, GROUP_SIZE, GROUP_STAGE

_N = NormalDist()

NA = "NA"
LOD = "LOD"

# Cumulative percentages are limited to this range before the probit
# transformation (0 % and 100 % have no finite probit).
P_MIN = 0.1
P_MAX = 99.99
LOD_PERCENT = 2.0           # FPD (by size) below this cumulative % -> LOD
STAGE_MIN_PERCENT = 1.0     # stage counted as "significant" above this %
P16 = 100.0 * _N.cdf(-1.0)  # 15.87 %
P84 = 100.0 * _N.cdf(1.0)   # 84.13 %
P97 = 100.0 * _N.cdf(2.0)   # probit 7


def probit(p: float) -> float:
    """Probit (z + 5) of a percentage."""
    p = min(max(p, P_MIN), P_MAX)
    return _N.inv_cdf(p / 100.0) + 5.0


def inv_probit(y: float) -> float:
    return 100.0 * _N.cdf(y - 5.0)


@dataclass
class GroupResult:
    mode: str
    label_from: str
    label_to: str
    dose: object = 0.0          # float or LOD
    fraction: object = 0.0


@dataclass
class RunResult:
    run: int
    flow: float
    doses: float
    masses_per_dose: List[float]
    ecd: List[float]                      # per stage row at actual flow
    total: float = 0.0                     # Total dose per shot (metered)
    delivered_calc: float = 0.0            # total less device
    delivered_entered: float = 0.0
    fpd: object = 0.0
    fpf: object = 0.0
    mmad: object = NA
    gsd: object = NA
    r2: object = NA
    slope: object = NA
    intercept: object = NA
    n_reg: int = 0
    ct: float = 0.0                        # cumulative mass on size stages
    points: List[Tuple[float, float]] = field(default_factory=list)  # (d, cum %)
    # rows for printouts: (row index, cut-off of that row, mass, cumulative mass, cum %)
    cum_table: List[tuple] = field(default_factory=list)
    groups: List[GroupResult] = field(default_factory=list)
    cu: List[tuple] = field(default_factory=list)   # (lo, hi, pct or None, comment)
    shot_weight_mean: float = 0.0
    shot_weight_sd: float = 0.0


# ----------------------------------------------------------------------
def _interp_p_at_d(points, d):
    """Cumulative % undersize at diameter d (log-probit interpolation)."""
    pts = sorted(points)
    if len(pts) < 2:
        return pts[0][1] if pts else 0.0
    if d <= 0:
        return 0.0
    i = None
    for k in range(len(pts) - 1):
        if pts[k][0] <= d <= pts[k + 1][0]:
            i = k
            break
    if i is None:
        i = 0 if d < pts[0][0] else len(pts) - 2
    (d1, p1), (d2, p2) = pts[i], pts[i + 1]
    if p1 == p2:
        return p1
    x1, x2, x = math.log10(d1), math.log10(d2), math.log10(d)
    y1, y2 = probit(p1), probit(p2)
    if x2 == x1:
        return p1
    if y1 == y2:                       # both beyond the probit range
        return p2
    y = y1 + (y2 - y1) * (x - x1) / (x2 - x1)
    p = inv_probit(y)
    return min(max(p, 0.0), 100.0)


def _interp_d_at_p(points, p):
    """Diameter at which the cumulative % undersize equals p."""
    pts = sorted(points)
    if len(pts) < 2:
        return None
    i = None
    for k in range(len(pts) - 1):
        a, b = pts[k][1], pts[k + 1][1]
        if min(a, b) <= p <= max(a, b) and a != b:
            i = k
            break
    if i is None:
        # nearest two points (by distance in cumulative %)
        dist = [abs(q - p) for _, q in pts]
        order = sorted(range(len(pts)), key=lambda k: dist[k])
        cand = None
        for k in order:
            for j in (k - 1, k + 1):
                if 0 <= j < len(pts) and pts[j][1] != pts[k][1]:
                    cand = (min(j, k), max(j, k))
                    break
            if cand:
                break
        if cand is None:
            return None
        i = cand[0]
    (d1, p1), (d2, p2) = pts[i], pts[i + 1]
    y1, y2, y = probit(p1), probit(p2), probit(p)
    if y2 == y1:
        return None
    x1, x2 = math.log10(d1), math.log10(d2)
    x = x1 + (x2 - x1) * (y - y1) / (y2 - y1)
    return 10.0 ** x


def _regression(points):
    sel = [(math.log10(d), probit(p)) for d, p in points if P16 <= p <= P84 and d > 0]
    n = len(sel)
    if n < 2:
        return n, NA, NA, NA
    mx = sum(x for x, _ in sel) / n
    my = sum(y for _, y in sel) / n
    sxx = sum((x - mx) ** 2 for x, _ in sel)
    syy = sum((y - my) ** 2 for _, y in sel)
    sxy = sum((x - mx) * (y - my) for x, y in sel)
    if sxx == 0:
        return n, NA, NA, NA
    slope = sxy / sxx
    intercept = my - slope * mx
    if n == 2 or syy == 0:
        r2 = 1.0
    else:
        r2 = (sxy * sxy) / (sxx * syy)
    return n, r2, slope, intercept


# ----------------------------------------------------------------------
def analyse_run(ds: Dataset, idx: int) -> RunResult:
    dev = ds.dev
    run = ds.runs[idx]
    doses = run.doses if run.doses else 1.0
    active = [ds.row_active(r) for r in range(ds.n_rows)]
    m = [(run.masses[r] / doses) if active[r] else 0.0 for r in range(ds.n_rows)]
    flow = run.flow if run.flow > 0 else ds.cal_flow
    ecd = scaled_ecd(dev, ds.cal_flow, ds.ecd, flow)       # per stage row

    res = RunResult(run=idx + 1, flow=flow, doses=doses, masses_per_dose=m,
                    ecd=ecd, delivered_entered=run.delivered,
                    shot_weight_mean=run.shot_weight_mean,
                    shot_weight_sd=run.shot_weight_sd)
    res.total = sum(m)
    res.delivered_calc = res.total - m[0]

    # ---- size stages taking part in cumulative calculations -----------
    srows = [r for r in range(3 + dev.first_size_stage, ds.n_rows) if active[r]]
    ct = sum(m[r] for r in srows)
    res.ct = ct
    pts = []
    stage_cum = []                 # cumulative % including the stage itself
    if ct > 0:
        for k, r in enumerate(srows):
            below = sum(m[q] for q in srows[k + 1:])
            stage_cum.append(100.0 * (below + m[r]) / ct)
            if k < len(srows) - 1:
                d = ecd[r - 3]
                if d > 0:
                    pts.append((d, 100.0 * below / ct))
    res.points = sorted(pts)

    # cumulative table (filter upwards) for EP/USP printouts
    cum = 0.0
    tbl = []
    for k in range(len(srows) - 1, -1, -1):
        r = srows[k]
        cum += m[r]
        if k > 0:
            cut = ecd[srows[k - 1] - 3]
        else:
            cut = ecd[srows[0] - 4] if srows[0] - 4 >= 0 else None
        tbl.append((r, cut, m[r], cum, 100.0 * cum / ct if ct else 0.0))
    res.cum_table = tbl

    n_sig = sum(1 for c in stage_cum if c > STAGE_MIN_PERCENT)
    insufficient = ct <= 0 or n_sig < 3 or len(pts) < 2

    # ---- fine particle dose ---------------------------------------------
    if ds.fpd_by_stage:
        res.fpd = sum(m[r] for r in range(ds.fpd_stage_row, ds.n_rows) if active[r])
    else:
        if insufficient:
            res.fpd = LOD
        else:
            p = _interp_p_at_d(pts, ds.fpd_size)
            res.fpd = LOD if p < LOD_PERCENT else p / 100.0 * ct
    if res.fpd == LOD:
        res.fpf = LOD
    else:
        res.fpf = 100.0 * res.fpd / res.delivered_calc if res.delivered_calc else 0.0

    # ---- MMAD / GSD ----------------------------------------------------
    na = insufficient
    below_range = False
    if not na:
        last = srows[-1]
        if 100.0 * m[last] / ct > 50.0:          # >50 % on filter / MOC
            na = below_range = True
        if 100.0 * m[srows[0]] / ct > 50.0:      # >50 % on top stage
            na = True
    n, r2, slope, icpt = _regression(pts) if pts else (0, NA, NA, NA)
    if insufficient or below_range:
        r2, slope, icpt = NA, NA, NA
    res.n_reg, res.r2, res.slope, res.intercept = n, r2, slope, icpt
    if not na:
        mmad = _interp_d_at_p(pts, 50.0)
        if mmad is None or mmad <= 0:
            res.mmad = NA
        else:
            res.mmad = mmad
            lognormal = (r2 == NA) or (r2 >= ds.r2_limit)
            if lognormal:
                has_67 = any(P84 < p <= P97 for _, p in pts)
                gsd = None
                if has_67:
                    d84 = _interp_d_at_p(pts, P84)
                    if d84:
                        gsd = d84 / mmad
                else:
                    d16 = _interp_d_at_p(pts, P16)
                    if d16:
                        gsd = mmad / d16
                res.gsd = gsd if gsd else NA
            else:
                res.gsd = NA
    if res.mmad == NA:
        res.gsd = NA

    # ---- groups ----------------------------------------------------------
    for g in ds.groups:
        if g.mode == GROUP_OFF:
            res.groups.append(GroupResult(GROUP_OFF, "", ""))
            continue
        if g.mode == GROUP_STAGE:
            lo, hi = sorted((g.from_row, g.to_row))
            dose = sum(m[r] for r in range(lo, hi + 1) if active[r])
            frac = 100.0 * dose / res.delivered_calc if res.delivered_calc else 0.0
            res.groups.append(GroupResult(GROUP_STAGE, ds.row_titles[lo], ds.row_titles[hi],
                                          dose, frac))
            continue
        lo, hi = sorted((g.min_um, g.max_um))
        lab_lo, lab_hi = f"{lo:.2f} µm", f"{hi:.2f} µm"
        if insufficient:
            res.groups.append(GroupResult(GROUP_SIZE, lab_lo, lab_hi, LOD, LOD))
            continue
        p_lo = 0.0 if lo <= 0 else _interp_p_at_d(pts, lo)
        p_hi = 0.0 if hi <= 0 else _interp_p_at_d(pts, hi)
        if (lo > 0 and p_lo < LOD_PERCENT) or (hi > 0 and p_hi < LOD_PERCENT):
            res.groups.append(GroupResult(GROUP_SIZE, lab_lo, lab_hi, LOD, LOD))
            continue
        dose = max(0.0, (p_hi - p_lo)) / 100.0 * ct
        frac = 100.0 * dose / res.delivered_calc if res.delivered_calc else 0.0
        res.groups.append(GroupResult(GROUP_SIZE, lab_lo, lab_hi, dose, frac))

    # ---- delivered dose uniformity ----------------------------------------
    for lo, hi in ((75, 125), (80, 120), (85, 115)):
        if not run.delivered:
            res.cu.append((lo, hi, None, "Content Uniformity result not entered"))
        else:
            pct = 100.0 * res.delivered_calc / run.delivered
            ok = lo <= round(pct, 1) <= hi
            res.cu.append((lo, hi, pct, "Result within specification." if ok
                           else "Result outside specification."))
    return res


@dataclass
class Summary:
    runs: List[RunResult]

    def stats(self, getter):
        """mean, sd, %rsd of numeric values (LOD / NA excluded)."""
        vals = [getter(r) for r in self.runs]
        vals = [v for v in vals if isinstance(v, (int, float))]
        return mean_sd_rsd(vals)


def mean_sd_rsd(vals):
    n = len(vals)
    if n == 0:
        return NA, NA, NA
    mean = sum(vals) / n
    if n < 2:
        return mean, 0.0, 0.0
    sd = math.sqrt(sum((v - mean) ** 2 for v in vals) / (n - 1))
    rsd = 100.0 * sd / mean if mean else NA
    return mean, sd, rsd


def analyse(ds: Dataset) -> Summary:
    ds.normalise()
    return Summary([analyse_run(ds, i) for i in range(ds.n_runs)])
