"""The GRADER CONTRACT — one shape every grader returns, enforced at the boundary.

WHY THIS EXISTS (2026-07-28). The engine is a 3-tier assembly: core.py (class-wide)
delegates to a grader, and a grader may itself be COMPOSITE and delegate again through
the same contract. That only holds if the contract is real. It was not: it lived as an
assumption in core.py's field reads, so a grader could omit a field and the engine would
carry on with a hole. Both of today's defects are that one bug:

  · `quiz.py` never returned `review_content` → core.py wrote an empty ground_truth →
    view_gate exploded zero evidence files → check() passes an empty manifest → a whole
    quiz could be POSTED with not one student answer read. Silent.
  · quiz's multi-attempt merge took `review_content` from the representative attempt
    only, so a student whose last attempt was blank produced no evidence at all. Silent.

Neither raised. Neither printed. The grade looked finished. That is the failure mode this
module exists to make impossible.

TWO CLASSES OF FIELD
  REQUIRED  — core.py reads it unconditionally (`out["raw"]`). Absence is a KeyError
              somewhere downstream; better to fail HERE, naming the grader.
  DECLARED  — optional to the type system but load-bearing for enforcement (evidence,
              instructor flags). Silence is the danger, not absence: a grader that
              produces no text evidence is fine, a grader that *should* and doesn't is a
              hole. So a grader DECLARES what it produces (module-level `PRODUCES`), and
              a declared-but-missing field is reported loudly instead of vanishing.

The validator never repairs. Filling a default here would be the same silent hole one
layer down — it raises (REQUIRED) or reports (DECLARED) and the caller decides.
"""

# core.py reads these with `out[...]` — no default, no guard.
REQUIRED = {
    "raw": (int, float),          # engine score for this unit
    "posted": (int, float),       # what would be posted (raw unless the grader adjusts)
    "scores": dict,               # per-rubric-key breakdown
    # NO comment field of ANY name. A grader does not author student-facing text:
    # `html_comment` (a Stage-A draft rendered by `lib/comment.py`) was REQUIRED here
    # until 2026-08-04 and read by NOBODY — core.py stored it as `comment_draft`, the
    # poster never looked at it. It was a SECOND comment renderer with none of
    # `comment_render`'s enforcement (it printed a below-max row with no reason and no
    # how-to-fix instead of raising `CommentError`), kept safe only by the convention
    # that nothing read the field. Both it and the module are deleted. The ONE renderer
    # is `lib/comment_render`, used by `report_generator` and the poster.
}

# Read with `.get()` by core.py, but each one drives a downstream mechanism. A grader
# lists in PRODUCES only what it genuinely emits; anything listed and then missing is a
# contract report (see `check`).
DECLARABLE = {
    "review_content",   # → core ground_truth → view_gate evidence files → POST GATE
    "needs_review",     # → report Section 0 "Engine-side issues"
    "attempts",         # → per-attempt posting (multi-attempt quizzes, Part D §2)
    "earned",           # → report_generator per-rubric columns
    "rubric_items",     # → report rubric table
    "authenticity",     # → commit server-time proctor flags
    "oversized_log",    # → Section 0 oversized-log notice
}

# PRODUCES means "emitted on EVERY normal grade", not "can emit". Declare only the
# unconditional fields. An exceptional one — gh's `oversized_log` (fires only when a log is
# too big), `authenticity` (only when a repo resolved) — is empty on almost every submission,
# so declaring it turns the check into noise the reader learns to skip, which is how a real
# missing field gets lost. Measured on A511: declaring `oversized_log` flagged 15 of 15
# students, all correct-to-be-empty.
#
# A grader that legitimately produces none of the above declares PRODUCES = frozenset().
# Absent PRODUCES = the module never declared itself → treated as UNDECLARED, which is a
# finding, not a pass. (Do not default it to "everything" or to "nothing": both guess.)
UNDECLARED = object()


class ContractError(TypeError):
    """A grader returned something core.py cannot consume. Names the grader."""


def produces(grader_module):
    """The set a grader declares it emits, or UNDECLARED. Never guesses."""
    p = getattr(grader_module, "PRODUCES", UNDECLARED)
    if p is UNDECLARED:
        return UNDECLARED
    return frozenset(p)


def check(out, grader_name, declared=UNDECLARED, graded=True):
    """Validate one grader return. Raises ContractError on a REQUIRED violation;
    returns a list of human-readable findings for DECLARED violations.

    `graded=False` (a STOP return) skips REQUIRED — a STOP legitimately carries no score.
    A STOP is itself part of the contract: {"stop": True, "stop_reason": str}.

    THREE return shapes, not two (found by this checker on 2026-07-28, which is the point of
    having it): a full grade, a STOP, and a NOTHING-TO-GRADE — the student who never submitted.
    The third scored 0 with no evidence and no attempts and had never been named anywhere, so
    it read as three graders dropping three declared fields. It is a real, correct outcome, so
    it gets a name (`nothing_to_grade`) rather than an exemption: declared fields are not
    expected, REQUIRED ones still are (the 0 and the comment are what get posted).
    """
    if not isinstance(out, dict):
        raise ContractError(f"grader '{grader_name}' returned {type(out).__name__}, not a dict")

    if out.get("stop"):
        if not str(out.get("stop_reason") or "").strip():
            raise ContractError(
                f"grader '{grader_name}' returned stop=True with no stop_reason — "
                f"a STOP must say why (it lands in report Section 0 verbatim)")
        return []

    if out.get("nothing_to_grade") or out.get("stub"):
        declared = frozenset()   # REQUIRED still enforced below; nothing was gathered to declare

    if graded:
        for key, typ in REQUIRED.items():
            if key not in out:
                raise ContractError(
                    f"grader '{grader_name}' omitted REQUIRED '{key}' — core.py reads it "
                    f"unconditionally; the run would fail (or worse, half-succeed) later")
            if out[key] is None or not isinstance(out[key], typ):
                names = getattr(typ, "__name__", None) or "/".join(t.__name__ for t in typ)
                raise ContractError(
                    f"grader '{grader_name}' returned '{key}'={out[key]!r} "
                    f"({type(out[key]).__name__}), expected {names}")

    findings = []
    if declared is UNDECLARED:
        findings.append(
            f"grader '{grader_name}' declares no PRODUCES — the engine cannot tell an "
            f"intentionally-empty field from a dropped one (this is exactly how quiz.py "
            f"lost review_content and switched the view-gate off)")
        return findings

    for key in sorted(declared):
        if key not in DECLARABLE:
            findings.append(f"grader '{grader_name}' declares unknown field '{key}'")
            continue
        val = out.get(key)
        if val is None or (hasattr(val, "__len__") and len(val) == 0):
            findings.append(
                f"grader '{grader_name}' declares it produces '{key}' but returned "
                f"{'nothing' if val is None else 'empty'} — if that is correct for this "
                f"submission say so in needs_review; do not let it pass silently")
    return findings
