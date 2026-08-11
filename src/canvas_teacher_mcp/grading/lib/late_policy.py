"""Late policy resolver.

Hierarchy (first hit wins):
  1. `late_waivers` table — per (code, uid). If sa <= grace_until → late_policy=none
     (no penalty). If sa > grace_until → late_policy=late, seconds_late_override =
     (sa - grace_until).
  2. EOPS / DSP from `students.accommodation` → 7-day grace.
  3. `default_grace_days` — supplied BY THE CALLER at grading time. Not a stored setting.

Quizzes / exams (Q-type, E-type) get NO grace regardless — caller must pass
`grace_days=0` for those.

GRACE COMES FROM THE RUN, NOT FROM A FILE (2026-07-28). It used to be
`expected_late_grace_days` hand-written into each course json, and a term-wide blanket
waiver was a 4th path reading `term_exceptions_path` — also hand-written, and only into
3 of 9 course files, so six courses had that feature silently switched off by omission.
Both were deleted with the old `grade_engine/config/` dir: a grace day is a decision the
instructor makes for a particular run, not a coordinate of the course. The caller passes
it; this module never reads a file to find one. (GRADING.md §470 still marks the whole
grace/waiver hierarchy [TBD] — all the more reason not to freeze it into config.)

A term-wide waiver is now expressed the same way as any other: the instructor passes the
grace for that run, or writes `late_waivers` rows. There is no separate blanket path.

NOT in this module:
  - Interpreting student comments for extension requests. Comment semantics are
    not keyword-matched here. The engine surfaces every student comment in the
    grading report (Section 1); the instructor reads and, if an extension is
    approved, INSERTs a row into `late_waivers` (code, uid, grace_until, reason)
    — and the next engine run picks it up via path #1.
"""
from datetime import datetime, timezone


def _parse(iso):
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:  # noqa: BLE001
        return None


def compute_late(
    *,
    code,
    uid,
    submitted_at,
    due_at,
    default_grace_days,     # from the RUN (CLI), never from a config file — see module docstring
    db=None,
    canvas_id=None,         # Canvas assignment id — the key for late_waivers (not `code`)
    student_comments=None,  # accepted for future use; not interpreted here
):
    """Return dict:

      {
        'late':           bool,
        'days_late':      float,
        'late_policy':    'none' | 'late' | None,   # what to PUT to Canvas
        'seconds_late_override': int | None,
        'reason':         str,                      # human-readable why
      }

    `late_policy='none'` waives penalty (and `seconds_late_override` is unused).
    `late_policy='late'` with `seconds_late_override` charges only the excess.
    """
    sa = _parse(submitted_at)
    da = _parse(due_at)
    if not sa or not da or sa <= da:
        return {
            "late": False,
            "days_late": 0.0,
            "late_policy": None,
            "seconds_late_override": None,
            "reason": "",
        }

    days_late = (sa - da).total_seconds() / 86400.0

    # 1. Per-asmt waiver in DB
    if db is not None:
        from .sqlite_db import get_late_waiver

        w = get_late_waiver(db, canvas_id, uid)
        if w:
            grace_until = _parse(w["grace_until"])
            if grace_until and sa <= grace_until:
                return {
                    "late": True,
                    "days_late": days_late,
                    "late_policy": "none",
                    "seconds_late_override": None,
                    "reason": f"late_waivers: {w.get('reason') or 'waived'}",
                }
            if grace_until and sa > grace_until:
                excess = int((sa - grace_until).total_seconds())
                return {
                    "late": True,
                    "days_late": days_late,
                    "late_policy": "late",
                    "seconds_late_override": excess,
                    "reason": f"late_waivers grace exceeded: {w.get('reason') or ''}",
                }

    # 2. EOPS / DSP accommodation → 7 days
    grace_days = default_grace_days
    if db is not None:
        from .sqlite_db import get_student

        st = get_student(db, uid)
        if st and st.get("accommodation"):
            accom = (st["accommodation"] or "").upper()
            if accom in ("EOPS", "DSP", "EOPS/DSP", "DSPS"):
                grace_days = max(grace_days, 7)

    # 3. Apply grace
    if days_late <= grace_days:
        return {
            "late": True,
            "days_late": days_late,
            "late_policy": "none",
            "seconds_late_override": None,
            "reason": f"within {grace_days}-day grace",
        }
    excess_sec = int((days_late - grace_days) * 86400)
    return {
        "late": True,
        "days_late": days_late,
        "late_policy": "late",
        "seconds_late_override": excess_sec,
        "reason": f"{grace_days}-day grace exceeded by {(days_late - grace_days):.1f} days",
    }
