"""Native LabDream file format (.ldd, JSON), legacy import and CSV export."""
from __future__ import annotations

import csv
import io
import json
import os

from .cpl import read_cpl
from .engine import analyse, mean_sd_rsd, NA, LOD
from .model import Dataset, GROUP_OFF, GROUP_STAGE, HEADING_LABELS

APP_NAME = "LabDream"
APP_VERSION = "LabDream Version 3.1"
NATIVE_EXT = ".ldd"


def load(path: str) -> Dataset:
    if path.lower().endswith(".cpl"):
        return read_cpl(path)
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    if d.get("format") != "LabDream":
        raise ValueError("Not a LabDream data file")
    ds = Dataset.from_dict(d)
    ds.file_name = os.path.basename(path)
    return ds


def save(ds: Dataset, path: str) -> None:
    ds.file_name = os.path.basename(path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(ds.to_dict(), f, ensure_ascii=False, indent=1)


# ----------------------------------------------------------------------
def fmt(v, prec=None):
    if isinstance(v, str):
        return v
    if v is None:
        return NA
    if prec is not None:
        return f"{v:.{prec}f}"
    return f"{v:.10g}"


def export_csv(ds: Dataset, path: str) -> None:
    """Export input data and all results as a CSV file."""
    s = analyse(ds)
    runs = s.runs
    n = len(runs)
    u = "mg" if ds.unit_mg else "ug"
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow([ds.dev.name])
    w.writerow([])
    w.writerow(["Calibration Flow Rate [L/min]", fmt(ds.cal_flow), ""])
    w.writerow(["Stage Titles", "Stage ECD"])
    for r, t in enumerate(ds.row_titles):
        if r < 3:
            if r == 2 and not ds.row_active(2):
                continue
            w.writerow([t])
        else:
            w.writerow([t, " " + fmt(ds.ecd[r - 3])])
    for lab, val in ds.info:
        if lab in HEADING_LABELS:
            w.writerow([lab])
        else:
            w.writerow([lab, " " + val if val else ""])
    w.writerow(["Other Information", ds.other_info])
    w.writerow([])

    head = [f"Run {i+1}" for i in range(n)]
    w.writerow(["Deposition Data"] + head + ["Mean/dose", "SD/dose", "%RSD/dose"])
    w.writerow(["Dose No :"] + [ds.runs[i].dose_no for i in range(n)] + ["", "", ""])

    def row(label, vals):
        num = [v for v in vals if isinstance(v, (int, float))]
        m, sd, rsd = mean_sd_rsd(num)
        if isinstance(m, float) and m == 0:
            rsd = NA
        w.writerow([label] + [fmt(v) for v in vals] + [fmt(m), fmt(sd), fmt(rsd)])

    for r, t in enumerate(ds.row_titles):
        if not ds.row_active(r):
            continue
        row(f"{t} [{u}]", [ds.runs[i].masses[r] for i in range(n)])
    row("Flow Rate [L/min]", [ds.runs[i].flow for i in range(n)])
    row(f"Doses to {ds.device} [{u}]", [ds.runs[i].doses for i in range(n)])
    row(f"Delivered Dose [{u}]", [ds.runs[i].delivered for i in range(n)])
    w.writerow([])
    if ds.fpd_by_stage:
        w.writerow(["Fine Particle Dose Spec :", f"{ds.row_titles[ds.fpd_stage_row]} to {ds.row_titles[-1]}"])
    else:
        w.writerow(["Fine Particle Dose Spec :", f"Less than or Equal to {ds.fpd_size:g} microns"])
    w.writerow(["Probit Range 4-6 :", fmt(ds.r2_limit)])
    w.writerow([])
    w.writerow(["RESULT SUMMARY"])
    w.writerow([""] + head + ["Mean/dose", "SD/dose", "%RSD/dose"])
    if ds.report_shot_weight:
        row("Shot Weight - Mean [mg]", [r.shot_weight_mean for r in runs])
        row("Shot Weight - Standard Deviation [mg]", [r.shot_weight_sd for r in runs])
        w.writerow([])
    row(f"Total Dose Per Shot  [{u}]", [r.total for r in runs])
    row(f"Calc Delivered Dose  [{u}]", [r.delivered_calc for r in runs])
    row(f"Fine Particle Dose  [{u}]", [r.fpd for r in runs])
    row("Fine Particle Fraction [%]", [r.fpf for r in runs])
    row("MMAD [um]", [r.mmad for r in runs])
    row("GSD", [r.gsd for r in runs])
    row("R2", [r.r2 for r in runs])
    row("Flow Rate [L/min]", [r.flow for r in runs])
    w.writerow([])
    for k, (lo, hi) in enumerate(((75, 125), (80, 120), (85, 115))):
        w.writerow([f"Total mass of active substance within {lo}-{hi}% of mean delivered dose"])
        w.writerow(["", "Run No", " Calculated [%]", " Comment"])
        for r in runs:
            _, _, pct, com = r.cu[k]
            w.writerow(["", r.run, "Error" if pct is None else f" {pct:.1f}%", com])
        w.writerow([])
    active = [g for g in range(5) if ds.groups[g].mode != GROUP_OFF]
    w.writerow([f"Particle dose results for {len(active)} groups"])
    w.writerow(["From", " To"] + head + ["Mean", "SD/dose", "%RSD/dose"])
    for g in active:
        gr = runs[0].groups[g]
        vals = [r.groups[g].dose for r in runs]
        num = [v for v in vals if isinstance(v, (int, float))]
        m, sd, rsd = mean_sd_rsd(num)
        w.writerow([" " + gr.label_from, " " + gr.label_to] + [fmt(v) for v in vals] + [fmt(m), fmt(sd), fmt(rsd)])
    w.writerow([])
    w.writerow(["Particle fraction group results"])
    w.writerow(["From", " To"] + head + ["Mean", "SD/dose", "%RSD/dose"])
    for g in active:
        gr = runs[0].groups[g]
        vals = [r.groups[g].fraction for r in runs]
        num = [v for v in vals if isinstance(v, (int, float))]
        m, sd, rsd = mean_sd_rsd(num)
        w.writerow([" " + gr.label_from, " " + gr.label_to] + [fmt(v) for v in vals] + [fmt(m), fmt(sd), fmt(rsd)])
    w.writerow([])
    w.writerow([APP_VERSION])
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        f.write(out.getvalue())
