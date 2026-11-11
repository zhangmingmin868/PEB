"""Population Bioequivalence (PBE) for in-vitro tests.

Implements FDA "Draft Guidance on Budesonide (Inhalation Suspension)",
section 5 "Recommendation related to the PBE statistical analysis procedure",
steps 1–5, with the same conventions as the validated Excel workbook
"FDA体外一致性评价方法（PBE）.xlsx":

* every measured value X is ln-transformed (optional – off if the data are
  already on log scale, as in the guidance example);
* m life stages (B / M / E …) per container, n containers per batch, l batches;
* θp = ((ln 1.11)² + 0.01) / 0.1² = 2.0891 (exact, reproduces the guidance example;
  the Excel workbook rounds it to 2.089 – selectable), σT0 = 0.1, α = 0.05;
* reference-scaled criterion if σR > σT0, otherwise constant-scaled;
* PBE passes if the 95 % upper confidence bound Hη ≤ 0.
"""
from __future__ import annotations

import copy
import datetime as _dt
import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

from .stats import chi2_ppf, t_ppf

THETA_P = (math.log(1.11) ** 2 + 0.01) / 0.1 ** 2      # 2.08910… (guidance)
THETA_P_WORKBOOK = 2.089                               # rounded value used by the Excel workbook
SIGMA_T0 = 0.1
ALPHA = 0.05
MAX_STAGES = 6
PBE_EXT = ".pbe"
FORMAT = "LabDream-PBE"
FORMAT_VERSION = 1


class PbeError(ValueError):
    """Data are not complete / not balanced. args[0] is an English message."""


# ====================================================================== model
@dataclass
class Container:
    no: str = ""
    values: List[Optional[float]] = field(default_factory=list)   # one per life stage


@dataclass
class Batch:
    batch_no: str = ""
    containers: List[Container] = field(default_factory=list)


@dataclass
class Signature:
    username: str
    full_name: str
    meaning: str           # "performed" | "reviewed" | "approved"
    timestamp: str         # UTC
    record_hash: str       # SHA-256 of the signed content
    comment: str = ""


@dataclass
class PbeStudy:
    # --- study information
    title: str = ""
    product: str = ""
    test_product: str = ""
    reference_product: str = ""
    parameter: str = ""              # e.g. "Delivered dose", "ISM", "Spray pattern area"
    unit: str = ""
    study_no: str = ""
    method: str = ""
    notes: str = ""
    # --- design / constants
    m: int = 1
    stage_names: List[str] = field(default_factory=lambda: ["B", "M", "E", "4", "5", "6"])
    ln_transform: bool = True
    theta_p: float = THETA_P
    sigma_t0: float = SIGMA_T0
    alpha: float = ALPHA
    reference: List[Batch] = field(default_factory=list)
    test: List[Batch] = field(default_factory=list)
    # --- record metadata (21 CFR 11.10(e))
    created_by: str = ""
    created_at: str = ""
    modified_by: str = ""
    modified_at: str = ""
    revision: int = 0
    signatures: List[Signature] = field(default_factory=list)
    file_name: str = ""

    # ---------------------------------------------------------- serialise
    def content_dict(self) -> dict:
        """Everything that defines the result (signed / checksummed part)."""
        d = asdict(self)
        for k in ("created_by", "created_at", "modified_by", "modified_at", "revision",
                  "signatures", "file_name"):
            d.pop(k)
        return d

    def content_hash(self) -> str:
        s = json.dumps(self.content_dict(), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(s.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("file_name")
        return {"format": FORMAT, "format_version": FORMAT_VERSION, "study": d,
                "checksum": self._checksum(d)}

    @staticmethod
    def _checksum(d: dict) -> str:
        s = json.dumps(d, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(("LabDream-PBE\x1f" + s).encode("utf-8")).hexdigest()

    @classmethod
    def from_dict(cls, raw: dict, verify=True) -> "PbeStudy":
        if raw.get("format") != FORMAT:
            raise PbeError("Not a LabDream PBE data file")
        d = raw["study"]
        if verify and raw.get("checksum") != cls._checksum(d):
            raise PbeError("File checksum does not match: the file was altered outside LabDream")
        d = dict(d)
        d["reference"] = [Batch(b["batch_no"], [Container(c["no"], list(c["values"])) for c in b["containers"]])
                          for b in d.get("reference", [])]
        d["test"] = [Batch(b["batch_no"], [Container(c["no"], list(c["values"])) for c in b["containers"]])
                     for b in d.get("test", [])]
        d["signatures"] = [Signature(**s) for s in d.get("signatures", [])]
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})

    # ---------------------------------------------------------- signatures
    def valid_signatures(self) -> List[Signature]:
        h = self.content_hash()
        return [s for s in self.signatures if s.record_hash == h]

    def stale_signatures(self) -> List[Signature]:
        h = self.content_hash()
        return [s for s in self.signatures if s.record_hash != h]


def new_study(l_ref=3, n_ref=10, l_test=3, n_test=10, m=1) -> PbeStudy:
    st = PbeStudy(m=m)
    st.reference = make_batches(l_ref, n_ref, m, first_batch=1)
    st.test = make_batches(l_test, n_test, m, first_batch=1)
    return st


def make_batches(l: int, n: int, m: int, first_batch=1, old: Optional[List[Batch]] = None) -> List[Batch]:
    """Build l batches x n containers x m stages, keeping any existing values."""
    out = []
    for j in range(l):
        ob = old[j] if old and j < len(old) else None
        b = Batch(ob.batch_no if ob else "", [])
        for i in range(n):
            oc = ob.containers[i] if ob and i < len(ob.containers) else None
            vals = list(oc.values[:m]) if oc else []
            vals += [None] * (m - len(vals))
            b.containers.append(Container(oc.no if oc else str(i + 1), vals))
        out.append(b)
    return out


def diff_studies(old: PbeStudy, new: PbeStudy) -> List[str]:
    """Human-readable list of changed values: 'field: old -> new'."""
    out = []
    a, b = old.content_dict(), new.content_dict()
    for k in a:
        if k in ("reference", "test"):
            continue
        if a[k] != b.get(k):
            out.append(f"{k}: {a[k]!r} -> {b.get(k)!r}")
    for prod in ("reference", "test"):
        ob, nb = getattr(old, prod), getattr(new, prod)
        if len(ob) != len(nb):
            out.append(f"{prod}: batches {len(ob)} -> {len(nb)}")
        for j in range(min(len(ob), len(nb))):
            if ob[j].batch_no != nb[j].batch_no:
                out.append(f"{prod} batch {j+1} no: {ob[j].batch_no!r} -> {nb[j].batch_no!r}")
            oc, nc = ob[j].containers, nb[j].containers
            if len(oc) != len(nc):
                out.append(f"{prod} batch {j+1}: containers {len(oc)} -> {len(nc)}")
            for i in range(min(len(oc), len(nc))):
                if oc[i].no != nc[i].no:
                    out.append(f"{prod} batch {j+1} container {i+1} no: {oc[i].no!r} -> {nc[i].no!r}")
                for s in range(max(len(oc[i].values), len(nc[i].values))):
                    va = oc[i].values[s] if s < len(oc[i].values) else None
                    vb = nc[i].values[s] if s < len(nc[i].values) else None
                    if va != vb:
                        out.append(f"{prod} batch {ob[j].batch_no or j+1} container {oc[i].no or i+1} "
                                   f"stage {s+1}: {va} -> {vb}")
    return out


# ====================================================================== engine
@dataclass
class ProductStats:
    l: int
    n: int
    m: int
    mean: float          # X̄k.. on analysis scale
    geo_mean: float      # exp(mean) if ln-transformed, else arithmetic mean
    msb: float
    msw: float
    sigma: float
    container_means: List[List[float]]


@dataclass
class Criterion:
    name: str            # "reference" | "constant"
    applies: bool
    E: Dict[str, float]
    H: Dict[str, float]
    U: Dict[str, float]
    eq: float            # linearized point estimate
    uq: float
    h_eta: float         # 95 % upper confidence bound
    passed: bool


@dataclass
class PbeResult:
    ref: ProductStats
    test: ProductStats
    delta: float
    t_value: float
    df_t: int
    chi2: Dict[str, float]
    gmr: float
    sigma_ratio: float
    reference_scaled: Criterion
    constant_scaled: Criterion
    scaling: str          # "reference" | "constant"
    passed: bool
    theta_p: float
    sigma_t0: float
    alpha: float
    ln_transform: bool

    @property
    def applied(self) -> Criterion:
        return self.reference_scaled if self.scaling == "reference" else self.constant_scaled


def _product(batches: List[Batch], m: int, ln: bool, label: str) -> ProductStats:
    if not batches:
        raise PbeError(f"{label}: no batches")
    n = len(batches[0].containers)
    if n < 1:
        raise PbeError(f"{label}: no containers")
    xs: List[List[List[float]]] = []
    for j, b in enumerate(batches):
        if len(b.containers) != n:
            raise PbeError(f"{label}: every batch must have the same number of containers")
        bx = []
        for i, c in enumerate(b.containers):
            row = []
            for s in range(m):
                v = c.values[s] if s < len(c.values) else None
                if v is None or (isinstance(v, float) and math.isnan(v)):
                    raise PbeError(f"{label}: missing value (batch {b.batch_no or j+1}, "
                                   f"container {c.no or i+1}, stage {s+1})")
                v = float(v)
                if ln:
                    if v <= 0:
                        raise PbeError(f"{label}: value must be > 0 for ln transformation (batch "
                                       f"{b.batch_no or j+1}, container {c.no or i+1}, stage {s+1})")
                    v = math.log(v)
                row.append(v)
            bx.append(row)
        xs.append(bx)
    l = len(batches)
    N = l * n
    if N < 2:
        raise PbeError(f"{label}: at least 2 containers are needed")
    cmeans = [[sum(r) / m for r in bx] for bx in xs]
    grand = sum(sum(r) for bx in xs for r in bx) / (N * m)
    msb = m * sum((x - grand) ** 2 for row in cmeans for x in row) / (N - 1)
    if m > 1:
        msw = sum((v - cmeans[j][i]) ** 2 for j, bx in enumerate(xs) for i, r in enumerate(bx) for v in r) \
            / (N * (m - 1))
    else:
        msw = 0.0
    sigma = math.sqrt(msb / m + (m - 1) / m * msw)
    return ProductStats(l, n, m, grand, math.exp(grand) if ln else grand, msb, msw, sigma, cmeans)


def compute(st: PbeStudy) -> PbeResult:
    m = int(st.m)
    if not 1 <= m <= MAX_STAGES:
        raise PbeError("Number of life stages must be between 1 and 6")
    R = _product(st.reference, m, st.ln_transform, "Reference")
    T = _product(st.test, m, st.ln_transform, "Test")
    a, tp, s0 = float(st.alpha), float(st.theta_p), float(st.sigma_t0)
    if not 0 < a < 0.5:
        raise PbeError("α must be between 0 and 0.5")
    NT, NR = T.l * T.n, R.l * R.n
    delta = T.mean - R.mean
    df_t = NT + NR - 2
    if df_t < 1:
        raise PbeError("Not enough containers")
    tval = t_ppf(1 - a, df_t)
    chi = {
        "T_B": chi2_ppf(a, NT - 1),
        "R_B": chi2_ppf(1 - a, NR - 1),
    }
    if m > 1:
        chi["T_W"] = chi2_ppf(a, NT * (m - 1))
        chi["R_W"] = chi2_ppf(1 - a, NR * (m - 1))

    ED = delta ** 2
    HD = (abs(delta) + tval * math.sqrt(T.msb / (NT * m) + R.msb / (NR * m))) ** 2
    E1 = T.msb / m
    H1 = (NT - 1) * E1 / chi["T_B"]
    E2 = (m - 1) / m * T.msw
    H2 = NT * (m - 1) * E2 / chi["T_W"] if m > 1 else 0.0

    def crit(name, k3, offset):
        E3 = -k3 * R.msb / m
        E4 = -k3 * (m - 1) / m * R.msw + 0.0      # avoid -0.0 when m = 1
        H3 = (NR - 1) * E3 / chi["R_B"]
        H4 = NR * (m - 1) * E4 / chi["R_W"] if m > 1 else 0.0
        E = {"D": ED, "1": E1, "2": E2, "3": E3, "4": E4}
        H = {"D": HD, "1": H1, "2": H2, "3": H3, "4": H4}
        U = {k: (H[k] - E[k]) ** 2 for k in E}
        eq = sum(E.values()) - offset
        uq = sum(U.values())
        h = eq + math.sqrt(uq)
        applies = (R.sigma > s0) if name == "reference" else (R.sigma <= s0)
        return Criterion(name, applies, E, H, U, eq, uq, h, h <= 0)

    rs = crit("reference", 1 + tp, 0.0)
    cs = crit("constant", 1.0, tp * s0 ** 2)
    scaling = "reference" if R.sigma > s0 else "constant"
    applied = rs if scaling == "reference" else cs
    gmr = (T.geo_mean / R.geo_mean) if R.geo_mean else float("nan")
    return PbeResult(R, T, delta, tval, df_t, chi, gmr, T.sigma / R.sigma if R.sigma else float("inf"),
                     rs, cs, scaling, applied.passed, tp, s0, a, st.ln_transform)


def utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


# ====================================================================== files
def load(path: str) -> PbeStudy:
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    st = PbeStudy.from_dict(raw)
    import os
    st.file_name = os.path.basename(path)
    return st


def save(st: PbeStudy, path: str) -> None:
    import os
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st.to_dict(), f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    st.file_name = os.path.basename(path)


def clone(st: PbeStudy) -> PbeStudy:
    return copy.deepcopy(st)


# ====================================================================== import
def parse_long_table(rows: List[List[str]], m_hint: Optional[int] = None):
    """Parse 'Batch, Container, Stage, Product, Value' rows (guidance Table 1 /
    SAS-transport layout).  Returns (reference_batches, test_batches, m, stage_names)."""
    data: Dict[str, Dict[str, Dict[str, Dict[str, float]]]] = {"R": {}, "T": {}}
    stage_order: List[str] = []
    order: Dict[str, List[str]] = {"R": [], "T": []}
    corder: Dict[tuple, List[str]] = {}
    for r in rows:
        cells = [c.strip() for c in r]
        if len(cells) < 5 or not cells[4]:
            continue
        try:
            val = float(cells[4].replace(",", "."))
        except ValueError:
            continue                                     # header line
        prod = cells[3].upper()
        p = "R" if prod.startswith("R") else "T" if prod.startswith("T") else None
        if p is None:
            raise PbeError(f"Unknown product '{cells[3]}' (use REF / TEST)")
        b, c, s = cells[0], cells[1], cells[2]
        if s not in stage_order:
            stage_order.append(s)
        if b not in data[p]:
            data[p][b] = {}
            order[p].append(b)
            corder[(p, b)] = []
        if c not in data[p][b]:
            data[p][b][c] = {}
            corder[(p, b)].append(c)
        data[p][b][c][s] = val
    m = len(stage_order)
    if m == 0:
        raise PbeError("No data rows found")
    if m > MAX_STAGES:
        raise PbeError("Number of life stages must be between 1 and 6")

    def build(p):
        out = []
        for b in order[p]:
            cons = [Container(c, [data[p][b][c].get(s) for s in stage_order]) for c in corder[(p, b)]]
            out.append(Batch(b, cons))
        return out

    return build("R"), build("T"), m, stage_order


def read_csv_rows(path: str) -> List[List[str]]:
    import csv
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        return [r for r in csv.reader(f, dialect)]


def import_workbook(path: str):
    """Read the 'Original Data' sheet of the customer's PBE Excel workbook:
    Reference in columns A-E (Batch No., No., Life Stage 1-3), Test in F-J,
    data from row 3.  Returns (reference, test, m)."""
    try:
        import openpyxl
    except ImportError as e:                                   # pragma: no cover
        raise PbeError("Excel import needs the openpyxl package") from e
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    ws = None
    for w in wb.worksheets:
        if w.title.strip().lower() == "original data":
            ws = w
            break
    if ws is None:
        ws = wb.worksheets[0]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    # locate the two 'Batch No.' header cells
    hdr_row, cols = None, []
    for ri, r in enumerate(rows[:20]):
        cs = [ci for ci, v in enumerate(r) if isinstance(v, str) and v.strip().lower().startswith("batch")]
        if len(cs) >= 2:
            hdr_row, cols = ri, cs[:2]
            break
    if hdr_row is None:
        raise PbeError("Could not find the 'Batch No.' header row in the workbook")
    width = cols[1] - cols[0]
    n_stage_cols = width - 2

    def block(c0):
        batches: List[Batch] = []
        m_used = 0
        for r in rows[hdr_row + 1:]:
            cells = list(r[c0:c0 + width]) + [None] * width
            bno, cno, vals = cells[0], cells[1], cells[2:2 + n_stage_cols]
            if cno is None and all(v is None for v in vals):
                continue
            if bno is not None or not batches:
                batches.append(Batch("" if bno is None else str(bno).strip(), []))
            fv = []
            for v in vals:
                fv.append(float(v) if isinstance(v, (int, float)) else None)
            while fv and fv[-1] is None:
                fv.pop()
            m_used = max(m_used, len(fv))
            batches[-1].containers.append(Container("" if cno is None else str(cno).strip(), fv))
        return batches, m_used

    ref, m1 = block(cols[0])
    test, m2 = block(cols[1])
    m = max(m1, m2, 1)
    for b in ref + test:
        for c in b.containers:
            c.values = (c.values + [None] * m)[:m]
    return ref, test, m


def export_csv(st: PbeStudy, path: str, app_version: str = "") -> None:
    import csv
    res = None
    err = ""
    try:
        res = compute(st)
    except PbeError as e:
        err = str(e)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Population Bioequivalence (PBE) – FDA in-vitro PBE procedure"])
        for k in ("title", "study_no", "product", "test_product", "reference_product", "parameter", "unit",
                  "method", "notes"):
            w.writerow([k, getattr(st, k)])
        w.writerow(["m (life stages)", st.m, "stages", ";".join(st.stage_names[:st.m])])
        w.writerow(["ln transform", "yes" if st.ln_transform else "no"])
        w.writerow(["theta_p", repr(st.theta_p), "sigma_T0", repr(st.sigma_t0), "alpha", repr(st.alpha)])
        w.writerow(["file", st.file_name, "revision", st.revision, "content SHA-256", st.content_hash()])
        w.writerow([])
        if res is None:
            w.writerow(["ERROR", err])
        else:
            w.writerow(["", "mean", "geometric mean", "MSB", "MSW", "sigma", "l", "n", "m"])
            for lab, p in (("Reference", res.ref), ("Test", res.test)):
                w.writerow([lab, repr(p.mean), repr(p.geo_mean), repr(p.msb), repr(p.msw), repr(p.sigma), p.l, p.n, p.m])
            w.writerow(["Delta", repr(res.delta), "GMR", repr(res.gmr), "sigmaT/sigmaR", repr(res.sigma_ratio)])
            w.writerow(["t", repr(res.t_value), "df", res.df_t] + [x for k, v in res.chi2.items() for x in ("chi2 " + k, repr(v))])
            w.writerow([])
            for c in (res.reference_scaled, res.constant_scaled):
                w.writerow([f"{c.name}-scaled criterion", "applies" if c.applies else "not applicable"])
                w.writerow(["q", "Eq", "Hq", "Uq"])
                for k in ("D", "1", "2", "3", "4"):
                    w.writerow([k, repr(c.E[k]), repr(c.H[k]), repr(c.U[k])])
                w.writerow(["sum", repr(c.eq), "H_eta", repr(c.h_eta), "Uq", repr(c.uq),
                            "result", ("Pass" if c.passed else "Fail") if c.applies else "--"])
                w.writerow([])
            w.writerow(["CONCLUSION", f"{res.scaling}-scaled", "PASS" if res.passed else "FAIL"])
        w.writerow([])
        w.writerow(["Product", "Batch No.", "Container No."] + [f"Stage {s}" for s in st.stage_names[:st.m]])
        for lab, batches in (("Reference", st.reference), ("Test", st.test)):
            for b in batches:
                for c in b.containers:
                    w.writerow([lab, b.batch_no, c.no] + ["" if v is None else repr(v) for v in c.values[:st.m]])
        w.writerow([])
        w.writerow(["Signatures"])
        h = st.content_hash()
        for s in st.signatures:
            w.writerow([s.meaning, s.full_name, s.username, s.timestamp,
                        "valid" if s.record_hash == h else "INVALID (data changed after signing)"])
        if app_version:
            w.writerow([app_version])
