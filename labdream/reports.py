"""Printed reports: EP method, USP method, graphical, tabular and group results."""
from __future__ import annotations

import datetime as _dt

from PySide6.QtCore import QMarginsF, QPointF, QRectF, Qt
from PySide6.QtGui import QFont, QFontMetricsF, QPageLayout, QPageSize, QPainter, QPen

from . import charts
from .engine import analyse, mean_sd_rsd, NA, LOD
from .fileio import APP_VERSION
from .model import GROUP_OFF, HEADING_LABELS
from .i18n import tr, trf

EP, USP, GRAPHICAL, TABULAR, GROUPS = "ep", "usp", "graphical", "tabular", "groups"
MEAN = "Mean"


def f5(v):
    if isinstance(v, str):
        return v
    if v is None:
        return NA
    return f"{v:.5f}"


def short_name(ds):
    n = tr(ds.dev.name)
    return n.split(" (")[0].split("（")[0]


class Page:
    """Helper that converts millimetres to device pixels."""

    def __init__(self, painter: QPainter, device, landscape: bool):
        self.p = painter
        self.dev = device
        self.dpi = device.logicalDpiX()
        pr = device.pageLayout().paintRectPixels(device.resolution())
        self.w = pr.width()
        self.h = pr.height()
        painter.setViewport(0, 0, self.w, self.h)
        painter.setWindow(0, 0, self.w, self.h)
        self.landscape = landscape

    def mm(self, v):
        return v * self.dpi / 25.4

    def font(self, size, bold=False):
        f = QFont("Arial")
        f.setPointSizeF(size)
        f.setBold(bold)
        self.p.setFont(f)
        return QFontMetricsF(f, self.dev)

    def text(self, x, y, w, h, s, align=Qt.AlignLeft | Qt.AlignVCenter, size=8, bold=False):
        self.font(size, bold)
        self.p.drawText(QRectF(self.mm(x), self.mm(y), self.mm(w), self.mm(h)), align, s)

    def line(self, x1, y1, x2, y2, width=0.2):
        self.p.setPen(QPen(Qt.black, self.mm(width)))
        self.p.drawLine(QPointF(self.mm(x1), self.mm(y1)), QPointF(self.mm(x2), self.mm(y2)))

    def rect(self, x, y, w, h):
        return QRectF(self.mm(x), self.mm(y), self.mm(w), self.mm(h))

    @property
    def W(self):
        return self.w * 25.4 / self.dpi

    @property
    def H(self):
        return self.h * 25.4 / self.dpi


class ReportRenderer:
    def __init__(self, ds, selections, printed_at=None, printed_by=""):
        """selections: list of (kind, first_run, last_run) ; run index 1-based or MEAN."""
        self.ds = ds
        self.summary = analyse(ds)
        self.sel = selections
        self.printed_at = printed_at or _dt.datetime.now()
        self.printed_by = printed_by
        self._pages = self._plan()

    # ------------------------------------------------------------------
    def _run_list(self, a, b):
        n = self.ds.n_runs
        lo = 1 if a == MEAN else int(a)
        if b == MEAN:
            return list(range(lo, n + 1)) + [MEAN]
        hi = int(b)
        return list(range(lo, min(hi, n) + 1))

    def _plan(self):
        pages = []
        for kind, a, b in self.sel:
            if kind in (EP, USP):
                for r in self._run_list(a, b):
                    pages.append((kind, r, False))
            elif kind == GRAPHICAL:
                runs = list(range(1, self.ds.n_runs + 1))
                for i in range(0, len(runs), 3):
                    pages.append((kind, runs[i:i + 3], True))
            elif kind == TABULAR:
                pages.append((kind, None, True))
            elif kind == GROUPS:
                pages.append((kind, None, True))
        return pages

    @property
    def page_count(self):
        return len(self._pages)

    # ------------------------------------------------------------------
    def render(self, printer):
        """Render all pages onto a QPrinter / QPdfWriter."""
        if not self._pages:
            return
        first_land = self._pages[0][2]
        printer.setPageLayout(QPageLayout(QPageSize(QPageSize.A4),
                                          QPageLayout.Landscape if first_land else QPageLayout.Portrait,
                                          QMarginsF(10, 10, 10, 10), QPageLayout.Millimeter))
        p = QPainter()
        if not p.begin(printer):
            return
        p.setRenderHint(QPainter.Antialiasing)
        try:
            for i, (kind, arg, land) in enumerate(self._pages):
                if i > 0:
                    printer.setPageOrientation(QPageLayout.Landscape if land else QPageLayout.Portrait)
                    printer.newPage()
                pg = Page(p, printer, land)
                getattr(self, "_page_" + kind)(pg, arg)
                self._footer(pg, i + 1)
        finally:
            p.end()

    # ------------------------------------------------------------------
    def _footer(self, pg: Page, n):
        y = pg.H - 6
        pg.text(0, y, 80, 5, APP_VERSION, size=8)
        pg.text(0, y, pg.W, 5, trf("Page {n} of {m}", n=n, m=self.page_count), Qt.AlignHCenter | Qt.AlignVCenter, size=8)
        pg.text(pg.W - 90, y, 90, 5, (trf("Printed by {u}", u=self.printed_by) + "   " if self.printed_by else "") + self.printed_at.strftime("%Y-%m-%d %H:%M:%S"),
                Qt.AlignRight | Qt.AlignVCenter, size=8)

    def _header(self, pg: Page, title, y=0.0):
        ds = self.ds
        pg.text(0, y, pg.W, 9, title, Qt.AlignCenter, size=14, bold=True)
        y += 11
        pg.line(0, y, pg.W, y, 0.15)
        y += 1.5
        info = ds.info
        left = info[:9]
        right = info[9:]
        lh = 3.6
        cw = pg.W / 4
        for i, (lab, val) in enumerate(left[:8]):
            pg.text(4, y + i * lh, cw, lh, tr(lab), size=8, bold=True)
            if lab not in HEADING_LABELS:
                pg.text(4 + cw, y + i * lh, cw, lh, val, size=8)
        rlist = [left[8]] + right
        for i, (lab, val) in enumerate(rlist[:8]):
            pg.text(4 + 2 * cw, y + i * lh, cw, lh, tr(lab), size=8, bold=True)
            if lab not in HEADING_LABELS:
                pg.text(4 + 3 * cw, y + i * lh, cw - 4, lh, val, size=8)
        y += 8 * lh + 1
        pg.line(0, y, pg.W, y, 0.15)
        return y + 1

    # ------------------------------------------------------------------
    def _mean_result(self):
        """Pseudo result holding the mean of per-dose values of all runs."""
        runs = self.summary.runs
        base = runs[0]
        import copy
        r = copy.copy(base)
        n = len(runs)
        r.run = MEAN
        r.masses_per_dose = [sum(x.masses_per_dose[k] for x in runs) / n for k in range(len(base.masses_per_dose))]

        def mean(attr):
            vals = [getattr(x, attr) for x in runs if isinstance(getattr(x, attr), (int, float))]
            return sum(vals) / len(vals) if vals else NA
        for a in ("total", "delivered_calc", "delivered_entered", "fpd", "fpf", "mmad", "gsd", "flow",
                  "shot_weight_mean", "shot_weight_sd", "ct"):
            setattr(r, a, mean(a))
        r.doses = mean("doses")
        r.r2 = mean("r2")
        r.slope, r.intercept, r.n_reg = mean("slope"), mean("intercept"), mean("n_reg")
        cum = 0.0
        tbl = []
        for (row, cut, _m, _c, _p) in base.cum_table:
            mm = r.masses_per_dose[row]
            cum += mm
            tbl.append((row, cut, mm, cum, 0.0))
        tot = cum or 1.0
        r.cum_table = [(a, b, c, d, 100.0 * d / tot) for a, b, c, d, _ in tbl]
        pts = []
        for (row, cut, _m, c, pc) in r.cum_table[:-1]:
            if cut:
                pts.append((cut, pc))
        r.points = sorted(pts)
        cu = []
        for k, (lo, hi) in enumerate(((75, 125), (80, 120), (85, 115))):
            vals = [x.cu[k][2] for x in runs if x.cu[k][2] is not None]
            if vals:
                pct = sum(vals) / len(vals)
                ok = lo <= round(pct, 1) <= hi
                cu.append((lo, hi, pct, "Result within specification." if ok else "Result outside specification."))
            else:
                cu.append((lo, hi, None, "Content Uniformity result not entered"))
        r.cu = cu
        return r

    def _result(self, run):
        if run == MEAN:
            return self._mean_result()
        return self.summary.runs[run - 1]

    def _run_info(self, pg, res, y):
        ds = self.ds
        pg.text(0, y, 100, 4, f"{tr('Other Info')} : {ds.other_info}", size=8)
        y += 4
        run_lab = tr("Mean") if res.run == MEAN else str(res.run)
        pg.text(0, y, 50, 4, tr("Run Number ="), size=8)
        pg.text(55, y, 30, 4, run_lab, size=8)
        pg.text(100, y, 60, 4, tr("Sampling Flow rate (l/min) ="), size=8)
        pg.text(160, y, 30, 4, f5(res.flow), Qt.AlignHCenter | Qt.AlignVCenter, size=8)
        y += 4
        pg.text(0, y, 50, 4, tr("Number of discharges ="), size=8)
        pg.text(55, y, 30, 4, f"{res.doses:g}" if isinstance(res.doses, (int, float)) else "", size=8)
        if ds.report_shot_weight:
            pg.text(100, y, 60, 4, tr("Shot Weight, mean +/- sd [mg] ="), size=8)
            pg.text(160, y, 40, 4, f"{f5(res.shot_weight_mean)}+/-{f5(res.shot_weight_sd)}",
                    Qt.AlignHCenter | Qt.AlignVCenter, size=8)
        y += 5
        pg.line(0, y, pg.W, y, 0.15)
        return y + 1

    def _cu_lines(self, pg, res, y, usp=False):
        u = self.ds.unit
        pg.text(0, y, pg.W, 4, trf("(1) Total mass of active ingredient, less device deposition per discharge [{u}] = {v}", u=u, v=f5(res.delivered_calc)), size=8, bold=False)
        y += 3.8
        de = res.delivered_entered
        pg.text(0, y, pg.W, 4, trf("(2) Mean delivered dose determined during testing for uniformity of delivered dose [{u}] = {v}", u=u, v=f5(de)), size=8)
        y += 3.8
        for k, (lo, hi, pct, com) in enumerate(res.cu):
            s = trf("({k}) Total mass of active substance within {lo}-{hi}% of mean delivered dose : ", k=k + 3, lo=lo, hi=hi)
            s += (tr("Error") + " - " + tr(com)) if pct is None else f"{pct:.1f}% - {tr(com)}"
            pg.text(0, y, pg.W, 4, s, size=8)
            y += 3.8
        return y + 2

    def _fpd_lines(self, pg, res, y, usp=False):
        ds = self.ds
        u = ds.unit
        if ds.fpd_by_stage:
            spec = trf("{a} to {b}", a=tr(ds.row_titles[ds.fpd_stage_row]), b=tr(ds.row_titles[-1]))
        else:
            spec = trf("Less than or Equal to {d} µm", d=f"{ds.fpd_size:.5f}")
        lines = [(f"{spec} [{u}] =", f5(res.fpd))]
        if usp:
            lines.append((f"{tr('Fine Particle Fraction')}, {spec} [%] =", f5(res.fpf)))
        lines += [("MMAD [µm] =", f5(res.mmad)), ("GSD =", f5(res.gsd))]
        for lab, val in lines:
            pg.text(0, y, 120, 4, lab, size=8.5)
            pg.text(125, y, 40, 4, val, size=8.5)
            y += 4
        return y + 2

    def _charts_and_regression(self, pg, res, y):
        h = 62
        charts.draw_probit(pg.p, pg.rect(0, y, pg.W * 0.47, h), res, fs=7.5)
        charts.draw_deposition(pg.p, self.ds, res, pg.rect(pg.W * 0.52, y, pg.W * 0.48, h), fs=7.5)
        y += h + 4
        pg.text(0, y, 80, 4, tr("Log-Probit Graph Regression:"), size=8.5, bold=True)
        y += 4
        n = res.n_reg if isinstance(res.n_reg, (int, float)) else 0
        vals = [(tr("Intercept") + " =", f5(res.intercept)), (tr("Slope") + " =", f5(res.slope)),
                ("R^2 =", f5(res.r2)), ("n =", f"{n:g}" if isinstance(n, (int, float)) else n)]
        for lab, v in vals:
            pg.text(0, y, 60, 4, lab, size=8.5)
            pg.text(65, y, 40, 4, v, size=8.5)
            y += 4
        y += 3
        pg.text(0, y, 120, 4, f"{tr('File Name')} : {self.ds.file_name}", size=8.5)
        y += 8
        pg.text(0, y, 60, 4, tr("Data Input by:"), size=8.5)
        pg.text(80, y, 40, 4, tr("Date:"), size=8.5)
        y += 8
        pg.text(0, y, 60, 4, tr("Data Checked by:"), size=8.5)
        pg.text(80, y, 40, 4, tr("Date:"), size=8.5)

    # ------------------------------------------------------------------
    def _page_ep(self, pg: Page, run):
        ds = self.ds
        res = self._result(run)
        y = self._header(pg, trf("Results and Analysis (EP Method) for {d}", d=short_name(ds)))
        y = self._run_info(pg, res, y)
        u = ds.unit
        cols = [0, pg.W * 0.25, pg.W * 0.5, pg.W * 0.75]
        heads = [tr("Cut-off\nDiameter\n[µm]"), tr("Mass of active ingredient\ndeposited per discharge") + f"\n[{u}]",
                 tr("Cumulative mass of active\ningredient deposited per\ndischarge") + f" [{u}]",
                 tr("Cumulative fraction of\nactive ingredient deposited\nper discharge [%]")]
        for c, hd in zip(cols, heads):
            pg.text(c, y, pg.W / 4, 11, hd, Qt.AlignCenter, size=8, bold=True)
        y += 12
        pg.line(pg.W * 0.08, y, pg.W * 0.92, y, 0.15)
        y += 1
        for (row, cut, m, cum, pc) in res.cum_table:
            vals = [f5(cut) if cut else "---", f5(m), f5(cum), f5(pc)]
            for c, v in zip(cols, vals):
                pg.text(c, y, pg.W / 4, 3.6, v, Qt.AlignCenter, size=8)
            y += 3.6
        y += 1
        pg.line(0, y, pg.W, y, 0.15)
        y += 2
        y = self._cu_lines(pg, res, y)
        y = self._fpd_lines(pg, res, y)
        self._charts_and_regression(pg, res, y)

    def _page_usp(self, pg: Page, run):
        ds = self.ds
        res = self._result(run)
        y = self._header(pg, trf("Results and Analysis (USP Method) for {d}", d=short_name(ds)))
        y = self._run_info(pg, res, y)
        u = ds.unit
        cols = [0, pg.W * 0.2, pg.W * 0.4, pg.W * 0.6, pg.W * 0.8]
        heads = [tr("Stage"), tr("Mass A") + f"\n\n[{u}]", tr("Mass B") + f"\n\n[{u}]", tr("Cum. % of\nmass less than\nstated diameter"), "<D50\n\n[µm]"]
        for c, hd in zip(cols, heads):
            pg.text(c, y, pg.W / 5, 11, hd, Qt.AlignCenter, size=8, bold=True)
        y += 12
        pg.line(pg.W * 0.05, y, pg.W * 0.95, y, 0.15)
        y += 1
        size_rows = set()
        for (row, cut, m, cum, pc) in res.cum_table:
            size_rows.add(row)
            vals = [tr(ds.row_titles[row]), f5(m), f5(m), f5(pc), f5(cut) if cut else "---"]
            for c, v in zip(cols, vals):
                pg.text(c, y, pg.W / 5, 3.6, v, Qt.AlignCenter, size=8)
            y += 3.6
        sum_a = sum(m for (_r, _c, m, _cu, _p) in res.cum_table)
        sum_b = sum_a
        extra = [r for r in range(ds.n_rows - 1, 0, -1) if r not in size_rows and ds.row_active(r)]
        for r in extra:
            m = res.masses_per_dose[r]
            name = "M.A./I.P." if r == 1 else tr(ds.row_titles[r])
            pg.text(cols[0], y, pg.W / 5, 3.6, name, Qt.AlignCenter, size=8)
            pg.text(cols[1], y, pg.W / 5, 3.6, f5(m), Qt.AlignCenter, size=8)
            sum_a += m
            y += 3.6
        y += 2
        pg.text(cols[0], y, pg.W / 5, 4, tr("Sum of Masses"), Qt.AlignCenter, size=8)
        pg.text(cols[1], y, pg.W / 5, 4, f"{f5(sum_a)} (A)", Qt.AlignCenter, size=8)
        pg.text(cols[2], y, pg.W / 5, 4, f"{f5(sum_b)} (B)", Qt.AlignCenter, size=8)
        y += 5
        pg.line(0, y, pg.W, y, 0.15)
        y += 2
        y = self._cu_lines(pg, res, y, usp=True)
        y = self._fpd_lines(pg, res, y, usp=True)
        self._charts_and_regression(pg, res, y)

    def _page_graphical(self, pg: Page, runs):
        ds = self.ds
        y = self._header(pg, trf("Graphical Summary for {d}", d=short_name(ds)))
        pg.text(0, y, 150, 4, f"{tr('Other Info')} : {ds.other_info}", size=8)
        pg.text(pg.W - 100, y, 100, 4, f"{tr('File Name')}: {ds.file_name}", Qt.AlignRight | Qt.AlignVCenter, size=8)
        y += 5
        avail = pg.H - y - 10
        rh = avail / 3
        for i, run in enumerate(runs):
            res = self.summary.runs[run - 1]
            yy = y + i * rh
            pg.text(0, yy, 15, 4, trf("Run {n}", n=run), size=8.5, bold=True)
            pg.text(15, yy, 90, 4, f"{tr('Sampling Flow rate (l/min) =')} {res.flow:.2f}", size=8.5)
            w3 = pg.W / 3
            charts.draw_probit(pg.p, pg.rect(0, yy + 4, w3 - 4, rh - 6), res, fs=6.5)
            charts.draw_deposition(pg.p, ds, res, pg.rect(w3, yy + 4, w3 - 4, rh - 6),
                                   title=tr("Drug Mass Distribution"), fs=6.5)
            charts.draw_cumulative(pg.p, res, pg.rect(2 * w3, yy + 4, w3, rh - 6), fs=6.5)

    def _page_tabular(self, pg: Page, _):
        ds = self.ds
        y = self._header(pg, trf("Tabular Summary for {d}", d=short_name(ds)))
        if ds.fpd_by_stage:
            spec = trf("{a} to {b}", a=tr(ds.row_titles[ds.fpd_stage_row]), b=tr(ds.row_titles[-1]))
        else:
            spec = trf("Less than or Equal to {d} µm", d=f"{ds.fpd_size:.1f}")
        pg.text(0, y, 150, 4, f"{tr('Other Info')} : {ds.other_info}", size=8)
        pg.text(pg.W - 120, y, 120, 4, f"{tr('Fine Particle Dose Spec.')} {spec}", Qt.AlignRight | Qt.AlignVCenter, size=8)
        y += 4
        pg.text(pg.W - 120, y, 120, 4, f"{tr('File Name')}: {ds.file_name}", Qt.AlignRight | Qt.AlignVCenter, size=8)
        y += 6
        u = ds.unit
        heads = [tr("Run\nNo."), tr("Dose\nNos."), tr("No. of\nDoses\nSampled"), tr("Flow\nRate\nSampled"),
                 tr("Metered") + f"\n\n[{u}]", tr("Delivered") + f"\n\n[{u}]", tr("Fine Particle") + f"\n\n[{u}]", tr("Fine Particle") + "\n\n%",
                 "MMAD\n\n[µm]", "GSD", "R^2", "n", tr("Intercept"), tr("Slope")]
        widths = [10, 18, 16, 16, 20, 20, 22, 20, 18, 16, 16, 12, 20, 20]
        scale = pg.W / sum(widths)
        widths = [w * scale for w in widths]
        xs = [sum(widths[:i]) for i in range(len(widths))]
        pg.text(0, y, pg.W, 4, tr("Dose and Post Throat Particle Size Characterisation"), size=8, bold=True)
        y += 4.5
        pg.line(0, y, pg.W, y, 0.2)
        for x, w, hd in zip(xs, widths, heads):
            pg.text(x, y + 0.5, w, 11, hd, Qt.AlignCenter, size=7.5, bold=True)
        y += 12
        pg.line(0, y, pg.W, y, 0.2)
        y += 1
        runs = self.summary.runs
        getters = [lambda r: r.doses, lambda r: r.flow, lambda r: r.total, lambda r: r.delivered_calc,
                   lambda r: r.fpd, lambda r: r.fpf, lambda r: r.mmad, lambda r: r.gsd, lambda r: r.r2,
                   lambda r: r.n_reg, lambda r: r.intercept, lambda r: r.slope]
        for r in runs:
            vals = [str(r.run), ds.runs[r.run - 1].dose_no]
            for k, g in enumerate(getters):
                v = g(r)
                if k in (0, 9):
                    vals.append(f"{v:g}" if isinstance(v, (int, float)) else v)
                elif k == 1:
                    vals.append(f"{v:.2f}")
                else:
                    vals.append(f5(v))
            for x, w, v in zip(xs, widths, vals):
                pg.text(x, y, w, 3.6, v, Qt.AlignCenter, size=7.5)
            y += 3.6
        for lab, idx in ((tr("Mean"), 0), (tr("SD"), 1), (tr("%RSD"), 2)):
            vals = [lab, ""]
            for k, g in enumerate(getters):
                st = mean_sd_rsd([g(r) for r in runs if isinstance(g(r), (int, float))])
                v = st[idx]
                if k == 0:
                    vals.append("-")
                elif k == 1:
                    vals.append(f"{v:.2f}" if isinstance(v, float) else v)
                else:
                    vals.append(f5(v))
            for x, w, v in zip(xs, widths, vals):
                pg.text(x, y, w, 3.6, v, Qt.AlignCenter, size=7.5)
            y += 3.6
        y += 1
        pg.line(0, y, pg.W, y, 0.2)
        y += 6
        pg.text(0, y, 60, 4, tr("Data Input by:"), size=8)
        pg.text(70, y, 40, 4, tr("Date:"), size=8)
        pg.text(140, y, 60, 4, tr("Data Checked by:"), size=8)
        pg.text(210, y, 40, 4, tr("Date:"), size=8)

    def _page_groups(self, pg: Page, _):
        ds = self.ds
        y = self._header(pg, trf("Group Results for {d}", d=short_name(ds)))
        pg.text(0, y, 150, 4, f"{tr('Other Info')} : {ds.other_info}", size=8)
        pg.text(pg.W - 100, y, 100, 4, f"{tr('File Name')}: {ds.file_name}", Qt.AlignRight | Qt.AlignVCenter, size=8)
        y += 6
        runs = self.summary.runs
        n = len(runs)
        u = ds.unit
        lw = 52
        cw = (pg.W - lw) / (n + 3)
        heads = [trf("Run {n}", n=r.run) for r in runs] + [tr("Mean"), tr("SD"), tr("%RSD")]
        pg.line(0, y, pg.W, y, 0.2)
        for i, hd in enumerate(heads):
            pg.text(lw + i * cw, y + 0.5, cw, 4, hd, Qt.AlignCenter, size=7.5, bold=True)
        y += 5
        pg.line(0, y, pg.W, y, 0.2)
        y += 1
        for g in range(5):
            if ds.groups[g].mode == GROUP_OFF:
                continue
            gr0 = runs[0].groups[g]
            pg.text(0, y, 20, 3.8, trf("Group {n}", n=g + 1), size=7.5, bold=True)
            pg.text(0, y + 3.8, 26, 3.8, f"{tr('From')}  {gr0.label_from}", size=7.5)
            pg.text(0, y + 7.6, 26, 3.8, f"{tr('To')}    {gr0.label_to}", size=7.5)
            for k, (lab, attr) in enumerate(((f"{tr('Particle Dose')} [{u}]", "dose"), (f"{tr('Particle Fraction')} [%]", "fraction"))):
                yy = y + 3.8 + k * 3.8
                pg.text(26, yy, lw - 26, 3.8, lab, size=7.5)
                vals = [getattr(r.groups[g], attr) for r in runs]
                st = mean_sd_rsd([v for v in vals if isinstance(v, (int, float))])
                for i, v in enumerate(vals + list(st)):
                    pg.text(lw + i * cw, yy, cw, 3.8, f5(v), Qt.AlignCenter, size=7)
            y += 13
            pg.line(0, y, pg.W, y, 0.1)
            y += 1
        y += 6
        pg.text(0, y, 60, 4, tr("Data Input by:"), size=8)
        pg.text(70, y, 40, 4, tr("Date:"), size=8)
        pg.text(140, y, 60, 4, tr("Data Checked by:"), size=8)
        pg.text(210, y, 40, 4, tr("Date:"), size=8)
