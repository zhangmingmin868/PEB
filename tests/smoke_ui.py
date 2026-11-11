"""Headless UI smoke test: opens each legacy example file, grabs screenshots of the
three screens and renders every report type to PDF.

usage: QT_QPA_PLATFORM=offscreen python tests/smoke_ui.py <out-dir>
"""
import glob
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtGui import QPdfWriter          # noqa: E402
from PySide6.QtWidgets import QApplication    # noqa: E402

from labdream import fileio, reports          # noqa: E402
from labdream.ui.main_window import MainWindow  # noqa: E402
from labdream.ui.wizard import DataWizard     # noqa: E402
from labdream.ui.dialogs import GroupSpecDialog, GroupResultsDialog, PrintDialog, DeviceSelectDialog  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "..", "Copley原装软件", "CITDAS V3.10 Validation")


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    mw = MainWindow()
    mw.show()
    app.processEvents()
    mw.grab().save(os.path.join(out, "main.png"))
    d = DeviceSelectDialog(mw)
    d.show(); app.processEvents()
    d.grab().save(os.path.join(out, "device_select.png"))
    d.close()

    files = sorted(glob.glob(os.path.join(SRC, "Example Files", "*.CPL")))
    files += [os.path.join(SRC, "Scanned and Checked Input-Output", "FILE CI 1.CPL")]
    for path in files:
        ds = fileio.load(path)
        tag = os.path.splitext(os.path.basename(path))[0].replace(" ", "_")
        wiz = DataWizard(ds, path, mw)
        wiz.show()
        for i in range(3):
            wiz.screens[i].load()
            wiz.set_page(i)
            app.processEvents()
            wiz.grab().save(os.path.join(out, f"{tag}_screen{i+1}.png"))
        g = GroupSpecDialog(ds, wiz); g.show(); app.processEvents()
        g.grab().save(os.path.join(out, f"{tag}_groupspec.png")); g.close()
        gr = GroupResultsDialog(ds, wiz.screens[2].summary, wiz); gr.show(); app.processEvents()
        gr.grab().save(os.path.join(out, f"{tag}_groupresults.png")); gr.close()
        sel = [(reports.EP, "1", reports.MEAN), (reports.USP, "1", "2"), (reports.GRAPHICAL, None, None),
               (reports.TABULAR, None, None), (reports.GROUPS, None, None)]
        rr = reports.ReportRenderer(ds, sel)
        w = QPdfWriter(os.path.join(out, f"{tag}_report.pdf"))
        w.setResolution(150)
        rr.render(w)
        del w
        fileio.export_csv(ds, os.path.join(out, f"{tag}.csv"))
        fileio.save(ds, os.path.join(out, f"{tag}.ldd"))
        wiz.modified = False
        wiz.close()
        print("ok", tag, rr.page_count, "pages")
    p = PrintDialog(12, mw); p.show(); app.processEvents()
    p.grab().save(os.path.join(out, "print_dialog.png"))
    print("done")


if __name__ == "__main__":
    main()
