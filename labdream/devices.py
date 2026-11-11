"""Impactor / impinger device definitions (Ph. Eur. 2.9.18 / USP <601>).

Each device has a fixed list of deposition rows:
    row 0  : device / actuator (mouthpiece adapter)
    row 1  : throat (induction port)
    row 2  : pre-separator (only CI and NGI)
    row 3+ : impaction stages, the last one being the filter / MOC

``ecd`` gives the calibrated cut-off diameter (µm) of every stage row at
``cal_flow`` (L/min).  The last stage (filter / MOC) has ECD 0.

``first_size_stage`` is the index (within the stage rows) of the first stage
that takes part in cumulative-mass calculations; stages before it act as a
pre-separator (MSLI stage 1, MMI stage 1).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional

CI, MSLI, MMI, NGI = "CI", "MSLI", "MMI", "NGI"

MAX_RUNS = 12


@dataclass
class DeviceDef:
    code: str
    name: str
    row_titles: List[str]
    has_presep: bool
    default_cal_flow: float
    default_ecd: List[float]          # one value per stage row
    first_size_stage: int             # index into stage rows
    scaling: str                      # "sqrt" or "ngi"
    ngi_exponents: Optional[List[float]] = None
    default_group_ranges: List[tuple] = field(default_factory=list)
    supports_remove_stages: bool = False
    image: str = ""

    @property
    def stage_titles(self) -> List[str]:
        return self.row_titles[3:]

    @property
    def n_stages(self) -> int:
        return len(self.row_titles) - 3


DEVICES = {
    CI: DeviceDef(
        code=CI,
        name="Cascade Impactor (CI)",
        row_titles=["Actuator", "Throat", "Presep.", "Stage 0", "Stage 1", "Stage 2",
                    "Stage 3", "Stage 4", "Stage 5", "Stage 6", "Stage 7", "Filter"],
        has_presep=True,
        default_cal_flow=28.3,
        default_ecd=[9.0, 5.8, 4.7, 3.3, 2.1, 1.1, 0.7, 0.43, 0.0],
        first_size_stage=0,
        scaling="sqrt",
        default_group_ranges=[(0, 1), (1, 2), (2, 3), (3, 4), (4, 5)],
        supports_remove_stages=True,
        image="ci",
    ),
    MSLI: DeviceDef(
        code=MSLI,
        name="Multi-Stage Liquid Impinger (MSLI)",
        row_titles=["Device", "Throat", "Presep.", "Stage 1", "Stage 2", "Stage 3",
                    "Stage 4", "Stage 5/F"],
        has_presep=False,
        default_cal_flow=60.0,
        default_ecd=[13.0, 6.8, 3.1, 1.7, 0.0],
        first_size_stage=1,
        scaling="sqrt",
        default_group_ranges=[(0, 1.7), (1.7, 2), (2, 3), (3, 4), (4, 5)],
        image="msli",
    ),
    MMI: DeviceDef(
        code=MMI,
        name="Marple-Miller Impactor (MMI)",
        row_titles=["Device", "Throat", "Presep.", "Stage 1", "Stage 2", "Stage 3",
                    "Stage 4", "Stage 5", "Filter"],
        has_presep=False,
        default_cal_flow=60.0,
        default_ecd=[10.0, 5.0, 2.5, 1.25, 0.625, 0.0],
        first_size_stage=1,
        scaling="sqrt",
        default_group_ranges=[(0, 1), (1, 2), (2, 3), (3, 4), (4, 5)],
        image="mmi",
    ),
    NGI: DeviceDef(
        code=NGI,
        name="Next Generation Impactor (NGI)",
        row_titles=["Device", "Throat", "Presep.", "Stage 1", "Stage 2", "Stage 3",
                    "Stage 4", "Stage 5", "Stage 6", "Stage 7", "MOC"],
        has_presep=True,
        default_cal_flow=60.0,
        default_ecd=[8.06, 4.46, 2.82, 1.66, 0.94, 0.55, 0.34, 0.0],
        first_size_stage=0,
        scaling="ngi",
        # Ph. Eur. 2.9.18 / USP <601>: D50,Q = D50,Qn * (Qn/Q)^x
        ngi_exponents=[0.54, 0.52, 0.50, 0.47, 0.53, 0.60, 0.67, 0.0],
        default_group_ranges=[(0, 1), (1, 2), (2, 3), (3, 4), (4, 5)],
        image="ngi",
    ),
}

DEVICE_ORDER = [CI, MSLI, MMI, NGI]


def scaled_ecd(dev: DeviceDef, cal_flow: float, ecd: List[float], flow: float) -> List[float]:
    """Cut-off diameters at the actual sampling flow ``flow``."""
    out = []
    if flow <= 0 or cal_flow <= 0:
        return list(ecd)
    for i, d in enumerate(ecd):
        if d <= 0:
            out.append(0.0)
            continue
        if dev.scaling == "ngi" and dev.ngi_exponents:
            x = dev.ngi_exponents[i] if i < len(dev.ngi_exponents) else 0.5
            out.append(d * (cal_flow / flow) ** x)
        else:
            out.append(d * math.sqrt(cal_flow / flow))
    return out
