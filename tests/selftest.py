"""Self-contained tests (no external data needed).

    python tests/selftest.py        engine tests with synthetic lognormal data
    python tests/selftest.py --ui   also opens every screen offscreen and renders all reports
"""
import math
import os
import sys
import tempfile
from statistics import NormalDist

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from labdream import fileio                       # noqa: E402
from labdream.devices import DEVICE_ORDER, scaled_ecd  # noqa: E402
from labdream.engine import analyse, NA            # noqa: E402
from labdream.model import new_dataset             # noqa: E402

N = NormalDist()


def lognormal_dataset(device, mmad, gsd, flow, total=100.0):
    """Stage masses of an exact lognormal distribution."""
    ds = new_dataset(device)
    ds.n_runs = 1
    run = ds.runs[0]
    run.flow = flow
    run.doses = 1
    ecd = scaled_ecd(ds.dev, ds.cal_flow, ds.ecd, flow)
    first = 3 + ds.dev.first_size_stage
    rows = list(range(first, ds.n_rows))
    cdf = lambda d: N.cdf(math.log(d / mmad) / math.log(gsd)) if d > 0 else 0.0
    for k, r in enumerate(rows):
        upper = 1.0 if k == 0 else cdf(ecd[rows[k - 1] - 3])
        lower = cdf(ecd[r - 3]) if r < ds.n_rows - 1 else 0.0
        run.masses[r] = total * (upper - lower)
    run.delivered = total
    return ds


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def engine_tests():
    n = 0
    for dev in DEVICE_ORDER:
        for mmad in (2.0, 3.0):
            for gsd in (1.5, 2.0):
                for flow in (30.0, 60.0, 90.0):
                    ds = lognormal_dataset(dev, mmad, gsd, flow)
                    r = analyse(ds).runs[0]
                    cuts = [d for d in scaled_ecd(ds.dev, ds.cal_flow, ds.ecd, flow) if d > 0]
                    if mmad < min(cuts):          # below range -> must be NA
                        check(r.mmad == NA, f"{dev} MMAD should be NA @ {flow}")
                        n += 1
                        continue
                    check(r.mmad != NA and abs(r.mmad / mmad - 1) < 1e-3,
                          f"{dev} MMAD {r.mmad} != {mmad} @ {flow}")
                    if r.gsd != NA:
                        check(abs(r.gsd / gsd - 1) < 2e-3, f"{dev} GSD {r.gsd} != {gsd} @ {flow}")
                    exp = 100.0 * N.cdf(math.log(5.0 / mmad) / math.log(gsd))
                    check(abs(r.fpd - exp) < 0.6, f"{dev} FPD {r.fpd} != {exp:.3f} @ {flow}")
                    check(abs(r.total - 100.0) < 1e-6, "total")
                    n += 1
    # NA rule: almost everything on the filter
    ds = lognormal_dataset("CI", 0.2, 1.3, 28.3)
    check(analyse(ds).runs[0].mmad == NA, "MMAD should be NA when >50% on filter")
    # save / load round trip
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "t.ldd")
        ds = lognormal_dataset("NGI", 3.0, 1.8, 60)
        fileio.save(ds, p)
        ds2 = fileio.load(p)
        check(abs(analyse(ds2).runs[0].mmad - analyse(ds).runs[0].mmad) < 1e-12, "round trip")
        fileio.export_csv(ds2, os.path.join(d, "t.csv"))
    print(f"engine tests passed ({n} distributions)")


def ui_tests():
    from PySide6.QtGui import QPdfWriter
    from PySide6.QtWidgets import QApplication
    from labdream import reports
    from labdream.ui.main_window import MainWindow
    from labdream.ui.wizard import DataWizard

    app = QApplication.instance() or QApplication(sys.argv)
    mw = MainWindow()
    mw.show()
    with tempfile.TemporaryDirectory() as d:
        for dev in DEVICE_ORDER:
            ds = lognormal_dataset(dev, 3.0, 1.8, 60)
            ds.n_runs = 3
            for j in (1, 2):
                ds.runs[j] = ds.runs[0]
            wiz = DataWizard(ds, None, mw)
            wiz.show()
            for i in range(3):
                wiz.screens[i].load()
                wiz.set_page(i)
                app.processEvents()
            sel = [(reports.EP, "1", reports.MEAN), (reports.USP, "1", "1"),
                   (reports.GRAPHICAL, None, None), (reports.TABULAR, None, None),
                   (reports.GROUPS, None, None)]
            rr = reports.ReportRenderer(ds, sel)
            w = QPdfWriter(os.path.join(d, f"{dev}.pdf"))
            w.setResolution(100)
            rr.render(w)
            del w
            check(os.path.getsize(os.path.join(d, f"{dev}.pdf")) > 5000, "empty report")
            wiz.modified = False
            wiz.close()
    print("ui tests passed")


if __name__ == "__main__":
    engine_tests()
    if "--ui" in sys.argv:
        ui_tests()
