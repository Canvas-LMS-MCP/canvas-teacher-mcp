"""Classify each Canvas submission as ✅ already graded / 🔄 re-submitted / 🆕 new / ❌ no-submit.

Authoritative rule:
- workflow_state == 'unsubmitted'  → 'nosubmit'
- graded_at + submitted_at present AND submitted_at > graded_at + 60s → 'resubmit' (re-graded later)
    …UNLESS the earlier "grade" is a MISSING-POLICY AUTO-ZERO → 'new' (a late FIRST submission)
- workflow_state == 'graded' AND graded_at present                   → 'graded' (SKIP — never touch)
    …same exception: an auto-zero on a submitted row is not a grade → 'new'
- otherwise (submitted but not graded)                               → 'new'

THE AUTO-ZERO IS THE TRAP. Canvas stamps score 0 + graded_at + workflow_state 'graded' on every
missing submission at the due date. Nothing about that row says "nobody graded me", so a late
submission on top of it reads as a re-submission — and the two are graded by OPPOSITE rules
(a resubmission is floored at its earlier grade and keeps the first submission's late anchor;
a late first submission has neither). `_auto_zero` separates them by `grader_id`: a person has
one, the policy does not.

DO NOT use score>0 / instructor-comment heuristics — those mis-classify ✅ as 🆕 and risk
overwriting already-posted grades when the JSON is later posted by the canonical poster.
"""
from datetime import datetime, timezone, timedelta


def _parse_iso(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        return None


def _auto_zero(submission):
    """True when the 0 on this row was stamped by Canvas' MISSING policy, not by a person.

    The distinguishing mark is the grader: Canvas records no `grader_id` (or a non-positive one)
    for a policy-applied zero, while any human grade carries the grader's user id. `missing` is
    accepted as a second signal for the same state. Score alone can never decide this — see
    `skills/grade/SKILL.md`: "a 0 may be a REAL grade OR an ungraded placeholder".
    """
    score = submission.get("score")
    if score not in (0, 0.0):
        return False
    grader = submission.get("grader_id")
    return (grader is None or (isinstance(grader, (int, float)) and grader <= 0)
            or bool(submission.get("missing")))


def classify(submission):
    """Return one of: 'graded', 'resubmit', 'new', 'nosubmit'."""
    wf = submission.get("workflow_state")
    if wf == "unsubmitted":
        return "nosubmit"
    graded_at = _parse_iso(submission.get("graded_at"))
    submitted_at = _parse_iso(submission.get("submitted_at"))
    if graded_at and submitted_at and submitted_at > graded_at + timedelta(seconds=60):
        # ⚠ AN AUTO-ZERO IS NOT A FIRST GRADE, so what follows it is not a RE-submission.
        # Canvas' missing policy stamps score 0 + graded_at at the due date on anyone who has
        # not submitted. When that student submits late, `submitted_at > graded_at` holds and
        # this looked like a resubmission — which is a different assignment: a resubmission
        # keeps the FIRST submission's late anchor and may never lower the earlier grade, while
        # this student has no earlier grade at all and is simply late. Grading them as
        # resubmissions floors every one of them against a 0 that no human ever awarded.
        # `grader_id` is what separates them: a human grader has a positive id, the missing
        # policy does not (null / <= 0). Measured 2026-08-02: 42 late first submissions across
        # 25 assignments were all classified `resubmit` before this check existed.
        if _auto_zero(submission):
            return "new"
        return "resubmit"
    if wf == "graded" and graded_at:
        # A real instructor grade → SKIP. BUT Canvas also stamps wf='graded' + graded_at when it
        # AUTO-assigns a 0 for a MISSING submission at the due date — that is NOT a grade. If the
        # student actually submitted and the grade does NOT match the current submission, the auto-0
        # is stale → this student still needs grading (do not let the placeholder 0 swallow them).
        if submitted_at and submission.get("grade_matches_current_submission") is False:
            return "new"
        if submitted_at and _auto_zero(submission):
            return "new"          # submitted, but the only "grade" is the missing-policy zero
        return "graded"
    return "new"


def classify_all(submissions):
    """Return dict {bucket: [submission, ...]} sorted by user.sortable_name."""
    buckets = {"graded": [], "resubmit": [], "new": [], "nosubmit": []}
    sorted_subs = sorted(
        submissions or [],
        key=lambda s: ((s.get("user") or {}).get("sortable_name") or "Z, ?").lower(),
    )
    for s in sorted_subs:
        buckets[classify(s)].append(s)
    return buckets
