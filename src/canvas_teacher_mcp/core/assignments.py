"""canvas_core.assignments — CRUD for Canvas Assignments.

Python port of canvas_via_playwright/api/canvas_assignments.js. Uses canvas_auth
CanvasSession. create/update default published=False (Don't-Publish rule).

Common fields: name, description, points_possible, due_at (ISO-8601 UTC),
submission_types (list), grading_type, assignment_group_id, position.
"""
from __future__ import annotations

from ..auth.session import CanvasSession


def create(s: CanvasSession, course_id, *, published=False, **fields):
    """Create an assignment. Returns the created assignment dict."""
    r = s.post(f"/api/v1/courses/{course_id}/assignments",
               json={"assignment": {"published": published, **fields}}, csrf=True)
    r.raise_for_status()
    return r.json()


def read(s: CanvasSession, course_id, assignment_id):
    r = s.get(f"/api/v1/courses/{course_id}/assignments/{assignment_id}")
    r.raise_for_status()
    return r.json()


def list(s: CanvasSession, course_id, **params):
    """EVERY assignment — follows Canvas' `Link: rel="next"` to the end.

    It used to be a single GET, so a course with more than one page silently returned only the
    first 100 and everything downstream reasoned about a truncated course. Measured 2026-08-02:
    CSCI-19A returned exactly 100 rows, the chapter-5 EXAM (300 pts) was on page 2, and the
    grading queue built from this list reported it as not existing. A cut-off list is worse than
    an error because it looks like an answer.
    """
    # canvas_rest.client.get ALREADY walks `Link: rel="next"` and takes a CanvasSession just as
    # happily as a token string (`_auth_headers`). Writing a second page-walk here would be the
    # private-copy that code/README Rule #1 forbids — and the first version of this function did
    # exactly that before it was replaced.
    from ..rest.client import get as _rest_get
    return _rest_get(s.base, s, f"/api/v1/courses/{course_id}/assignments",
                     params=params or None)


def update(s: CanvasSession, course_id, assignment_id, **patch):
    r = s.put(f"/api/v1/courses/{course_id}/assignments/{assignment_id}",
              json={"assignment": patch}, csrf=True)
    r.raise_for_status()
    return r.json()


def remove(s: CanvasSession, course_id, assignment_id):
    r = s.delete(f"/api/v1/courses/{course_id}/assignments/{assignment_id}", csrf=True)
    r.raise_for_status()
    return r.json()


def needs_grading(s: CanvasSession, course_id, *, only_open=False):
    """The course's grading queue: every assignment that still holds ungraded work.

    `skills/grade/SKILL.md` names the Canvas needs-grading queue as the SOURCE OF TRUTH for what to
    grade, but nothing implemented the sweep, so the queue could only be read one assignment at
    a time (`grade_engine.lib.classify` does that, and needs the id up front). This is the step
    above it: ask Canvas which assignments are outstanding at all.

    Returns [{id, name, due_at, ungraded, published, is_quiz}] sorted by due date, newest last.
    `only_open=True` keeps just the rows with ungraded > 0.

    ⚠ `needs_grading_count` is unreliable for QUIZZES — a quiz sitting in `pending_review` keeps
    the count above zero even when a grade displays (`Access/Canvas.md`). Rows carry `is_quiz`
    so the caller can confirm those against the submissions themselves rather than the count.
    """
    rows = []
    for a in list(s, course_id, per_page=100, include=["needs_grading_count"]) or []:
        n = a.get("needs_grading_count") or 0
        if only_open and not n:
            continue
        rows.append({"id": a.get("id"), "name": a.get("name") or "",
                     "due_at": a.get("due_at"), "ungraded": n,
                     "published": bool(a.get("published")),
                     "is_quiz": bool(a.get("quiz_id") or "online_quiz"
                                     in (a.get("submission_types") or []))})
    return sorted(rows, key=lambda r: (r["due_at"] or "9999"))


def set_due_dates(s: CanvasSession, course_id, assignment_ids, due_at):
    """Set due_at on each assignment id (only due_at changes). Returns
    [{id, status, due_at, name}] — Python port of put_due_dates.kick.js.
    due_at = ISO-8601 UTC, e.g. '2026-07-20T06:59:00Z'."""
    out = []
    for aid in assignment_ids:
        try:
            a = update(s, course_id, aid, due_at=due_at)
            out.append({"id": aid, "status": 200, "due_at": a.get("due_at"),
                        "name": (a.get("name") or "")[:60]})
        except Exception as e:  # noqa: BLE001
            out.append({"id": aid, "error": str(e)})
    return out


def _main(argv):
    """CLI:  python3 -m canvas_core.assignments --course <slug> --needs-grading [--all]

    Read-only. Prints the grading queue in PDT (never raw UTC — account rule).
    """
    import argparse
    import sys
    sys.path.insert(0, __file__.rsplit("/", 2)[0])
    from .. import course_config
    from ..rest import timefmt

    p = argparse.ArgumentParser(prog="canvas_core.assignments")
    p.add_argument("--course", required=True, help="course slug")
    p.add_argument("--needs-grading", action="store_true", help="print the grading queue")
    p.add_argument("--all", action="store_true", help="include assignments with nothing ungraded")
    p.add_argument("--triage", action="store_true",
                   help="split each queued assignment into 🔄 resubmit / 🆕 new(late) — the two "
                        "need DIFFERENT rules, so this must be known before grading")
    a = p.parse_args(argv)
    if not (a.needs_grading or a.triage):
        p.error("nothing to do — pass --needs-grading or --triage")

    cfg = course_config.load(a.course)
    s = CanvasSession(cfg["school"], domain=cfg.get("domain"))
    rows = needs_grading(s, cfg["course_id"], only_open=not a.all)

    if a.triage:
        # WHY THIS SPLIT DECIDES THE RULES (grade skill, Step 3 re-grade checklist):
        #   🔄 resubmit → late is anchored to the FIRST submission, and the final score is
        #                 max(new, entered_score) — a re-grade may never lower a posted grade.
        #   🆕 new      → an ordinary late first submission: same rubric, check the waiver.
        # Grading them the same way silently re-penalises a resubmission for being late twice.
        from ..grading.lib import classify as _classify
        from ..rest import resources as _res
        # NAME THE STUDENTS, not just the counts. A count says work exists; it does not say who,
        # and every downstream step (`grade_skill --only <uid>`, the prior score to floor against)
        # needs the uid. A triage that has to be re-run to answer "which student" is half a tool.
        tot_r = tot_n = 0
        for r in rows:
            subs = _res.fetch_submissions(cfg["canvas_base_url"], s, cfg["course_id"], r["id"])
            b = _classify.classify_all(subs)
            nr, nn = len(b["resubmit"]), len(b["new"])
            tot_r += nr
            tot_n += nn
            due = timefmt.to_localtime(r["due_at"]) if r["due_at"] else "—"
            print(f"\n[{r['id']}] {r['name'][:60]}   due {str(due)[:18]}")
            for tag, key in (("🔄", "resubmit"), ("🆕", "new")):
                for sub in b[key]:
                    who = (sub.get("user") or {}).get("sortable_name") or "?"
                    print(f"   {tag} {sub.get('user_id'):<8} {who[:32]:<34}"
                          f"score={sub.get('score')}  submitted={sub.get('submitted_at')}")
        print(f"\n{len(rows)} assignment(s) — 🔄 resubmit {tot_r} · 🆕 new(late) {tot_n}")
        return 0
    if not rows:
        print("nothing ungraded — the queue is empty")
        return 0
    # THE ID IS PRINTED because the id is what the next step needs. Everything downstream is
    # driven by `grade_skill.py --canvas-id N`: `code` is the engine's internal label and is
    # explicitly NOT a Canvas key (`grade_engine.core._resolve_canvas_id`), so a queue that
    # names the work but withholds its id can be read and not acted on — you have to go back to
    # Canvas and hunt the same rows a second time to get the one column that matters.
    print(f"{'ID':<9}{'DUE (PDT)':<18}{'UNGRADED':>9}  {'PUB':<4}{'TYPE':<6}NAME")
    for r in rows:
        due = timefmt.to_localtime(r["due_at"]) if r["due_at"] else "—"
        print(f"{r['id']:<9}{str(due)[:18]:<18}{r['ungraded']:>9}  "
              f"{'y' if r['published'] else 'n':<4}"
              f"{'quiz' if r['is_quiz'] else 'asmt':<6}{r['name'][:56]}")
    print(f"\n{len(rows)} assignment(s), {sum(r['ungraded'] for r in rows)} ungraded submission(s)")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_main(sys.argv[1:]))
