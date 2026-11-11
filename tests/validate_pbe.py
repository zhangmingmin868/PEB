"""Validation of the PBE module (IQ/OQ evidence).

1. FDA Budesonide guidance, section 5.B example (180 values, 3 batches x 10
   containers x 3 life stages, data already on log scale)  -> every published
   intermediate value (ED…E4, HD…H4, UD…U4, Eq, Uq, Hη, σR) for both criteria.
2. Customer Excel workbook "FDA体外一致性评价方法（PBE）.xlsx" (ln transform,
   θp = 2.089, m = 1) -> all cached cell values of sheet "PBE Calculation".
3. Inverse t / chi-square functions against scipy (if installed).
4. File integrity: checksum, tamper detection, signature binding.

Run:  python tests/validate_pbe.py        (exit code 0 = all passed)
"""
import csv
import math
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from labdream import pbe, stats  # noqa: E402

fails = 0
checks = 0


def check(label, got, exp, rel=1e-6, abs_=1e-12):
    global fails, checks
    checks += 1
    ok = (isinstance(got, str) and got == exp) or (
        not isinstance(got, str) and abs(got - exp) <= max(abs_, rel * abs(exp)))
    if not ok:
        fails += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<34} calc={got!s:<24} expected={exp}")


# ------------------------------------------------------------------ 1. FDA example
print("1. FDA Budesonide guidance example (reference-scaled / constant-scaled)")
rows = list(csv.reader(open(os.path.join(HERE, "data", "fda_budesonide_example.csv"), encoding="utf-8")))
R, T, m, names = pbe.parse_long_table(rows)
assert (len(R), len(R[0].containers), len(T), m) == (3, 10, 3, 3), "example layout"
st = pbe.PbeStudy(m=m, reference=R, test=T, ln_transform=False)   # published data are already ln values
res = pbe.compute(st)
# Published values (guidance pages 9-10) are printed with 5-9 significant digits
# and were computed from unrounded data, while the printed input data have 6
# decimals; the small within-container terms (E2, E4, H4) are most sensitive to
# that, hence 5e-5 relative tolerance on E/H and 2e-4 on U (= squared terms).
pub = {
    "D": (0.022094106, 0.113976896, 0.008442447),
    "1": (0.219742944, 0.359860715, 0.01963299),
    "2": (3.9108E-05, 5.43319E-05, 2.31765E-10),
}
rs = {"3": (-0.505515326, -0.344478125, 0.02593298), "4": (-0.000256672, -0.000194739, 3.83572E-09)}
cs = {"3": (-0.163644789, -0.111514028, 0.002717616), "4": (-8.30895E-05, -6.30405E-05, 4.0196E-10)}
for name, crit, extra in (("reference", res.reference_scaled, rs), ("constant", res.constant_scaled, cs)):
    for k, (e, h, u) in {**pub, **extra}.items():
        check(f"{name} E{k}", crit.E[k], e, 5e-5)
        check(f"{name} H{k}", crit.H[k], h, 5e-5)
        check(f"{name} U{k}", crit.U[k], u, 2e-4)
check("reference Eq", res.reference_scaled.eq, -0.26389584, 1e-7)
check("reference Uq", res.reference_scaled.uq, 0.054008421, 1e-6)
check("reference Hη", res.reference_scaled.h_eta, -0.031498721, 1e-5)
check("constant Eq", res.constant_scaled.eq, 0.057257267, 1e-6)
check("constant Uq", res.constant_scaled.uq, 0.030793054, 1e-6)
check("constant Hη", res.constant_scaled.h_eta, 0.232736764, 1e-6)
check("σR", res.ref.sigma, math.sqrt(0.163727878), 1e-6)
check("σR² ", res.ref.sigma ** 2, 0.163727878, 1e-6)
check("scaling", res.scaling, "reference")
check("conclusion", "Pass" if res.passed else "Fail", "Pass")

# ------------------------------------------------------------------ 2. Excel workbook
print("\n2. Customer Excel workbook (ln transform, θp = 2.089)")
xlsx = os.path.join(HERE, "data", "pbe_reference_workbook.xlsx")
try:
    import openpyxl
except ImportError:
    openpyxl = None
    print("  SKIP  openpyxl not installed")
if openpyxl is not None and os.path.exists(xlsx):
    wb = openpyxl.load_workbook(xlsx, data_only=True)
    od = wb[" Original Data "]
    calc = wb["PBE Calculation"]

    def read(col_batch, col_no, col_vals):
        batches = []
        for r in range(3, 33):
            b = od.cell(r, col_batch).value
            if b is not None or not batches:
                batches.append(pbe.Batch(str(b or ""), []))
            vals = [od.cell(r, c).value for c in col_vals]
            vals = [float(v) for v in vals if v is not None]
            batches[-1].containers.append(pbe.Container(str(od.cell(r, col_no).value), vals))
        return batches

    st2 = pbe.PbeStudy(m=1, theta_p=pbe.THETA_P_WORKBOOK, ln_transform=True,
                       reference=read(1, 2, [3]), test=read(6, 7, [8]))
    r2 = pbe.compute(st2)
    v = lambda a: calc[a].value  # noqa: E731
    pairs = [("X̄R (B35)", r2.ref.mean, "B35"), ("MSBR (C35)", r2.ref.msb, "C35"),
             ("MSWR (D35)", r2.ref.msw, "D35"), ("σR (E35)", r2.ref.sigma, "E35"),
             ("X̄T (B37)", r2.test.mean, "B37"), ("MSBT (C37)", r2.test.msb, "C37"),
             ("MSWT (D37)", r2.test.msw, "D37"), ("σT (E37)", r2.test.sigma, "E37"),
             ("Δ (B40)", r2.delta, "B40")]
    for crit, row0 in ((r2.reference_scaled, 41), (r2.constant_scaled, 50)):
        for i, k in enumerate(["D", "1", "2", "3", "4"]):
            pairs += [(f"{crit.name} E{k} (B{row0+i})", crit.E[k], f"B{row0+i}"),
                      (f"{crit.name} H{k} (D{row0+i})", crit.H[k], f"D{row0+i}"),
                      (f"{crit.name} U{k} (F{row0+i})", crit.U[k], f"F{row0+i}")]
        pairs += [(f"{crit.name} Eq (B{row0+5})", crit.eq, f"B{row0+5}"),
                  (f"{crit.name} Uq (F{row0+5})", crit.uq, f"F{row0+5}"),
                  (f"{crit.name} Hη (H{row0+5})", crit.h_eta, f"H{row0+5}")]
    for label, got, cell in pairs:
        check(label, got, v(cell), 1e-9, 1e-15)
    check("reference applies (I41)", "Yes" if r2.reference_scaled.applies else "Not", v("I41"))
    check("constant applies (I50)", "Yes" if r2.constant_scaled.applies else "Not", v("I50"))
    check("conclusion (J50)", "Pass" if r2.passed else "Fail", v("J50"))

# ------------------------------------------------------------------ 3. distributions
print("\n3. Inverse t / chi-square vs scipy")
try:
    from scipy import stats as sps
except ImportError:
    sps = None
    print("  SKIP  scipy not installed")
if sps is not None:
    worst = 0.0
    for df in (1, 2, 3, 5, 9, 10, 19, 29, 58, 59, 89, 100, 179, 500, 2000, 10000):
        for p in (0.0001, 0.001, 0.01, 0.025, 0.05, 0.1, 0.5, 0.9, 0.95, 0.975, 0.99, 0.999, 0.9999):
            for mine, ref in ((stats.chi2_ppf(p, df), sps.chi2.ppf(p, df)),
                              (stats.t_ppf(p, df), sps.t.ppf(p, df))):
                e = abs(mine - ref) / abs(ref) if abs(ref) > 1e-12 else abs(mine - ref)
                worst = max(worst, e)
    check("max relative error (416 points)", worst, 0.0, 0, 1e-10)

# ------------------------------------------------------------------ 4. integrity
print("\n4. File integrity and electronic signature binding")
with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, "x.pbe")
    st.signatures.append(pbe.Signature("ana", "Analyst", "performed", pbe.utc_now(), st.content_hash()))
    pbe.save(st, p)
    back = pbe.load(p)
    check("round-trip identical result", pbe.compute(back).reference_scaled.h_eta, res.reference_scaled.h_eta, 0, 0)
    check("signature valid after reload", len(back.valid_signatures()), 1, 0, 0)
    back.test[0].containers[0].values[0] += 0.001
    check("signature invalid after change", len(back.valid_signatures()), 0, 0, 0)
    txt = open(p, encoding="utf-8").read().replace("5.957211", "5.957212", 1)
    open(p, "w", encoding="utf-8").write(txt)
    try:
        pbe.load(p)
        tam = "not detected"
    except pbe.PbeError:
        tam = "detected"
    check("external tampering", tam, "detected")

print(f"\n{checks - fails}/{checks} checks passed")
sys.exit(1 if fails else 0)
