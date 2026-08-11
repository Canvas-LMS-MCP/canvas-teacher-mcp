"""canvas_rest.submissions — undo Canvas missing-policy auto-zeros on ONE assignment.

Why this exists: an assignment copied from a previous term carries that term's due date. The
moment it is published, Canvas's missing-submission policy sees a past due date with no
submission and stamps a 0 on every student. Moving the due date forward does NOT remove those
zeros — Canvas never retracts a grade it has written — so a whole class ends up dragged down by
graded zeros on work that was never assigned yet.

Scope: ONE assignment id per call. There is no course-wide sweep, on purpose.

Safety invariant — a submission is touched ONLY when BOTH hold:
    score == 0  AND  submitted_at is None
A submission the student actually turned in is never touched, even if it scored 0: that is a
real grade. The guard takes no override argument. Canvas has no revisions API for grades, so a
wiped grade is unrecoverable except from the backup this module writes.

clear_auto_zeros is dry-run unless apply=True, and writes a restorable backup BEFORE the first
PUT; if the backup cannot be written, nothing is sent. restore_from_backup feeds it back.

Grade writes are gated by the post-gate hook (CourseGlobalWorkflow/GRADING.md).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .client import get
from .resources import post_submission_grade

# Captured before a clear so restore_from_backup can put the grade back.
_SNAPSHOT_FIELDS = (
    "score", "grade", "entered_score", "entered_grade", "workflow_state",
    "graded_at", "grader_id", "late_policy_status", "missing", "excused",
)


def _is_auto_zero(sub) -> bool:
    """The only predicate that authorizes a clear. Both conditions required.

    score == 0        -> Canvas wrote a zero.
    submitted_at None -> the student never turned anything in, so the zero belongs to the
                         missing policy, not to a grader. A submitted-and-scored-0 is a real
                         grade and must survive.
    """
    return sub.get("score") == 0 and sub.get("submitted_at") is None


def find_auto_zeros(base_url, token, course_id, assignment_id):
    """Return the auto-zero submissions on `assignment_id`. Read-only.

    An empty list means the assignment is not in that state — "nothing to do", not an error.
    """
    subs = get(base_url, token,
               f"/courses/{course_id}/assignments/{assignment_id}/submissions",
               params={"per_page": 100})
    return [s for s in subs if _is_auto_zero(s)]


def _snapshot(base_url, course_id, assignment_id, targets) -> dict:
    return {
        "base_url": base_url,
        "course_id": course_id,
        "assignment_id": assignment_id,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "submissions": [
            {"user_id": s["user_id"], **{k: s.get(k) for k in _SNAPSHOT_FIELDS}}
            for s in targets
        ],
    }


def clear_auto_zeros(base_url, token, course_id, assignment_id, *,
                     apply=False, backup_path=None):
    """Blank the auto-zeros on ONE assignment. Dry-run unless apply=True.

    Returns (targets, results); results is [] in dry-run. With apply=True, `backup_path` is
    required: every target's prior state is written there first and a write failure aborts
    before any PUT. Submitted work never reaches the PUT loop (see `_is_auto_zero`).
    """
    targets = find_auto_zeros(base_url, token, course_id, assignment_id)
    if not apply or not targets:
        return targets, []

    if not backup_path:
        raise ValueError("apply=True requires backup_path — refusing to clear grades unbacked")

    p = Path(backup_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(_snapshot(base_url, course_id, assignment_id, targets), indent=2))
    if not p.exists() or p.stat().st_size == 0:
        raise RuntimeError(f"backup not written to {p} — nothing was cleared")

    results = []
    for s in targets:
        status, _ = post_submission_grade(base_url, token, course_id, assignment_id,
                                          s["user_id"], "")
        results.append({"user_id": s["user_id"], "status": status})
    return targets, results


def restore_from_backup(base_url, token, backup_path):
    """Re-post the scores captured by clear_auto_zeros."""
    data = json.loads(Path(backup_path).read_text())
    cid, aid = data["course_id"], data["assignment_id"]
    results = []
    for s in data["submissions"]:
        score = s.get("score")
        status, _ = post_submission_grade(base_url, token, cid, aid, s["user_id"],
                                          "" if score is None else score)
        results.append({"user_id": s["user_id"], "status": status, "restored_score": score})
    return results
