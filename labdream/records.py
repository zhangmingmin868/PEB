"""Record index used by the Data / Report lists of the workstation.

Every APSD (.ldd) and PBE (.pbe) file saved by the program is registered here
with its SHA-256.  Approval status:

* PBE   – taken from the electronic signatures stored *inside* the file
          (bound to the content hash, see ``pbe.PbeStudy.valid_signatures``).
* APSD  – signatures are stored in the database ``approvals`` table, each
          bound to the SHA-256 of the file at the time of signing.  If the file
          is changed afterwards the signature no longer matches and the record
          falls back to "not reviewed" (signature invalidated).
"""
from __future__ import annotations

import hashlib
import os

from . import session

MOD_APSD, MOD_PBE = "APSD", "PBE"
ST_DRAFT, ST_PERFORMED, ST_REVIEWED, ST_APPROVED, ST_INVALID, ST_MISSING = (
    "draft", "performed", "reviewed", "approved", "invalid", "missing")
STATUS_TEXT = {ST_DRAFT: "Not reviewed", ST_PERFORMED: "Submitted", ST_REVIEWED: "Reviewed",
               ST_APPROVED: "Approved", ST_INVALID: "Signature invalidated", ST_MISSING: "File missing"}
STATUS_COLOR = {ST_DRAFT: "#fdf3d0", ST_PERFORMED: "#e3ecfb", ST_REVIEWED: "#dbeefa", ST_APPROVED: "#e3f1dc",
                ST_INVALID: "#f9dede", ST_MISSING: "#eeeeee"}


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def register(module: str, path: str, summary: str = ""):
    if session.store is None or not path:
        return None
    try:
        sha = file_sha256(path)
    except OSError:
        return None
    return session.store.register_record(module, path, os.path.basename(path), session.name(), sha, summary)


def status(rec: dict):
    """Return (status, [signature dicts: meaning, username, full_name, ts, valid])."""
    path = rec["path"]
    if not os.path.exists(path):
        return ST_MISSING, []
    if rec["module"] == MOD_PBE:
        from . import pbe
        try:
            st = pbe.load(path)
        except Exception:  # noqa: BLE001 – tampered / unreadable
            return ST_INVALID, []
        valid = {id(s) for s in st.valid_signatures()}
        sigs = [{"meaning": s.meaning, "username": s.username, "full_name": s.full_name, "ts": s.timestamp,
                 "valid": id(s) in valid, "comment": s.comment} for s in st.signatures]
    else:
        sha = file_sha256(path)
        sigs = [{"meaning": a["meaning"], "username": a["username"], "full_name": a["full_name"], "ts": a["ts"],
                 "valid": a["sha256"] == sha, "comment": a["comment"]}
                for a in session.store.approvals(rec["id"])]
    return _derive(sigs), sigs


def _derive(sigs):
    meanings = {s["meaning"] for s in sigs if s["valid"]}
    if "approved" in meanings:
        return ST_APPROVED
    if "reviewed" in meanings:
        return ST_REVIEWED
    if "performed" in meanings:
        return ST_PERFORMED
    if sigs:
        return ST_INVALID
    return ST_DRAFT


def last_signature(sigs):
    v = [s for s in sigs if s["valid"]]
    return v[-1] if v else None
