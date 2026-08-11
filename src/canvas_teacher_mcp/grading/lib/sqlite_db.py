"""SQLite read-only helpers for the grade engine.

SCOPE (post DB-redesign, 2026-06): the DB stores ONLY data Canvas does NOT have
and that cannot be derived live — per-student **accommodations** and **late-policy
waivers**. Everything Canvas/GitHub LIVE (assignment ids/names/dues, student
names/sids/emails, repos, scores, attempt counts) is NOT stored here; it is fetched
live every run (caching it caused stale-mismatch bugs).

The engine NEVER writes to the DB (read-only). Tables it reads:
  • students(uid, accommodation, notes)         — instructor accommodations (DSP/EOPS)
  • late_waivers(canvas_id, uid, grace_until, reason) — instructor late-policy grants
    (keyed by Canvas assignment id + uid — stable keys, never the `code` label)
"""
import sqlite3


def open_db(path):
    """Open the project's SQLite DB read-only. Returns None if path is empty/missing."""
    if not path:
        return None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        return conn
    except Exception:  # noqa: BLE001
        return None


def get_student(db, uid):
    """Return the instructor-maintained, Canvas-ABSENT fields {accommodation, notes}
    for a student — or None.

    Name / sid / email are Canvas LIVE data and are intentionally NOT read here (the
    DB no longer stores them). uid is the Canvas key."""
    if not db or uid is None:
        return None
    try:
        row = db.execute(
            "SELECT accommodation, notes FROM students WHERE uid=?", (uid,)
        ).fetchone()
    except Exception:  # noqa: BLE001
        return None
    if not row:
        return None
    return {"accommodation": row[0], "notes": row[1]}


def get_late_waiver(db, canvas_id, uid):
    """Return dict {grace_until, reason} or None — an instructor-granted late waiver.

    Keyed by the **Canvas assignment id** (the stable Canvas key) + uid — NOT the
    engine's internal `code` label."""
    if not db or uid is None or not canvas_id:
        return None
    try:
        row = db.execute(
            "SELECT grace_until, reason FROM late_waivers WHERE canvas_id=? AND uid=?",
            (canvas_id, uid),
        ).fetchone()
    except Exception:  # noqa: BLE001
        return None
    if not row:
        return None
    return {"grace_until": row[0], "reason": row[1]}
