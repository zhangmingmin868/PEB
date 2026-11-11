"""Login, first administrator, password change, user management and audit trail."""
from __future__ import annotations

import json

from PySide6.QtCore import Qt, QDate, QSettings
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QDialog,
                               QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
                               QTextEdit, QVBoxLayout)

from .. import session
from ..fileio import APP_VERSION
from ..i18n import LANGUAGES, language, set_language, tr, trf
from ..security import MIN_PASSWORD, ROLES, AuthError, password_problem
from .dialogs import ok_cancel

PW_MESSAGES = {
    "pw_short": "The password must have at least {n} characters.",
    "pw_mix": "The password must contain letters and digits.",
    "pw_same": "The new password must be different from the old one.",
    "user_exists": "This user name already exists.",
    "empty_user": "Enter a user name.",
    "last_admin": "At least one active administrator is required.",
    "bad_login": "Wrong user name or password.",
    "locked": "This account is locked after too many failed attempts. Ask an administrator to unlock it.",
    "inactive": "This account is deactivated.",
}


def message(key: str) -> str:
    return trf(PW_MESSAGES.get(key, key), n=MIN_PASSWORD)


def _pw(edit_parent=None):
    e = QLineEdit(edit_parent)
    e.setEchoMode(QLineEdit.Password)
    return e


class LoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_VERSION} – {tr('Log In')}")
        self.user = None
        self.lang_changed = False
        lay = QVBoxLayout(self)
        t = QLabel("LabDream")
        t.setFont(QFont("Arial", 24, QFont.Bold))
        t.setStyleSheet("color:#1f4fa8")
        lay.addWidget(t)
        lay.addWidget(QLabel(tr("Inhaler Testing Data Analysis Software")))
        form = QFormLayout()
        self.lang = QComboBox()
        for code, name in LANGUAGES.items():
            self.lang.addItem(name, code)
        self.lang.setCurrentIndex(max(0, self.lang.findData(language())))
        self.lang.currentIndexChanged.connect(self._lang)
        self.name = QLineEdit(QSettings("LabDream", "LabDream").value("last_user", "", type=str))
        self.pw = _pw()
        form.addRow(tr("Language"), self.lang)
        form.addRow(tr("User name"), self.name)
        form.addRow(tr("Password"), self.pw)
        lay.addLayout(form)
        self.err = QLabel()
        self.err.setStyleSheet("color:#c00")
        self.err.setWordWrap(True)
        lay.addWidget(self.err)
        lay.addWidget(ok_cancel(self, self._ok, self.reject))
        (self.pw if self.name.text() else self.name).setFocus()
        self.resize(380, 260)

    def _lang(self):
        code = self.lang.currentData()
        set_language(code)
        QSettings("LabDream", "LabDream").setValue("language", code)
        self.lang_changed = True
        self.done(2)                     # caller re-opens the dialog in the new language

    def _ok(self):
        try:
            u = session.store.authenticate(self.name.text().strip(), self.pw.text())
        except AuthError as e:
            self.err.setText(message(str(e)))
            self.pw.clear()
            return
        QSettings("LabDream", "LabDream").setValue("last_user", u.username)
        session.user = u
        if u.must_change:
            QMessageBox.information(self, tr("Change Password"),
                                    tr("You must set a new password before continuing."))
            d = ChangePasswordDialog(self, forced=True)
            if d.exec() != QDialog.Accepted:
                session.log("LOGOUT", u.username, {"reason": "password change cancelled"})
                session.user = None
                return
            session.user = session.store.get(u.username)
        self.user = session.user
        self.accept()


class FirstAdminDialog(QDialog):
    """Shown on first start: create the first administrator account."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_VERSION} – {tr('Create Administrator')}")
        lay = QVBoxLayout(self)
        info = QLabel(tr("No users exist yet. Create the first administrator account.")
                      + "\n" + trf("Passwords need at least {n} characters with letters and digits.", n=MIN_PASSWORD))
        info.setWordWrap(True)
        lay.addWidget(info)
        form = QFormLayout()
        self.name = QLineEdit("admin")
        self.full = QLineEdit()
        self.pw = _pw()
        self.pw2 = _pw()
        form.addRow(tr("User name"), self.name)
        form.addRow(tr("Full name"), self.full)
        form.addRow(tr("Password"), self.pw)
        form.addRow(tr("Confirm password"), self.pw2)
        lay.addLayout(form)
        self.err = QLabel()
        self.err.setStyleSheet("color:#c00")
        self.err.setWordWrap(True)
        lay.addWidget(self.err)
        lay.addWidget(ok_cancel(self, self._ok, self.reject))
        self.resize(420, 260)

    def _ok(self):
        if self.pw.text() != self.pw2.text():
            self.err.setText(tr("The passwords do not match."))
            return
        try:
            session.store.create_user("SYSTEM", self.name.text(), self.full.text(), "admin",
                                      self.pw.text(), must_change=False)
        except ValueError as e:
            self.err.setText(message(str(e)))
            return
        self.accept()


class ChangePasswordDialog(QDialog):
    def __init__(self, parent=None, forced=False):
        super().__init__(parent)
        self.setWindowTitle(tr("Change Password"))
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.old = _pw()
        self.new = _pw()
        self.new2 = _pw()
        form.addRow(tr("Current password"), self.old)
        form.addRow(tr("New password"), self.new)
        form.addRow(tr("Confirm password"), self.new2)
        lay.addLayout(form)
        lay.addWidget(QLabel(trf("Passwords need at least {n} characters with letters and digits.", n=MIN_PASSWORD)))
        self.err = QLabel()
        self.err.setStyleSheet("color:#c00")
        self.err.setWordWrap(True)
        lay.addWidget(self.err)
        lay.addWidget(ok_cancel(self, self._ok, self.reject))

    def _ok(self):
        if self.new.text() != self.new2.text():
            self.err.setText(tr("The passwords do not match."))
            return
        try:
            session.store.change_password(session.name(), self.old.text(), self.new.text())
        except AuthError:
            self.err.setText(tr("The current password is wrong."))
            return
        except ValueError as e:
            self.err.setText(message(str(e)))
            return
        QMessageBox.information(self, tr("Change Password"), tr("Password changed."))
        self.accept()


class UserEditDialog(QDialog):
    def __init__(self, parent=None, user=None):
        super().__init__(parent)
        self.u = user
        self.setWindowTitle(tr("Edit User") if user else tr("New User"))
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(user.username if user else "")
        self.name.setReadOnly(user is not None)
        self.full = QLineEdit(user.full_name if user else "")
        self.role = QComboBox()
        for r in ROLES:
            self.role.addItem(tr(r), r)
        self.role.setCurrentIndex(max(0, self.role.findData(user.role if user else "analyst")))
        self.active = QCheckBox(tr("Active"))
        self.active.setChecked(user.active if user else True)
        form.addRow(tr("User name"), self.name)
        form.addRow(tr("Full name"), self.full)
        form.addRow(tr("Role"), self.role)
        form.addRow("", self.active)
        if user is None:
            self.pw = _pw()
            self.pw2 = _pw()
            form.addRow(tr("Initial password"), self.pw)
            form.addRow(tr("Confirm password"), self.pw2)
        lay.addLayout(form)
        lay.addWidget(QLabel(tr("admin: all functions, user management, calibration and audit trail\n"
                                "analyst: enter, edit, save, print and export data\n"
                                "reviewer: view, print and export data, view audit trail")))
        self.err = QLabel()
        self.err.setStyleSheet("color:#c00")
        self.err.setWordWrap(True)
        lay.addWidget(self.err)
        lay.addWidget(ok_cancel(self, self._ok, self.reject))

    def _ok(self):
        try:
            if self.u is None:
                if self.pw.text() != self.pw2.text():
                    self.err.setText(tr("The passwords do not match."))
                    return
                session.store.create_user(session.name(), self.name.text(), self.full.text(),
                                          self.role.currentData(), self.pw.text(), must_change=True)
                if not self.active.isChecked():
                    session.store.update_user(session.name(), self.name.text(), self.full.text(),
                                              self.role.currentData(), False)
            else:
                session.store.update_user(session.name(), self.u.username, self.full.text(),
                                          self.role.currentData(), self.active.isChecked())
        except ValueError as e:
            self.err.setText(message(str(e)))
            return
        self.accept()


class UserManagementDialog(QDialog):
    COLS = ["User name", "Full name", "Role", "Status", "Created", "Created by", "Last login"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("User Management"))
        self.resize(900, 420)
        lay = QVBoxLayout(self)
        self.t = QTableWidget(0, len(self.COLS))
        self.t.setHorizontalHeaderLabels([tr(c) for c in self.COLS])
        self.t.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.t.setSelectionMode(QAbstractItemView.SingleSelection)
        self.t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.t.doubleClicked.connect(self.edit)
        lay.addWidget(self.t)
        h = QHBoxLayout()
        for text, fn in ((tr("New User…"), self.new), (tr("Edit…"), self.edit),
                         (tr("Reset Password…"), self.reset_pw), (tr("Unlock"), self.unlock)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            h.addWidget(b)
        h.addStretch(1)
        close = QPushButton(tr("Close"))
        close.clicked.connect(self.accept)
        h.addWidget(close)
        lay.addLayout(h)
        lay.addWidget(QLabel(tr("Users cannot be deleted; deactivate them instead so the audit trail stays complete.")))
        self.reload()

    def reload(self):
        users = session.store.users()
        self.users = users
        self.t.setRowCount(len(users))
        for i, u in enumerate(users):
            status = tr("Locked") if u.locked else (tr("Active") if u.active else tr("Inactive"))
            for j, v in enumerate([u.username, u.full_name, tr(u.role), status, u.created_at,
                                   u.created_by, u.last_login]):
                self.t.setItem(i, j, QTableWidgetItem(v))

    def selected(self):
        r = self.t.currentRow()
        if r < 0:
            QMessageBox.information(self, tr("User Management"), tr("Select a user first."))
            return None
        return self.users[r]

    def new(self):
        if UserEditDialog(self).exec() == QDialog.Accepted:
            self.reload()

    def edit(self, *_):
        u = self.selected()
        if u and UserEditDialog(self, u).exec() == QDialog.Accepted:
            self.reload()

    def reset_pw(self):
        u = self.selected()
        if not u:
            return
        d = QDialog(self)
        d.setWindowTitle(tr("Reset Password"))
        lay = QFormLayout(d)
        p1, p2 = _pw(), _pw()
        lay.addRow(tr("New password"), p1)
        lay.addRow(tr("Confirm password"), p2)
        err = QLabel()
        err.setStyleSheet("color:#c00")
        lay.addRow(err)

        def ok():
            if p1.text() != p2.text():
                err.setText(tr("The passwords do not match."))
                return
            try:
                session.store.reset_password(session.name(), u.username, p1.text())
            except ValueError as e:
                err.setText(message(str(e)))
                return
            d.accept()
        lay.addRow(ok_cancel(d, ok, d.reject))
        if d.exec() == QDialog.Accepted:
            QMessageBox.information(self, tr("Reset Password"),
                                    tr("Password reset. The user must change it at the next log in."))
            self.reload()

    def unlock(self):
        u = self.selected()
        if u:
            session.store.unlock(session.name(), u.username)
            self.reload()


class AuditTrailDialog(QDialog):
    COLS = ["Time (UTC)", "User", "Action", "Object", "Details"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Audit Trail"))
        self.resize(1150, 620)
        lay = QVBoxLayout(self)
        f = QHBoxLayout()
        self.user = QComboBox()
        self.user.addItem(tr("All users"), None)
        for u in session.store.users():
            self.user.addItem(u.username, u.username)
        self.action = QComboBox()
        self.action.addItem(tr("All actions"), None)
        for a in session.store.actions():
            self.action.addItem(tr(a), a)
        self.d_from = QDateEdit(QDate.currentDate().addMonths(-1))
        self.d_to = QDateEdit(QDate.currentDate())
        for d in (self.d_from, self.d_to):
            d.setCalendarPopup(True)
            d.setDisplayFormat("yyyy-MM-dd")
        self.text = QLineEdit()
        self.text.setPlaceholderText(tr("Search object / details"))
        go = QPushButton(tr("Apply Filter"))
        go.clicked.connect(self.reload)
        for w in (QLabel(tr("User")), self.user, QLabel(tr("Action")), self.action, QLabel(tr("From")),
                  self.d_from, QLabel(tr("To")), self.d_to, self.text, go):
            f.addWidget(w)
        lay.addLayout(f)
        self.t = QTableWidget(0, len(self.COLS))
        self.t.setHorizontalHeaderLabels([tr(c) for c in self.COLS])
        self.t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.t.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.t.horizontalHeader().setStretchLastSection(True)
        self.t.currentCellChanged.connect(self._show)
        lay.addWidget(self.t, 3)
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        lay.addWidget(self.detail, 1)
        h = QHBoxLayout()
        v = QPushButton(tr("Verify Integrity"))
        v.clicked.connect(self.verify)
        e = QPushButton(tr("Export CSV…"))
        e.clicked.connect(self.export)
        close = QPushButton(tr("Close"))
        close.clicked.connect(self.accept)
        self.count = QLabel()
        h.addWidget(v); h.addWidget(e); h.addWidget(self.count); h.addStretch(1); h.addWidget(close)
        lay.addLayout(h)
        session.log("AUDIT_VIEWED", "audit trail", {})
        self.reload()

    def reload(self):
        self.rows = session.store.records(username=self.user.currentData(), action=self.action.currentData(),
                                          text=self.text.text().strip() or None,
                                          date_from=self.d_from.date().toString("yyyy-MM-dd"),
                                          date_to=self.d_to.date().toString("yyyy-MM-dd"))
        self.t.setRowCount(len(self.rows))
        for i, r in enumerate(self.rows):
            det = r["details"]
            short = det if len(det) < 160 else det[:157] + "…"
            for j, v in enumerate([r["ts"], r["username"], tr(r["action"]), r["target"], short]):
                self.t.setItem(i, j, QTableWidgetItem(v))
        self.t.resizeColumnsToContents()
        self.count.setText(trf("{n} records", n=len(self.rows)))

    def _show(self, row, *_):
        if 0 <= row < len(self.rows):
            r = self.rows[row]
            try:
                det = json.dumps(json.loads(r["details"]), ensure_ascii=False, indent=2)
            except ValueError:
                det = r["details"]
            self.detail.setPlainText(f"#{r['id']}  {r['ts']}  {r['username']}  {r['action']}  {r['target']}\n"
                                     f"{det}\nSHA-256: {r['hash']}")

    def verify(self):
        ok, n, bad = session.store.verify()
        if ok:
            QMessageBox.information(self, tr("Audit Trail"),
                                    trf("Integrity check passed: {n} records, hash chain intact.", n=n))
        else:
            QMessageBox.critical(self, tr("Audit Trail"),
                                 trf("Integrity check FAILED at record #{id}. The audit trail has been altered.", id=bad))
        session.log("AUDIT_VERIFIED", "audit trail", {"ok": ok, "records": n})

    def export(self):
        path, _ = QFileDialog.getSaveFileName(self, tr("Export CSV…"), "labdream_audit_trail.csv", "CSV (*.csv)")
        if path:
            session.store.export_csv(path, self.rows)
            session.log("AUDIT_EXPORTED", "audit trail", {"file": path, "records": len(self.rows)})
            QMessageBox.information(self, tr("Audit Trail"), trf("Data exported:\n{path}", path=path))
