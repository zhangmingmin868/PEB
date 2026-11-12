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
    ROLE_ADMIN: {"edit_data", "maintenance", "manage_users", "view_audit", "templates", "print", "export",
                 "sign_performed", "sign_reviewed", "sign_approved", "modules", "methods", "instruments",
                 "policies", "data_management"},
    ROLE_ANALYST: {"edit_data", "print", "export", "sign_performed", "methods"},
    ROLE_REVIEWER: {"view_audit", "print", "export", "sign_reviewed", "sign_approved"},
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


# ---------------------------------------------------------------- policies
# Configurable by an administrator (System > Policy); every change is audited.
DEFAULT_POLICY = {
    "pw_min_len": 8,            # minimum password length
    "pw_expiry_days": 180,      # 0 = never expires
    "pw_complexity": 0,         # 1 = 3 of 4: upper, lower, digit, symbol
    "pw_history": 3,            # new password must differ from the last N
    "max_failed": MAX_FAILED,   # failed log-ins before the account is locked
    "lock_minutes": 15,         # 0 = only an administrator can unlock
    "session_timeout_min": 15,  # inactivity lock (0 = off)
    "esign_reason_required": 1, # signature meaning/comment required
    "esign_separate_reviewer": 1,  # performer may not review / approve the same record
    "report_requires_review": 1,   # reports must be reviewed before approval
}
POLICY_INT_KEYS = set(DEFAULT_POLICY)
_policy = dict(DEFAULT_POLICY)
_perm_override: dict = {}       # role -> set(perms) loaded from the database

ALL_PERMISSIONS = ["edit_data", "print", "export", "view_audit", "templates", "maintenance", "manage_users",
                   "sign_performed", "sign_reviewed", "sign_approved", "modules", "methods", "instruments",
                   "policies", "data_management"]


def policy(key: str) -> int:
    return int(_policy.get(key, DEFAULT_POLICY.get(key, 0)))


def password_problem(password: str) -> Optional[str]:
    """Return a problem key if the password does not meet the policy."""
    if len(password) < policy("pw_min_len"):
        return "pw_short"
    if policy("pw_complexity"):
        classes = sum([any(c.isupper() for c in password), any(c.islower() for c in password),
                       any(c.isdigit() for c in password), any(not c.isalnum() for c in password)])
        if classes < 3:
            return "pw_complex"
    elif not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
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
        return perm in role_permissions(self.role)


def role_permissions(role: str) -> set:
    if role in _perm_override:
        return set(_perm_override[role])
    return set(PERMISSIONS.get(role, set()))


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
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS role_perms(role TEXT PRIMARY KEY, perms TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS pw_history(
                id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL COLLATE NOCASE,
                pw_hash TEXT NOT NULL, salt TEXT NOT NULL, ts TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS records(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                module TEXT NOT NULL, path TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
                created_at TEXT NOT NULL, created_by TEXT NOT NULL,
                modified_at TEXT NOT NULL DEFAULT '', modified_by TEXT NOT NULL DEFAULT '',
                sha256 TEXT NOT NULL DEFAULT '', summary TEXT NOT NULL DEFAULT '');
            CREATE TABLE IF NOT EXISTS approvals(
                id INTEGER PRIMARY KEY AUTOINCREMENT, record_id INTEGER NOT NULL,
                meaning TEXT NOT NULL, username TEXT NOT NULL, full_name TEXT NOT NULL,
                ts TEXT NOT NULL, sha256 TEXT NOT NULL, comment TEXT NOT NULL DEFAULT '');
            CREATE TABLE IF NOT EXISTS methods(name TEXT PRIMARY KEY, data TEXT NOT NULL,
                modified_at TEXT NOT NULL, modified_by TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS instruments(
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, model TEXT NOT NULL DEFAULT '',
                sn TEXT NOT NULL DEFAULT '', tag TEXT NOT NULL DEFAULT '', valid_until TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '');
            CREATE TABLE IF NOT EXISTS test_runs(
                id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, instrument TEXT NOT NULL DEFAULT '',
                method TEXT NOT NULL DEFAULT '', sections TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT '',
                flow TEXT NOT NULL DEFAULT '', p1 TEXT NOT NULL DEFAULT '', flow_test TEXT NOT NULL DEFAULT '',
                leak_test TEXT NOT NULL DEFAULT '', operator TEXT NOT NULL DEFAULT '', data TEXT NOT NULL DEFAULT '');
            CREATE TRIGGER IF NOT EXISTS approvals_no_update BEFORE UPDATE ON approvals
                BEGIN SELECT RAISE(ABORT, 'signatures are read-only'); END;
            CREATE TRIGGER IF NOT EXISTS approvals_no_delete BEFORE DELETE ON approvals
                BEGIN SELECT RAISE(ABORT, 'signatures are read-only'); END;
            CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
                BEGIN SELECT RAISE(ABORT, 'audit trail is read-only'); END;
            CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
                BEGIN SELECT RAISE(ABORT, 'audit trail is read-only'); END;
            """
        )
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(users)")}
        if "locked_at" not in cols:
            self.db.execute("ALTER TABLE users ADD COLUMN locked_at TEXT NOT NULL DEFAULT ''")
        self.db.commit()
        self.load_policy()

    # ------------------------------------------------------------------ policy / permissions
    def load_policy(self):
        _policy.clear()
        _policy.update(DEFAULT_POLICY)
        for r in self.db.execute("SELECT key, value FROM settings"):
            if r["key"] in POLICY_INT_KEYS:
                try:
                    _policy[r["key"]] = int(r["value"])
                except ValueError:
                    pass
        _perm_override.clear()
        for r in self.db.execute("SELECT role, perms FROM role_perms"):
            _perm_override[r["role"]] = set(json.loads(r["perms"]))

    def set_policy(self, by: str, values: dict):
        changes = {}
        for k, v in values.items():
            if k not in POLICY_INT_KEYS:
                continue
            v = int(v)
            if policy(k) != v:
                changes[k] = [policy(k), v]
            self.db.execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?,?)", (k, str(v)))
        self.db.commit()
        self.load_policy()
        if changes:
            self.log(by, "POLICY_CHANGED", "policy", changes)
        return changes

    def set_role_permissions(self, by: str, role: str, perms):
        perms = set(perms) & set(ALL_PERMISSIONS)
        if role == ROLE_ADMIN:
            perms.add("manage_users")            # never lock everybody out of user management
        old = role_permissions(role)
        self.db.execute("INSERT OR REPLACE INTO role_perms(role, perms) VALUES(?,?)",
                        (role, json.dumps(sorted(perms))))
        self.db.commit()
        self.load_policy()
        added, removed = sorted(perms - old), sorted(old - perms)
        if added or removed:
            self.log(by, "PERMISSIONS_CHANGED", role, {"added": added, "removed": removed})

    def get_setting(self, key: str, default: str = "") -> str:
        r = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return r[0] if r else default

    def set_setting(self, by: str, key: str, value: str):
        old = self.get_setting(key, None)
        if old == value:
            return
        self.db.execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?,?)", (key, value))
        self.db.commit()
        self.log(by, "SETTING_CHANGED", key, {"old": old, "new": value})

    # ------------------------------------------------------------------ records registry
    def register_record(self, module: str, path: str, name: str, user: str, sha256: str, summary: str = ""):
        ts = now_utc()
        path = os.path.abspath(path)
        r = self.db.execute("SELECT id FROM records WHERE path=?", (path,)).fetchone()
        if r:
            self.db.execute("UPDATE records SET name=?, modified_at=?, modified_by=?, sha256=?, summary=? WHERE id=?",
                            (name, ts, user, sha256, summary, r[0]))
            rid = r[0]
        else:
            cur = self.db.execute("INSERT INTO records(module, path, name, created_at, created_by, modified_at,"
                                  " modified_by, sha256, summary) VALUES(?,?,?,?,?,?,?,?,?)",
                                  (module, path, name, ts, user, ts, user, sha256, summary))
            rid = cur.lastrowid
        self.db.commit()
        return rid

    def record_list(self, module: Optional[str] = None):
        q, a = "SELECT * FROM records", []
        if module:
            q += " WHERE module=?"
            a.append(module)
        return [dict(r) for r in self.db.execute(q + " ORDER BY id DESC", a)]

    def record(self, rid: int):
        r = self.db.execute("SELECT * FROM records WHERE id=?", (rid,)).fetchone()
        return dict(r) if r else None

    def record_by_path(self, path: str):
        r = self.db.execute("SELECT * FROM records WHERE path=?", (os.path.abspath(path),)).fetchone()
        return dict(r) if r else None

    def remove_record(self, by: str, rid: int):
        """Remove a record from the index only (the data file itself is kept)."""
        rec = self.record(rid)
        if rec:
            self.db.execute("DELETE FROM records WHERE id=?", (rid,))
            self.db.commit()
            self.log(by, "RECORD_REMOVED_FROM_LIST", rec["name"], {"path": rec["path"]})

    def add_approval(self, record_id: int, meaning: str, user: User, sha256: str, comment: str = ""):
        ts = now_utc()
        self.db.execute("INSERT INTO approvals(record_id, meaning, username, full_name, ts, sha256, comment)"
                        " VALUES(?,?,?,?,?,?,?)", (record_id, meaning, user.username, user.full_name, ts, sha256, comment))
        self.db.commit()
        return ts

    def approvals(self, record_id: int):
        return [dict(r) for r in self.db.execute("SELECT * FROM approvals WHERE record_id=? ORDER BY id", (record_id,))]

    # ------------------------------------------------------------------ methods / instruments
    def methods(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM methods ORDER BY name")]

    def save_method(self, by: str, name: str, data: dict, reason: str = ""):
        old = self.db.execute("SELECT data FROM methods WHERE name=?", (name,)).fetchone()
        old_d = json.loads(old[0]) if old else None
        self.db.execute("INSERT OR REPLACE INTO methods(name, data, modified_at, modified_by) VALUES(?,?,?,?)",
                        (name, json.dumps(data, ensure_ascii=False, sort_keys=True), now_utc(), by))
        self.db.commit()
        if old_d is None:
            self.log(by, "METHOD_CREATED", name, data)
        else:
            ch = {k: [old_d.get(k), v] for k, v in data.items() if old_d.get(k) != v}
            if ch:
                d = {"changes": ch}
                if reason:
                    d["reason"] = reason
                self.log(by, "METHOD_MODIFIED", name, d)

    def instruments(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM instruments ORDER BY id")]

    def save_instrument(self, by: str, data: dict, iid: Optional[int] = None):
        keys = ["name", "model", "sn", "tag", "valid_until", "notes"]
        vals = [str(data.get(k, "")) for k in keys]
        if iid is None:
            cur = self.db.execute(f"INSERT INTO instruments({','.join(keys)}) VALUES(?,?,?,?,?,?)", vals)
            self.db.commit()
            self.log(by, "INSTRUMENT_ADDED", data.get("name", ""), dict(zip(keys, vals)))
            return cur.lastrowid
        old = self.db.execute("SELECT * FROM instruments WHERE id=?", (iid,)).fetchone()
        self.db.execute(f"UPDATE instruments SET {','.join(k + '=?' for k in keys)} WHERE id=?", vals + [iid])
        self.db.commit()
        ch = {k: [old[k], v] for k, v in zip(keys, vals) if old and old[k] != v}
        if ch:
            self.log(by, "INSTRUMENT_MODIFIED", data.get("name", ""), ch)
        return iid

    def test_runs(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM test_runs ORDER BY id DESC")]

    def backup(self, by: str, dest: str):
        bk = sqlite3.connect(dest)
        with bk:
            self.db.backup(bk)
        bk.close()
        self.log(by, "DATABASE_BACKUP", os.path.basename(dest), {"path": dest})

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
        self.db.execute("UPDATE users SET locked=0, failed=0, locked_at='' WHERE username=?", (username,))
        self.db.commit()
        self.log(by, "USER_UNLOCKED", username, {})

    def change_password(self, username: str, old_password: str, new_password: str):
        self.authenticate(username, old_password, log_success=False)
        if old_password == new_password:
            raise ValueError("pw_same")
        p = password_problem(new_password)
        if p:
            raise ValueError(p)
        if self._in_history(username, new_password):
            raise ValueError("pw_history")
        self._push_history(username)
        salt = secrets.token_bytes(16)
        self.db.execute("UPDATE users SET pw_hash=?, salt=?, must_change=0, pw_changed_at=? WHERE username=?",
                        (_hash_password(new_password, salt), salt.hex(), now_utc(), username))
        self.db.commit()
        self.log(username, "PASSWORD_CHANGED", username, {})

    def _push_history(self, username):
        r = self.db.execute("SELECT pw_hash, salt FROM users WHERE username=?", (username,)).fetchone()
        if r:
            self.db.execute("INSERT INTO pw_history(username, pw_hash, salt, ts) VALUES(?,?,?,?)",
                            (username, r["pw_hash"], r["salt"], now_utc()))

    def _in_history(self, username, password) -> bool:
        n = policy("pw_history")
        if n <= 0:
            return False
        cur = self.db.execute("SELECT pw_hash, salt FROM users WHERE username=?", (username,)).fetchone()
        rows = [cur] if cur else []
        rows += list(self.db.execute("SELECT pw_hash, salt FROM pw_history WHERE username=? ORDER BY id DESC LIMIT ?",
                                     (username, n)))
        return any(hmac.compare_digest(_hash_password(password, bytes.fromhex(x["salt"])), x["pw_hash"]) for x in rows)

    def authenticate(self, username: str, password: str, log_success=True) -> User:
        r = self.db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if r is None:
            self.log(username or "?", "LOGIN_FAILED", username, {"reason": "unknown user"})
            raise AuthError("bad_login")
        u = self._row_to_user(r)
        if not u.active:
            self.log(u.username, "LOGIN_FAILED", u.username, {"reason": "inactive"})
            raise AuthError("inactive")
        if u.locked and policy("lock_minutes") > 0 and r["locked_at"]:
            try:
                t0 = _dt.datetime.strptime(r["locked_at"], "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=_dt.timezone.utc)
                if _dt.datetime.now(_dt.timezone.utc) - t0 >= _dt.timedelta(minutes=policy("lock_minutes")):
                    self.db.execute("UPDATE users SET locked=0, failed=0, locked_at='' WHERE username=?", (u.username,))
                    self.db.commit()
                    self.log("SYSTEM", "USER_UNLOCKED", u.username, {"reason": "lock time elapsed"})
                    u = self.get(u.username)
            except ValueError:
                pass
        if u.locked:
            self.log(u.username, "LOGIN_FAILED", u.username, {"reason": "locked"})
            raise AuthError("locked")
        ok = hmac.compare_digest(_hash_password(password, bytes.fromhex(r["salt"])), r["pw_hash"])
        if not ok:
            failed = u.failed + 1
            locked = failed >= policy("max_failed")
            self.db.execute("UPDATE users SET failed=?, locked=?, locked_at=? WHERE username=?",
                            (failed, int(locked), now_utc() if locked else "", u.username))
            self.db.commit()
            self.log(u.username, "LOGIN_FAILED", u.username, {"reason": "wrong password", "attempt": failed})
            if locked:
                self.log(u.username, "USER_LOCKED", u.username, {"after_attempts": failed})
                raise AuthError("locked")
            raise AuthError("bad_login")
        if log_success:
            days = policy("pw_expiry_days")
            if days > 0 and r["pw_changed_at"] and not u.must_change:
                try:
                    t0 = _dt.datetime.strptime(r["pw_changed_at"], "%Y-%m-%d %H:%M:%S UTC").replace(
                        tzinfo=_dt.timezone.utc)
                    if _dt.datetime.now(_dt.timezone.utc) - t0 > _dt.timedelta(days=days):
                        self.db.execute("UPDATE users SET must_change=1 WHERE username=?", (u.username,))
                        self.log("SYSTEM", "PASSWORD_EXPIRED", u.username, {"days": days})
                except ValueError:
                    pass
            self.db.execute("UPDATE users SET failed=0, last_login=? WHERE username=?", (now_utc(), u.username))
            self.db.commit()
            self.log(u.username, "LOGIN", u.username, {})
        return self.get(u.username)

    def verify_signature(self, username: str, password: str) -> User:
        """21 CFR 11.200(a): re-authenticate both signature components (user ID +
        password) at the time of signing.  Failures count towards the lock-out."""
        u = self.authenticate(username, password, log_success=False)
        self.db.execute("UPDATE users SET failed=0 WHERE username=?", (u.username,))
        self.db.commit()
        return u

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
