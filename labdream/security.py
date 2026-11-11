"""User management and audit trail (SQLite).

* Users have a role:
    admin    – everything, incl. user management, maintenance mode
               (stage titles / calibration / ECD), templates, audit trail
    analyst  – enter and edit data, save, print, export
    reviewer – open, view, print and export data; view the audit trail
* Passwords are stored as PBKDF2-HMAC-SHA256 hashes with a random salt.
* After MAX_FAILED wrong passwords an account is locked until an admin unlocks it.
* Users are never deleted, only deactivated, so the audit trail stays readable.
* The audit trail is append-only; every record carries the SHA-256 hash of the
  previous record, so any later edit or deletion is detected by verify().
"""
from __future__ import annotations

import csv
import datetime as _dt
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import sys
from dataclasses import dataclass
from typing import List, Optional

ROLE_ADMIN, ROLE_ANALYST, ROLE_REVIEWER = "admin", "analyst", "reviewer"
ROLES = [ROLE_ADMIN, ROLE_ANALYST, ROLE_REVIEWER]
MAX_FAILED = 5
MIN_PASSWORD = 8
PBKDF2_ROUNDS = 200_000
GENESIS = "0" * 64

PERMISSIONS = {
    ROLE_ADMIN: {"edit_data", "maintenance", "manage_users", "view_audit", "templates", "print", "export"},
    ROLE_ANALYST: {"edit_data", "print", "export"},
    ROLE_REVIEWER: {"view_audit", "print", "export"},
}


def data_dir() -> str:
    """Folder for the user database / audit trail (shared by all users of the PC)."""
    env = os.environ.get("LABDREAM_DATA_DIR")
    if env:
        path = env
    elif sys.platform == "win32":
        path = os.path.join(os.environ.get("PROGRAMDATA") or os.environ.get("APPDATA", "."), "LabDream")
    elif sys.platform == "darwin":
        path = os.path.expanduser("~/Library/Application Support/LabDream")
    else:
        path = os.path.expanduser("~/.local/share/LabDream")
    os.makedirs(path, exist_ok=True)
    return path


def now_utc() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS).hex()


def password_problem(password: str) -> Optional[str]:
    """Return a problem key if the password does not meet the policy."""
    if len(password) < MIN_PASSWORD:
        return "pw_short"
    if not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
        return "pw_mix"
    return None


@dataclass
class User:
    username: str
    full_name: str
    role: str
    active: bool
    locked: bool
    must_change: bool
    failed: int
    created_at: str
    created_by: str
    last_login: str

    def can(self, perm: str) -> bool:
        return perm in PERMISSIONS.get(self.role, set())


class AuthError(Exception):
    """Raised with a message key: bad_login, locked, inactive."""


class Store:
    def __init__(self, path: Optional[str] = None):
        self.path = path or os.path.join(data_dir(), "labdream.db")
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users(
                username TEXT PRIMARY KEY COLLATE NOCASE,
                full_name TEXT NOT NULL DEFAULT '',
                role TEXT NOT NULL,
                pw_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                locked INTEGER NOT NULL DEFAULT 0,
                must_change INTEGER NOT NULL DEFAULT 1,
                failed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                created_by TEXT NOT NULL,
                pw_changed_at TEXT NOT NULL DEFAULT '',
                last_login TEXT NOT NULL DEFAULT '');
            CREATE TABLE IF NOT EXISTS audit(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                username TEXT NOT NULL,
                action TEXT NOT NULL,
                target TEXT NOT NULL DEFAULT '',
                details TEXT NOT NULL DEFAULT '',
                prev_hash TEXT NOT NULL,
                hash TEXT NOT NULL);
            CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
                BEGIN SELECT RAISE(ABORT, 'audit trail is read-only'); END;
            CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
                BEGIN SELECT RAISE(ABORT, 'audit trail is read-only'); END;
            """
        )
        self.db.commit()

    # ------------------------------------------------------------------ users
    def has_users(self) -> bool:
        return self.db.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0

    def _row_to_user(self, r) -> User:
        return User(r["username"], r["full_name"], r["role"], bool(r["active"]), bool(r["locked"]),
                    bool(r["must_change"]), r["failed"], r["created_at"], r["created_by"], r["last_login"])

    def get(self, username: str) -> Optional[User]:
        r = self.db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        return self._row_to_user(r) if r else None

    def users(self) -> List[User]:
        return [self._row_to_user(r) for r in self.db.execute("SELECT * FROM users ORDER BY username")]

    def create_user(self, by: str, username: str, full_name: str, role: str, password: str,
                    must_change=True) -> User:
        username = username.strip()
        if not username:
            raise ValueError("empty_user")
        if self.get(username):
            raise ValueError("user_exists")
        if role not in ROLES:
            raise ValueError("bad_role")
        p = password_problem(password)
        if p:
            raise ValueError(p)
        salt = secrets.token_bytes(16)
        ts = now_utc()
        self.db.execute(
            "INSERT INTO users(username, full_name, role, pw_hash, salt, must_change, created_at, created_by, pw_changed_at)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (username, full_name, role, _hash_password(password, salt), salt.hex(), int(must_change), ts, by, ts))
        self.db.commit()
        self.log(by, "USER_CREATED", username, {"full_name": full_name, "role": role})
        return self.get(username)

    def update_user(self, by: str, username: str, full_name: str, role: str, active: bool):
        old = self.get(username)
        if old is None:
            raise ValueError("no_user")
        if old.role == ROLE_ADMIN and (role != ROLE_ADMIN or not active):
            admins = [u for u in self.users() if u.role == ROLE_ADMIN and u.active]
            if len(admins) <= 1:
                raise ValueError("last_admin")
        self.db.execute("UPDATE users SET full_name=?, role=?, active=? WHERE username=?",
                        (full_name, role, int(active), username))
        self.db.commit()
        changes = {}
        if old.full_name != full_name:
            changes["full_name"] = [old.full_name, full_name]
        if old.role != role:
            changes["role"] = [old.role, role]
        if old.active != active:
            changes["active"] = [old.active, active]
        if changes:
            self.log(by, "USER_MODIFIED", username, changes)

    def reset_password(self, by: str, username: str, new_password: str):
        p = password_problem(new_password)
        if p:
            raise ValueError(p)
        salt = secrets.token_bytes(16)
        self.db.execute("UPDATE users SET pw_hash=?, salt=?, must_change=1, failed=0, locked=0, pw_changed_at=?"
                        " WHERE username=?", (_hash_password(new_password, salt), salt.hex(), now_utc(), username))
        self.db.commit()
        self.log(by, "PASSWORD_RESET", username, {})

    def unlock(self, by: str, username: str):
        self.db.execute("UPDATE users SET locked=0, failed=0 WHERE username=?", (username,))
        self.db.commit()
        self.log(by, "USER_UNLOCKED", username, {})

    def change_password(self, username: str, old_password: str, new_password: str):
        self.authenticate(username, old_password, log_success=False)
        if old_password == new_password:
            raise ValueError("pw_same")
        p = password_problem(new_password)
        if p:
            raise ValueError(p)
        salt = secrets.token_bytes(16)
        self.db.execute("UPDATE users SET pw_hash=?, salt=?, must_change=0, pw_changed_at=? WHERE username=?",
                        (_hash_password(new_password, salt), salt.hex(), now_utc(), username))
        self.db.commit()
        self.log(username, "PASSWORD_CHANGED", username, {})

    def authenticate(self, username: str, password: str, log_success=True) -> User:
        r = self.db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if r is None:
            self.log(username or "?", "LOGIN_FAILED", username, {"reason": "unknown user"})
            raise AuthError("bad_login")
        u = self._row_to_user(r)
        if not u.active:
            self.log(u.username, "LOGIN_FAILED", u.username, {"reason": "inactive"})
            raise AuthError("inactive")
        if u.locked:
            self.log(u.username, "LOGIN_FAILED", u.username, {"reason": "locked"})
            raise AuthError("locked")
        ok = hmac.compare_digest(_hash_password(password, bytes.fromhex(r["salt"])), r["pw_hash"])
        if not ok:
            failed = u.failed + 1
            locked = failed >= MAX_FAILED
            self.db.execute("UPDATE users SET failed=?, locked=? WHERE username=?", (failed, int(locked), u.username))
            self.db.commit()
            self.log(u.username, "LOGIN_FAILED", u.username, {"reason": "wrong password", "attempt": failed})
            if locked:
                self.log(u.username, "USER_LOCKED", u.username, {"after_attempts": failed})
                raise AuthError("locked")
            raise AuthError("bad_login")
        if log_success:
            self.db.execute("UPDATE users SET failed=0, last_login=? WHERE username=?", (now_utc(), u.username))
            self.db.commit()
            self.log(u.username, "LOGIN", u.username, {})
        return self.get(u.username)

    # ------------------------------------------------------------------ audit
    def log(self, username: str, action: str, target: str = "", details=None):
        if details is None:
            details = {}
        det = details if isinstance(details, str) else json.dumps(details, ensure_ascii=False, sort_keys=True)
        ts = now_utc()
        prev = self.db.execute("SELECT hash FROM audit ORDER BY id DESC LIMIT 1").fetchone()
        prev_hash = prev[0] if prev else GENESIS
        h = self._record_hash(prev_hash, ts, username, action, target, det)
        self.db.execute("INSERT INTO audit(ts, username, action, target, details, prev_hash, hash)"
                        " VALUES(?,?,?,?,?,?,?)", (ts, username, action, target, det, prev_hash, h))
        self.db.commit()

    @staticmethod
    def _record_hash(prev_hash, ts, username, action, target, details) -> str:
        payload = "\x1f".join([prev_hash, ts, username, action, target, details])
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def records(self, username=None, action=None, text=None, date_from=None, date_to=None, limit=5000):
        q = "SELECT * FROM audit WHERE 1=1"
        args = []
        if username:
            q += " AND username=?"
            args.append(username)
        if action:
            q += " AND action=?"
            args.append(action)
        if text:
            q += " AND (target LIKE ? OR details LIKE ?)"
            args += [f"%{text}%", f"%{text}%"]
        if date_from:
            q += " AND ts>=?"
            args.append(date_from)
        if date_to:
            q += " AND ts<=?"
            args.append(date_to + " 99")
        q += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        return [dict(r) for r in self.db.execute(q, args)]

    def actions(self) -> List[str]:
        return [r[0] for r in self.db.execute("SELECT DISTINCT action FROM audit ORDER BY action")]

    def verify(self):
        """Return (ok, number_of_records, first_bad_id)."""
        prev = GENESIS
        n = 0
        for r in self.db.execute("SELECT * FROM audit ORDER BY id"):
            n += 1
            if r["prev_hash"] != prev:
                return False, n, r["id"]
            h = self._record_hash(r["prev_hash"], r["ts"], r["username"], r["action"], r["target"], r["details"])
            if h != r["hash"]:
                return False, n, r["id"]
            prev = r["hash"]
        return True, n, None

    def export_csv(self, path: str, rows=None):
        rows = rows if rows is not None else self.records(limit=10 ** 9)
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["id", "timestamp", "user", "action", "target", "details", "hash"])
            for r in rows:
                w.writerow([r["id"], r["ts"], r["username"], r["action"], r["target"], r["details"], r["hash"]])
