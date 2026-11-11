"""Compare LabDream results with the reference CSV outputs shipped with the
legacy validation package (CPL input + CSV output pairs).

usage:  python tests/validate_against_reference.py <folder-with-CPL-and-CSV> [-v]
"""
import csv
import glob
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from labdream.cpl import read_cpl           # noqa: E402
from labdream.engine import analyse, NA, LOD  # noqa: E402

ROWS = {
    "Total Dose Per Shot": lambda r: r.total,
    "Calc Delivered Dose": lambda r: r.delivered_calc,
    "Fine Particle Dose": lambda r: r.fpd,
    "Fine Particle Fraction": lambda r: r.fpf,
    "MMAD": lambda r: r.mmad,
    "GSD": lambda r: r.gsd,
    "R2": lambda r: r.r2,
}


def parse_ref(path):
    rows = list(csv.reader(open(path, encoding="latin-1")))
    out, groups = {}, []
    section = None
    for row in rows:
        if not row:
            continue
        key = row[0].strip()
        if key == "RESULT SUMMARY":
            section = "res"
            continue
        if key.startswith("Particle dose results"):
            section = "gdose"
            continue
        if key.startswith("Particle fraction group"):
            section = "gfrac"
            continue
        if section == "res":
            for name in ROWS:
                if key.startswith(name) and name not in out:
                    out[name] = row[1:]
        elif section in ("gdose", "gfrac") and len(row) > 3 and "m" in row[1]:
            groups.append((section, row[0].strip(), row[1].strip(), row[2:]))
    return out, groups


def cmp(ref, val, tol):
    ref = ref.strip()
    if ref in ("NA", "LOD", "Error"):
        return ref == val, ref
    try:
        rv = float(ref)
    except ValueError:
        return True, ref
    if not isinstance(val, (int, float)):
        return False, rv
    return abs(rv - val) <= tol * max(1.0, abs(rv)), rv


def main():
    folder = sys.argv[1]
    verbose = "-v" in sys.argv
    total = bad = 0
    for cpl in sorted(glob.glob(os.path.join(folder, "**", "*.CPL"), recursive=True)):
        csvp = cpl[:-4] + ".CSV"
        if not os.path.exists(csvp):
            continue
        ds = read_cpl(cpl)
        summ = analyse(ds)
        ref, groups = parse_ref(csvp)
        fails = []
        for name, get in ROWS.items():
            if name not in ref:
                continue
            tol = 2e-4 if name in ("MMAD", "GSD", "R2") else 2e-3
            for j, r in enumerate(summ.runs):
                if j >= len(ref[name]):
                    break
                v = get(r)
                ok, rv = cmp(ref[name][j], v, tol)
                total += 1
                if not ok:
                    bad += 1
                    fails.append(f"  run {j+1:2d} {name:24s} ref={rv!s:>14} got={v if isinstance(v,str) else round(v,6)!s:>14}")
        gi = {"gdose": 0, "gfrac": 0}
        for sec, lo, hi, vals in groups:
            g = gi[sec]
            gi[sec] += 1
            for j, r in enumerate(summ.runs):
                gr = r.groups[g]
                v = gr.dose if sec == "gdose" else gr.fraction
                ok, rv = cmp(vals[j], v, 2e-3)
                total += 1
                if not ok:
                    bad += 1
                    fails.append(f"  run {j+1:2d} group {sec} {lo}-{hi:10s} ref={rv!s:>14} got={v if isinstance(v,str) else round(v,6)!s:>14}")
        print(f"{os.path.basename(cpl):28s} mismatches: {len(fails)}")
        if verbose:
            print("\n".join(fails))
    print(f"\nTOTAL compared {total}, mismatches {bad}")


if __name__ == "__main__":
    main()
