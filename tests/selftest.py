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

from labdream import fileio, session              # noqa: E402
from labdream.devices import DEVICES, DEVICE_ORDER, factory_ecd, scaled_ecd  # noqa: E402
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


def ecd_tests():
    """ECDs at other flow rates must equal the reference tables (Ph. Eur. 2.9.18 / USP <601>)."""
    ref = {
        ("NGI", 15): [14.10, 8.61, 5.39, 3.30, 2.08, 1.36, 0.98],
        ("NGI", 29): [11.80716, 6.49370, 4.04912, 2.34102, 1.38854, 0.85030, 0.55598],
        ("NGI", 30): [11.71902, 6.39544, 3.98808, 2.29928, 1.35729, 0.83364, 0.54096],
        ("NGI", 90): [6.47509, 3.61216, 2.30252, 1.37197, 0.75823, 0.43123, 0.25912],
        ("CI", 60): [6.18102, 3.98332, 3.22787, 2.26637, 1.44224, 0.75546, 0.48075, 0.29532],
        ("CI", 90): [5.04678, 3.25237, 2.63554, 1.85049, 1.17758, 0.61683, 0.39253, 0.24112],
        ("MSLI", 30): [18.38478, 9.61665, 4.38406, 2.40416],
        ("MMI", 90): [8.16497, 4.08248, 2.04124, 1.02062, 0.51031],
    }
    for (dev, q), vals in ref.items():
        got = factory_ecd(DEVICES[dev], q)
        for a, b in zip(got, vals):
            check(abs(a - b) < 6e-5, f"{dev} @ {q}: {a} != {b}")
    # scaling a calibration at 15 L/min to 30 L/min follows the same tables
    ngi = DEVICES["NGI"]
    s = scaled_ecd(ngi, 15, factory_ecd(ngi, 15), 30)
    check(all(abs(a - b) < 1e-3 for a, b in zip(s, factory_ecd(ngi, 30))), "NGI 15->30 scaling")
    print("ecd tests passed")


def security_tests():
    from labdream.security import Store, AuthError
    with tempfile.TemporaryDirectory() as d:
        st = Store(os.path.join(d, "t.db"))
        check(not st.has_users(), "empty")
        st.create_user("SYSTEM", "admin", "Admin", "admin", "secret123", must_change=False)
        st.create_user("admin", "ana", "Ana", "analyst", "start1234")
        try:
            st.create_user("admin", "bad", "", "analyst", "short")
            check(False, "weak password accepted")
        except ValueError:
            pass
        u = st.authenticate("ana", "start1234")
        check(u.must_change and u.can("edit_data") and not u.can("manage_users"), "analyst rights")
        st.change_password("ana", "start1234", "newpass99")
        for _ in range(5):
            try:
                st.authenticate("ana", "wrong")
            except AuthError:
                pass
        check(st.get("ana").locked, "lockout after 5 failures")
        st.unlock("admin", "ana")
        check(st.authenticate("ana", "newpass99").username == "ana", "unlock")
        try:
            st.update_user("admin", "admin", "Admin", "analyst", True)
            check(False, "last admin demoted")
        except ValueError:
            pass
        ok, n, _ = st.verify()
        check(ok and n > 5, "audit chain")
        # tampering is detected even when the triggers are bypassed
        st.db.execute("DROP TRIGGER audit_no_update")
        st.db.execute("UPDATE audit SET details='{}' WHERE id=2")
        st.db.commit()
        ok, n, bad = st.verify()
        check(not ok and bad == 2, "tamper detection")
        st.db.close()
    print("security tests passed")


def ui_tests():
    from PySide6.QtGui import QPdfWriter
    from PySide6.QtWidgets import QApplication
    from labdream import reports
    from labdream.ui.main_window import MainWindow
    from labdream.ui.wizard import DataWizard

    from labdream.i18n import set_language
    app = QApplication.instance() or QApplication(sys.argv)
    tmp = tempfile.mkdtemp()
    st = session.init(os.path.join(tmp, "ui.db"))
    st.create_user("SYSTEM", "admin", "Admin", "admin", "secret123", must_change=False)
    session.user = st.authenticate("admin", "secret123")
    for lang in ("zh", "es", "fr", "en"):
        set_language(lang)
        MainWindow().close()                     # closing the main window logs out
        session.user = st.get("admin")
    mw = MainWindow()
    mw.show()
    with tempfile.TemporaryDirectory() as d:
        for dev in DEVICE_ORDER:
            ds = lognormal_dataset(dev, 3.0, 1.8, 60)
            ds.n_runs = 3
            for j in (1, 2):
                ds.runs[j] = ds.runs[0]
            check(session.can("edit_data"), "logged in")
            wiz = DataWizard(ds, None, mw)
            wiz.show()
            for i in range(3):
                wiz.screens[i].load()
                wiz.set_page(i)
                app.processEvents()
            sel = [(reports.EP, "1", reports.MEAN), (reports.USP, "1", "1"),
                   (reports.GRAPHICAL, None, None), (reports.TABULAR, None, None),
                   (reports.GROUPS, None, None)]
            set_language(["en", "zh", "es", "fr"][DEVICE_ORDER.index(dev)])
            rr = reports.ReportRenderer(ds, sel, printed_by="admin")
            w = QPdfWriter(os.path.join(d, f"{dev}.pdf"))
            w.setResolution(100)
            rr.render(w)
            del w
            check(os.path.getsize(os.path.join(d, f"{dev}.pdf")) > 5000, "empty report")
            wiz.modified = False
            wiz.close()
    print("ui tests passed")


def pbe_ui_tests():
    """Module selection, PBE editor, e-signature workflow and PDF report (offscreen)."""
    import csv
    from PySide6.QtGui import QPdfWriter
    from PySide6.QtWidgets import QApplication
    from labdream import pbe
    from labdream.i18n import set_language
    from labdream.pbe_report import PbeReport
    from labdream.ui.home import HomeWindow
    from labdream.ui.pbe_window import PbeEditor, PbeMainWindow, SignDialog

    app = QApplication.instance() or QApplication(sys.argv)
    tmp = tempfile.mkdtemp()
    st = session.init(os.path.join(tmp, "pbe.db"))
    st.create_user("SYSTEM", "admin", "Admin", "admin", "secret123", must_change=False)
    st.create_user("admin", "ana", "Ana Lyst", "analyst", "secret123", must_change=False)
    st.create_user("admin", "rev", "Rev Iewer", "reviewer", "secret123", must_change=False)
    rows = list(csv.reader(open(os.path.join(os.path.dirname(__file__), "data", "fda_budesonide_example.csv"))))
    R, T, m, names = pbe.parse_long_table(rows)
    for lang in ("zh", "es", "fr", "en"):
        set_language(lang)
        session.user = st.get("admin")
        h = HomeWindow(); h._leaving = True; h.close()
        w = PbeMainWindow(); w._leaving = True; w.close()
        study = pbe.PbeStudy(m=m, reference=R, test=T, ln_transform=False, stage_names=names + ["", "", ""],
                             parameter="Delivered dose", title="FDA example")
        ed = PbeEditor(study, None)
        ed.show()
        for i in range(4):
            ed.tabs.setCurrentIndex(i)
            app.processEvents()
        check("PASSED" in ed.results.toPlainText() or "通过" in ed.results.toPlainText()
              or "CUMPLE" in ed.results.toPlainText() or "CONFORME" in ed.results.toPlainText(), "result shown")
        pdf = os.path.join(tmp, f"pbe_{lang}.pdf")
        wr = QPdfWriter(pdf); wr.setResolution(150)
        PbeReport(study, printed_by="admin").render(wr)
        del wr
        check(os.path.getsize(pdf) > 5000, "empty PBE report")
        ed.modified = False
        ed.close()

    # e-signature workflow: analyst performs, reviewer reviews; change invalidates
    path = os.path.join(tmp, "study.pbe")
    session.user = st.get("ana")
    study = pbe.PbeStudy(m=m, reference=pbe.clone(pbe.PbeStudy(reference=R)).reference, test=T, ln_transform=False)
    ed = PbeEditor(study, None)
    ed._write(path)
    d = SignDialog(ed.st, ed)
    d.pw.setText("wrong-pw1")
    d._ok()
    check(d.sig is None, "wrong password must not sign")
    d.pw.setText("secret123")
    d._ok()
    check(d.sig is not None and d.sig.meaning == "performed", "analyst signs performed")
    ed.st.signatures.append(d.sig)
    pbe.save(ed.st, path)
    ed.close()
    session.user = st.get("rev")
    loaded = pbe.load(path)
    check(len(loaded.valid_signatures()) == 1, "signature valid after reload")
    d = SignDialog(loaded)
    d.pw.setText("secret123")
    d._ok()
    check(d.sig is not None and d.sig.meaning == "reviewed", "reviewer signs reviewed")
    loaded.signatures.append(d.sig)
    loaded.test[0].containers[0].values[0] = 1.0
    check(len(loaded.valid_signatures()) == 0, "change must invalidate signatures")
    acts = {r["action"] for r in st.records(limit=10000)}
    for a in ("FILE_CREATED", "SIGNATURE_FAILED", "LOGIN_FAILED"):
        check(a in acts, f"audit trail missing {a}")
    ok, n, _ = st.verify()
    check(ok, "audit chain")
    print(f"pbe ui tests passed ({n} audit records)")


def _note(msg):
    if os.environ.get("GITHUB_ACTIONS"):
        print("::notice title=selftest::" + msg, flush=True)


def _main():
    import faulthandler
    faulthandler.enable()
    engine_tests(); _note("engine ok")
    ecd_tests(); _note("ecd ok")
    security_tests(); _note("security ok")
    if "--ui" in sys.argv:
        ui_tests(); _note("apsd ui ok")
        pbe_ui_tests(); _note("pbe ui ok")


if __name__ == "__main__":
    try:
        _main()
    except BaseException:
        import traceback
        tb = traceback.format_exc()
        print(tb)
        if os.environ.get("GITHUB_ACTIONS"):
            print("::error title=selftest::" + tb.replace("%", "%25").replace("\r", "").replace("\n", "%0A"))
        sys.exit(1)
    # All tests passed. Skip interpreter teardown: destroying leftover Qt
    # widgets at exit can crash on Windows and turn a pass into exit code 1.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
