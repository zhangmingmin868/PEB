"""Data model for one LabDream data file (one impactor, up to 12 runs)."""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field, asdict
from typing import List, Optional

from .devices import DEVICES, MAX_RUNS, DeviceDef

# (label, default value) pairs shown on "User Setup" screen 1 of 3
DEFAULT_INFO = [
    ("Date of Analysis:", ""),
    ("Analyst:", ""),
    ("Instrument Serial No.", ""),
    ("Device Details:", ""),
    ("Name", ""),
    ("Device ID Code", ""),
    ("Batch Number", ""),
    ("Sample Age", ""),
    ("Storage Conditions", ""),
    ("Formulation Details:", ""),
    ("Drug/Dose", ""),
    ("Component 1", ""),
    ("Component 2", ""),
    ("Component 3", ""),
    ("Component 4", ""),
    ("Component 5", ""),
]
HEADING_LABELS = {"Device Details:", "Formulation Details:"}

GROUP_OFF, GROUP_SIZE, GROUP_STAGE = "off", "size", "stage"


@dataclass
class Group:
    mode: str = GROUP_SIZE
    min_um: float = 0.0
    max_um: float = 0.0
    from_row: int = 1          # index into Dataset rows (0 = device)
    to_row: int = 1


@dataclass
class Run:
    dose_no: str = ""
    masses: List[float] = field(default_factory=list)   # one per row
    flow: float = 0.0
    doses: float = 1.0
    delivered: float = 0.0          # delivered dose from DDU testing
    shot_weight_mean: float = 0.0
    shot_weight_sd: float = 0.0


@dataclass
class Dataset:
    device: str = "CI"
    cal_flow: float = 28.3
    row_titles: List[str] = field(default_factory=list)
    ecd: List[float] = field(default_factory=list)       # one per stage row
    info: List[List[str]] = field(default_factory=lambda: [list(p) for p in DEFAULT_INFO])
    other_info: str = ""
    n_runs: int = 3
    unit_mg: bool = False
    show_presep: bool = True
    remove_stage6: bool = False
    remove_stage7: bool = False
    fpd_by_stage: bool = False
    fpd_stage_row: int = 6         # row index of "Stage X to Filter"
    fpd_size: float = 5.0
    r2_limit: float = 0.95
    groups: List[Group] = field(default_factory=list)
    report_shot_weight: bool = False
    runs: List[Run] = field(default_factory=list)
    file_name: str = ""
    # record keeping
    created_by: str = ""
    created_at: str = ""
    modified_by: str = ""
    modified_at: str = ""
    revision: int = 0

    # ------------------------------------------------------------------
    @property
    def dev(self) -> DeviceDef:
        return DEVICES[self.device]

    @property
    def unit(self) -> str:
        return "mg" if self.unit_mg else "µg"

    @property
    def n_rows(self) -> int:
        return len(self.row_titles)

    def stage_rows(self) -> List[int]:
        return list(range(3, self.n_rows))

    def row_active(self, r: int) -> bool:
        """Row is used for data entry / totals."""
        if r == 2 and not (self.dev.has_presep and self.show_presep):
            return False
        if self.device == "CI" and self.dev.supports_remove_stages:
            if self.remove_stage6 and self.row_titles_default(r) == "Stage 6":
                return False
            if self.remove_stage7 and self.row_titles_default(r) == "Stage 7":
                return False
        return True

    def row_titles_default(self, r: int) -> str:
        return self.dev.row_titles[r]

    def info_value(self, label: str) -> str:
        for k, v in self.info:
            if k == label:
                return v
        return ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["format"] = "LabDream"
        d["version"] = 1
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Dataset":
        d = dict(d)
        d.pop("format", None)
        d.pop("version", None)
        groups = [Group(**g) for g in d.pop("groups", [])]
        runs = [Run(**r) for r in d.pop("runs", [])]
        ds = cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
        ds.groups = groups
        ds.runs = runs
        ds.normalise()
        return ds

    def normalise(self) -> None:
        dev = self.dev
        if len(self.row_titles) != len(dev.row_titles):
            self.row_titles = list(dev.row_titles)
        if len(self.ecd) != dev.n_stages:
            self.ecd = list(dev.default_ecd)
        while len(self.groups) < 5:
            lo, hi = dev.default_group_ranges[len(self.groups)]
            self.groups.append(Group(GROUP_SIZE, lo, hi, 1, 1))
        self.groups = self.groups[:5]
        while len(self.runs) < MAX_RUNS:
            self.runs.append(Run(masses=[0.0] * self.n_rows, flow=self.cal_flow, doses=1.0))
        for r in self.runs:
            if len(r.masses) < self.n_rows:
                r.masses += [0.0] * (self.n_rows - len(r.masses))
            r.masses = r.masses[: self.n_rows]
        self.n_runs = max(1, min(MAX_RUNS, int(self.n_runs)))
        if len(self.info) != len(DEFAULT_INFO):
            base = [list(p) for p in DEFAULT_INFO]
            for i, p in enumerate(self.info[: len(base)]):
                base[i] = list(p)
            self.info = base


def new_dataset(device: str) -> Dataset:
    dev = DEVICES[device]
    ds = Dataset(device=device, cal_flow=dev.default_cal_flow,
                 row_titles=list(dev.row_titles), ecd=list(dev.default_ecd))
    ds.show_presep = dev.has_presep
    ds.fpd_stage_row = 6 if device == "CI" else 5
    ds.info[0][1] = _dt.date.today().strftime("%d-%b-%y")
    ds.normalise()
    return ds


# ----------------------------------------------------------------------
_TRACKED = ["device", "cal_flow", "other_info", "n_runs", "unit_mg", "show_presep", "remove_stage6",
            "remove_stage7", "fpd_by_stage", "fpd_stage_row", "fpd_size", "r2_limit", "report_shot_weight"]
_RUN_FIELDS = ["dose_no", "flow", "doses", "delivered", "shot_weight_mean", "shot_weight_sd"]


def diff_datasets(old: "Dataset", new: "Dataset") -> List[str]:
    """Human-readable list of changes between two versions of a data file."""
    out = []
    if old is None:
        return out

    def ch(label, a, b):
        if a != b:
            out.append(f"{label}: {a!r} -> {b!r}")

    for f in _TRACKED:
        ch(f, getattr(old, f), getattr(new, f))
    for i, (a, b) in enumerate(zip(old.row_titles, new.row_titles)):
        ch(f"Stage title [{i}]", a, b)
    for i, (a, b) in enumerate(zip(old.ecd, new.ecd)):
        if abs(a - b) > 1e-12:
            ch(f"ECD {new.row_titles[3 + i] if 3 + i < len(new.row_titles) else i}", round(a, 6), round(b, 6))
    for (la, va), (lb, vb) in zip(old.info, new.info):
        ch(f"Info '{lb}' label", la, lb)
        ch(f"Info '{lb}'", va, vb)
    for g, (a, b) in enumerate(zip(old.groups, new.groups)):
        if a != b:
            out.append(f"Group {g + 1}: {a} -> {b}")
    for j, (ra, rb) in enumerate(zip(old.runs, new.runs)):
        for f in _RUN_FIELDS:
            ch(f"Run {j + 1} {f}", getattr(ra, f), getattr(rb, f))
        for r, (ma, mb) in enumerate(zip(ra.masses, rb.masses)):
            title = new.row_titles[r] if r < len(new.row_titles) else str(r)
            ch(f"Run {j + 1} {title}", ma, mb)
    return out
