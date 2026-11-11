"""Import of legacy ``.CPL`` impactor data files.

Layout (little endian), as found in the legacy data files:

    0x00  int32  device code (100 CI, 101 MSLI, 102 MMI, 103 NGI)
    0x04  int32  (device sub-type)
    0x08  int32  number of stage rows
    0x0C  int32  number of runs
    0x10  int32  (reserved)
    0x14  double[728]
          [0]        calibration flow rate (L/min)
          [1..9]     stage ECDs (µm)
          [10..21]   flow rate per run
          [22..165]  deposition masses, 12 rows x 12 runs
          [166..177] doses per run
          [178..189] delivered dose per run
          [190]      FPD stage number ("Stage n to Filter")
          [191]      FPD size limit (µm)
          [192..203] shot weight mean per run (mg)
          [204..215] shot weight standard deviation per run (mg)
          [216]      byte flags: FPD-by-stage, unit mg, shot weight, presep shown
          [218]      R² limit
          [219..228] five size groups (min, max)
    0x16D4 text block (CR/LF separated): device name, row titles,
           label/value pairs, dose numbers
"""
from __future__ import annotations

import os
import struct

from .devices import CI, MSLI, MMI, NGI, DEVICES, MAX_RUNS
from .model import Dataset, Group, Run, GROUP_SIZE, GROUP_OFF, DEFAULT_INFO

CODES = {100: CI, 101: MSLI, 102: MMI, 103: NGI}
TEXT_OFFSET = 20 + 728 * 8


class CplError(Exception):
    pass


def read_cpl(path: str) -> Dataset:
    data = open(path, "rb").read()
    if len(data) < TEXT_OFFSET:
        raise CplError("File too short – not a valid impactor data file")
    code, _sub, n_stage, n_runs, _res = struct.unpack("<5i", data[:20])
    if code not in CODES:
        raise CplError(f"Unknown device code {code}")
    dev = DEVICES[CODES[code]]

    def dbl(i):
        v = struct.unpack("<d", data[20 + 8 * i: 28 + 8 * i])[0]
        if v != v or abs(v) > 1e300 or (v != 0 and abs(v) < 1e-300):
            return 0.0
        return v

    ds = Dataset(device=dev.code)
    ds.cal_flow = dbl(0)
    ns = dev.n_stages
    ds.ecd = [dbl(1 + k) for k in range(ns)]
    ds.ecd[-1] = 0.0
    ds.n_runs = max(1, min(MAX_RUNS, n_runs))
    ds.row_titles = list(dev.row_titles)
    runs = []
    for j in range(MAX_RUNS):
        masses = [dbl(22 + r * 12 + j) for r in range(len(dev.row_titles))]
        runs.append(Run(masses=masses, flow=dbl(10 + j), doses=dbl(166 + j) or 1.0,
                        delivered=dbl(178 + j), shot_weight_mean=dbl(192 + j),
                        shot_weight_sd=dbl(204 + j)))
    ds.runs = runs

    stage_no = int(round(dbl(190)))
    first = 0 if dev.code in (CI,) else 1      # CI stages start at "Stage 0"
    ds.fpd_stage_row = min(max(3 + stage_no - first, 3), len(dev.row_titles) - 1)
    ds.fpd_size = dbl(191) or 5.0
    flags = data[20 + 8 * 216: 20 + 8 * 216 + 8]
    ds.fpd_by_stage = bool(flags[0])
    ds.unit_mg = bool(flags[1])
    ds.report_shot_weight = bool(flags[4])
    ds.show_presep = dev.has_presep and bool(flags[3])
    r2 = dbl(218)
    ds.r2_limit = r2 if 0 < r2 <= 1 else 0.95
    def raw(off):
        return struct.unpack("<d", data[off: off + 8])[0]

    # some file versions store the group table 4 bytes earlier
    shift = 0
    v = raw(20 + 8 * 220)
    if v != 0 and abs(v) < 1e-300:
        shift = -4

    def gval(i):
        x = raw(20 + 8 * i + shift)
        return 0.0 if (x != x or abs(x) > 1e6 or (x != 0 and abs(x) < 1e-300)) else x

    groups = []
    for g in range(5):
        lo, hi = gval(219 + 2 * g), gval(220 + 2 * g)
        if hi > lo >= 0 and hi < 1000:
            groups.append(Group(GROUP_SIZE, lo, hi, 1, 1))
        else:
            groups.append(Group(GROUP_OFF, 0.0, 0.0, 1, 1))
    ds.groups = groups

    # ---- text block ----------------------------------------------------
    text = data[TEXT_OFFSET:].decode("latin-1")
    lines = text.split("\r\n")
    pos = 1                                   # line 0: device name
    titles = lines[pos: pos + 12]                  # always 12 title slots
    if len(titles) >= len(dev.row_titles):
        ds.row_titles = [t if t.strip() else d for t, d in zip(titles, dev.row_titles)]
    pos += 12
    info = []
    for _ in DEFAULT_INFO:
        lab = lines[pos] if pos < len(lines) else ""
        val = lines[pos + 1] if pos + 1 < len(lines) else ""
        info.append([lab, val.strip() if val.strip() == "" else val])
        pos += 2
    ds.info = info
    # remaining: other information + dose numbers (one per run)
    rest = lines[pos:]
    dose_lines = rest[:MAX_RUNS]
    for j in range(min(MAX_RUNS, len(dose_lines))):
        ds.runs[j].dose_no = dose_lines[j].strip()
    ds.other_info = rest[MAX_RUNS].strip() if len(rest) > MAX_RUNS else ""
    ds.file_name = os.path.basename(path)
    ds.normalise()
    return ds
