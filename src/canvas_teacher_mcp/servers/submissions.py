"""Submission tools — wraps `rest/resources.py` and the grading library's classifier.

Read-only. Grades are written by the grading pipeline, never from here.
"""

from __future__ import annotations

from ..rest import resources
from . import _ctx

TOOLS = ("list_submissions", "get_submission", "classify_submissions", "get_rubric")


def _fetch(course: str, assignment_id: int) -> list[dict]:
    cfg = _ctx.config(course)
    return resources.fetch_submissions(
        cfg["canvas_base_url"], _ctx.credential(course), cfg["course_id"], assignment_id
    ) or []


def list_submissions(course: str, assignment_id: int) -> list[dict]:
    """Who submitted what: user id, submitted_at, current score, attempt count."""
    return [
        {"user_id": s.get("user_id"), "submitted_at": s.get("submitted_at"),
         "score": s.get("score"), "attempt": s.get("attempt"),
         "workflow_state": s.get("workflow_state"), "late": s.get("late")}
        for s in _fetch(course, assignment_id)
    ]


def get_submission(course: str, assignment_id: int, user_id: int) -> dict:
    """One submission in full, body and attachments included."""
    for s in _fetch(course, assignment_id):
        if s.get("user_id") == user_id:
            return s
    raise LookupError(f"no submission by user {user_id} on assignment {assignment_id}")


def classify_submissions(course: str, assignment_id: int) -> dict:
    """Split the submissions into graded / resubmitted / new / not submitted."""
    from ..grading.lib import classify

    buckets: dict[str, list[int]] = {}
    for s in _fetch(course, assignment_id):
        state = classify.classify(s) if hasattr(classify, "classify") else s.get("workflow_state")
        buckets.setdefault(str(state), []).append(s.get("user_id"))
    return buckets


def get_rubric(course: str, assignment_id: int) -> dict:
    """The assignment's Canvas rubric object, when it has one.

    The rubric a student was shown outranks this — an assignment page carries its own table.
    """
    cfg = _ctx.config(course)
    return resources.fetch_rubric(
        cfg["canvas_base_url"], _ctx.credential(course), cfg["course_id"], assignment_id
    )


def register(server) -> None:
    for fn in (list_submissions, get_submission, classify_submissions, get_rubric):
        server.add_tool(fn)
