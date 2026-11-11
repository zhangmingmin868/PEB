"""Printed / PDF report of a PBE study (A4 portrait).

Page 1  study information, design, constants, summary (guidance Table 2),
        intermediate values of both criteria, conclusion, signature manifest
        (21 CFR 11.50) and record identification (file, revision, SHA-256).
Page 2+ individual data (guidance Table 1): original values, ln values and
        container means for every batch / container / life stage.
"""
from __future__ import annotations

import datetime as _dt
import math

from PySide6.QtCore import QMarginsF, Qt
from PySide6.QtGui import QColor, QPageLayout, QPageSize, QPainter

from . import pbe
from .fileio import APP_VERSION
from .i18n import tr, trf
from .reports import Page

L, C, R = Qt.AlignLeft | Qt.AlignVCenter, Qt.AlignCenter, Qt.AlignRight | Qt.AlignVCenter
ROW = 4.3


def g(v, digits=6):
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return "NA"
    if v == 0:
        return "0"
    a = abs(v)
    if 1e-4 <= a < 1e6:
        return f"{v:.{digits}f}".rstrip("0").rstrip(".") if digits > 0 else f"{v:.0f}"
    return f"{v:.{digits - 1}E}"


def sig_meaning(m: str) -> str:
    return tr({"performed": "Performed by", "reviewed": "Reviewed by", "approved": "Approved by"}.get(m, m))


class PbeReport:
    def __init__(self, st: pbe.PbeStudy, printed_by="", printed_at=None):
        self.st = st
        self.printed_by = printed_by
        self.printed_at = printed_at or _dt.datetime.now()
        try:
            self.res = pbe.compute(st)
            self.error = ""
        except pbe.PbeError as e:
            self.res = None
            self.error = tr(str(e))
        self._rows = self._data_rows()
        self.rows_first = 52
        self.rows_next = 58
        n = len(self._rows)
        extra = 0 if n <= self.rows_first else math.ceil((n - self.rows_first) / self.rows_next)
        self.page_count = 2 + extra

    # ------------------------------------------------------------------
    def _data_rows(self):
        out = []
        st = self.st
        for label, batches in ((tr("Reference"), st.reference), (tr("Test"), st.test)):
            for j, b in enumerate(batches):
                for i, c in enumerate(b.containers):
                    vals = [c.values[s] if s < len(c.values) else None for s in range(st.m)]
                    lnv = []
                    for v in vals:
                        lnv.append(math.log(v) if (st.ln_transform and isinstance(v, (int, float)) and v > 0)
                                   else (v if not st.ln_transform else None))
                    mean = sum(lnv) / len(lnv) if lnv and all(x is not None for x in lnv) else None
                    out.append([label, b.batch_no or str(j + 1), c.no or str(i + 1)] + vals + lnv + [mean])
        return out

    # ------------------------------------------------------------------
    def render(self, printer):
        printer.setPageLayout(QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait,
                                          QMarginsF(12, 10, 12, 10), QPageLayout.Millimeter))
        p = QPainter()
        if not p.begin(printer):
            return
        p.setRenderHint(QPainter.Antialiasing)
        try:
            for i in range(self.page_count):
                if i > 0:
                    printer.newPage()
                pg = Page(p, printer, False)
                if i == 0:
                    self._page_summary(pg)
                else:
                    self._page_data(pg, i - 1)
                self._footer(pg, i + 1)
        finally:
            p.end()

    def _footer(self, pg, n):
        y = pg.H - 9
        pg.line(0, y, pg.W, y, 0.15)
        st = self.st
        ident = f"{st.file_name or tr('(new file)')}  ·  {tr('Revision')} {st.revision}  ·  SHA-256 {st.content_hash()[:16]}…"
        pg.text(0, y + 0.5, pg.W, 4, ident, L, size=7)
        pg.text(0, y + 4, 70, 4, APP_VERSION + " – " + tr("PBE module"), L, size=7)
        pg.text(0, y + 4, pg.W, 4, trf("Page {n} of {m}", n=n, m=self.page_count), C, size=7)
        pg.text(pg.W - 90, y + 4, 90, 4,
                (trf("Printed by {u}", u=self.printed_by) + "   " if self.printed_by else "")
                + self.printed_at.strftime("%Y-%m-%d %H:%M:%S"), R, size=7)

    def _title(self, pg, text):
        pg.text(0, 0, pg.W, 8, text, C, size=13, bold=True)
        pg.line(0, 9, pg.W, 9, 0.3)
        return 11

    def _table(self, pg, x, y, widths, rows, header=True, size=7.5, aligns=None, shade_first_col=False):
        tot = sum(widths)
        for r, row in enumerate(rows):
            if header and r == 0:
                pg.p.fillRect(pg.rect(x, y, tot, ROW), QColor("#e6ecf5"))
            elif shade_first_col:
                pg.p.fillRect(pg.rect(x, y, widths[0], ROW), QColor("#f3f3f3"))
            cx = x
            for k, cell in enumerate(row):
                al = aligns[k] if aligns and not (header and r == 0) else (C if header and r == 0 else L)
                pg.text(cx + 0.8, y, widths[k] - 1.6, ROW, str(cell), al, size=size, bold=(header and r == 0))
                cx += widths[k]
            y += ROW
        # grid
        top = y - ROW * len(rows)
        for r in range(len(rows) + 1):
            pg.line(x, top + r * ROW, x + tot, top + r * ROW, 0.1)
        cx = x
        for w in widths + [0]:
            pg.line(cx, top, cx, y, 0.1)
            cx += w
        return y

    # ------------------------------------------------------------------
    def _page_summary(self, pg):
        st, res = self.st, self.res
        y = self._title(pg, tr("Population Bioequivalence (PBE) Report"))
        W = pg.W
        info = [(tr("Study title"), st.title), (tr("Study No."), st.study_no),
                (tr("Product"), st.product), (tr("Parameter"), f"{st.parameter} {('[' + st.unit + ']') if st.unit else ''}"),
                (tr("Test product"), st.test_product), (tr("Reference product"), st.reference_product),
                (tr("Method"), st.method), (tr("Created"), f"{st.created_by}  {st.created_at}"),
                (tr("Notes"), st.notes), (tr("Last modified"), f"{st.modified_by}  {st.modified_at}")]
        half = W / 2
        for k, (lab, val) in enumerate(info):
            cx = 0 if k % 2 == 0 else half
            cy = y + (k // 2) * 4.2
            pg.text(cx, cy, 32, 4.2, lab, L, size=7.5, bold=True)
            pg.text(cx + 32, cy, half - 34, 4.2, val or "", L, size=7.5)
        y += 5 * 4.2 + 2

        pg.text(0, y, W, 5, tr("Study design and constants"), L, size=9, bold=True)
        y += 5.5
        rT = res.test if res else None
        rR = res.ref if res else None
        lR = len(st.reference); lT = len(st.test)
        nR = len(st.reference[0].containers) if st.reference else 0
        nT = len(st.test[0].containers) if st.test else 0
        rows = [[tr("Product"), tr("Batches (l)"), tr("Containers / batch (n)"), tr("Life stages (m)"),
                 tr("Stages"), tr("Transformation")],
                [tr("Reference"), lR, nR, st.m, ", ".join(st.stage_names[:st.m]), "ln" if st.ln_transform else tr("none")],
                [tr("Test"), lT, nT, st.m, ", ".join(st.stage_names[:st.m]), "ln" if st.ln_transform else tr("none")]]
        y = self._table(pg, 0, y, [30, 25, 37, 27, 37, W - 156], rows, aligns=[L, C, C, C, C, C])
        y += 1.5
        pg.text(0, y, W, 4.2, f"θp = {g(st.theta_p, 6)}     σT0 = {g(st.sigma_t0)}     α = {g(st.alpha)}"
                f"     ({tr('one-sided 95% upper confidence bound')})", L, size=7.5)
        y += 6

        if res is None:
            pg.text(0, y, W, 10, tr("PBE cannot be calculated:") + " " + self.error, L, size=10, bold=True)
            self._signatures(pg, y + 14)
            return

        pg.text(0, y, W, 5, tr("Summary of PBE results"), L, size=9, bold=True)
        y += 5.5
        gm = tr("Geometric mean") if st.ln_transform else tr("Mean")
        rows = [[tr("Variable"), f"{gm} {tr('Test')}", f"{gm} {tr('Reference')}",
                 tr("Geometric Mean Ratio") if st.ln_transform else tr("Mean Ratio"), "σT", "σR", "σT/σR"],
                [st.parameter or "—", g(rT.geo_mean, 5), g(rR.geo_mean, 5), g(res.gmr, 5),
                 g(rT.sigma, 6), g(rR.sigma, 6), g(res.sigma_ratio, 5)]]
        y = self._table(pg, 0, y, [W - 150, 26, 26, 28, 23, 23, 24], rows, aligns=[L, R, R, R, R, R, R])
        y += 2
        rows = [[tr("Criterion"), tr("Applicable"), tr("Scaled linearized point estimate"),
                 tr("95% upper confidence bound"), tr("Pass or Fail PBE")]]
        for c in (res.reference_scaled, res.constant_scaled):
            rows.append([tr("Reference-scaled") if c.name == "reference" else tr("Constant-scaled"),
                         tr("Yes") if c.applies else tr("Not applicable"), g(c.eq, 6), g(c.h_eta, 6),
                         (tr("Pass") if c.passed else tr("Fail")) if c.applies else "--"])
        y = self._table(pg, 0, y, [34, 26, (W - 90) / 2, (W - 90) / 2, 30], rows, aligns=[L, C, R, R, C])
        y += 3

        # intermediate values
        pg.text(0, y, W, 5, tr("Intermediate values"), L, size=9, bold=True)
        y += 5.5
        rows = [["", "X̄ (" + ("ln" if st.ln_transform else tr("analysis scale")) + ")", "MSB", "MSW", "σ", "σ²"],
                [tr("Reference"), g(rR.mean, 7), g(rR.msb, 6), g(rR.msw, 6), g(rR.sigma, 6), g(rR.sigma ** 2, 6)],
                [tr("Test"), g(rT.mean, 7), g(rT.msb, 6), g(rT.msw, 6), g(rT.sigma, 6), g(rT.sigma ** 2, 6)]]
        y = self._table(pg, 0, y, [30] + [(W - 30) / 5] * 5, rows, aligns=[L, R, R, R, R, R])
        y += 1.2
        chi = res.chi2
        line = (f"Δ = X̄T − X̄R = {g(res.delta, 7)}     t(1−α, {res.df_t}) = {g(res.t_value, 6)}     "
                f"χ²(α, {rT.l * rT.n - 1}) = {g(chi['T_B'], 6)}     χ²(1−α, {rR.l * rR.n - 1}) = {g(chi['R_B'], 6)}")
        if "T_W" in chi:
            line += (f"     χ²(α, {rT.l * rT.n * (st.m - 1)}) = {g(chi['T_W'], 6)}"
                     f"     χ²(1−α, {rR.l * rR.n * (st.m - 1)}) = {g(chi['R_W'], 6)}")
        pg.font(6.8)
        pg.p.drawText(pg.rect(0, y, W, 8), Qt.AlignLeft | Qt.TextWordWrap, line)
        y += 8.5
        cw = (W - 4) / 2
        for k, c in enumerate((res.reference_scaled, res.constant_scaled)):
            x = k * (cw + 4)
            sfx = "s" if c.name == "reference" else "c"
            pg.text(x, y, cw, 4.5, (tr("Reference-scaled criterion") if c.name == "reference"
                                    else tr("Constant-scaled criterion")) + ("  ✓" if c.applies else ""),
                    L, size=8, bold=True)
            rows = [["q", "Eq", "Hq", "Uq = (Hq − Eq)²"]]
            for key, lab in (("D", "D"), ("1", "1"), ("2", "2"), ("3", "3" + sfx), ("4", "4" + sfx)):
                rows.append([lab, g(c.E[key], 6), g(c.H[key], 6), g(c.U[key], 6)])
            rows.append(["Σ", g(c.eq, 6), "Hη = " + g(c.h_eta, 6), g(c.uq, 6)])
            self._table(pg, x, y + 5, [10, (cw - 10) / 3, (cw - 10) / 3, (cw - 10) / 3], rows,
                        size=7, aligns=[C, R, R, R], shade_first_col=True)
        y += 5 + 7 * ROW + 1.5
        if st.m == 1:
            pg.text(0, y, W, 4, tr("m = 1: E2 / E4 and their H and U terms are ignored (guidance)."), L, size=6.8)
        y += 4.5

        # conclusion
        ok = res.passed
        box = pg.rect(0, y, W, 15)
        pg.p.fillRect(box, QColor("#e3f4e1" if ok else "#fbe3e3"))
        pg.p.drawRect(box)
        crit = tr("reference-scaled") if res.scaling == "reference" else tr("constant-scaled")
        cmp_ = ">" if res.scaling == "reference" else "≤"
        txt1 = trf("σR = {s} {cmp} σT0 = {s0}: the {crit} criterion applies.", s=g(res.ref.sigma, 6), cmp=cmp_,
                   s0=g(st.sigma_t0), crit=crit)
        txt2 = trf("Hη = {h} {op} 0  →  {verdict}", h=g(res.applied.h_eta, 6), op="≤" if ok else ">",
                   verdict=tr("PBE PASSED – the test product is bioequivalent to the reference product.") if ok
                   else tr("PBE FAILED – bioequivalence is not demonstrated."))
        pg.text(3, y + 1, W - 6, 6, txt1, L, size=8.5)
        pg.text(3, y + 7.5, W - 6, 6.5, txt2, L, size=9.5, bold=True)
        y += 18
        self._signatures(pg, y)

    def _signatures(self, pg, y):
        st = self.st
        W = pg.W
        pg.text(0, y, W, 5, tr("Electronic signatures (21 CFR Part 11)"), L, size=9, bold=True)
        y += 5.5
        rows = [[tr("Meaning"), tr("Printed name"), tr("User ID"), tr("Date / time (UTC)"), tr("Status")]]
        h = st.content_hash()
        for s in st.signatures:
            rows.append([sig_meaning(s.meaning), s.full_name, s.username, s.timestamp,
                         tr("valid") if s.record_hash == h else tr("INVALID – data changed after signing")])
        if len(rows) == 1:
            rows.append([tr("(not signed)"), "", "", "", ""])
        self._table(pg, 0, y, [30, 42, 26, 40, W - 138], rows, aligns=[L, L, L, L, L])

    # ------------------------------------------------------------------
    def _page_data(self, pg, k):
        st = self.st
        y = self._title(pg, tr("Individual data") + f" – {st.parameter or ''}")
        m = st.m
        names = st.stage_names[:m]
        if k == 0:
            start, cnt = 0, self.rows_first
            pg.text(0, y, pg.W, 4.5, tr("Original data") + ("   |   ln " + tr("values") if st.ln_transform else ""),
                    L, size=8, bold=True)
            y += 5
        else:
            start, cnt = self.rows_first + (k - 1) * self.rows_next, self.rows_next
        rows = self._rows[start:start + cnt]
        head = [tr("Product"), tr("Batch No."), tr("No.")] + names
        if st.ln_transform:
            head += [f"ln {n}" for n in names]
        head += [tr("Mean") + (" (ln)" if st.ln_transform else "")]
        fixed = [20, 22, 14]
        rest = pg.W - sum(fixed)
        nv = len(head) - 3
        widths = fixed + [rest / nv] * nv
        body = []
        for r in rows:
            vals = r[3:3 + m]
            lnv = r[3 + m:3 + 2 * m]
            row = r[:3] + [g(v, 6) for v in vals]
            if st.ln_transform:
                row += [g(v, 6) for v in lnv]
            row += [g(r[-1], 6)]
            body.append(row)
        if not body:
            body = [[""] * len(head)]
        self._table(pg, 0, y, widths, [head] + body, size=7, aligns=[L, L, L] + [R] * nv)
