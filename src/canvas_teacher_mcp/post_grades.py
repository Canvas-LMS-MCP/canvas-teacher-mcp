"""Canonical grade poster — reads a grades.json and posts each student's final grade
+ pre-rendered comment to Canvas via the sanctioned canvas_rest.post_submission_grade.

PRINCIPLE: the poster is PURE TRANSIT. It NEVER builds a comment and NEVER decides
lateness — those are DATA in the grades.json (comment authored by the canonical
lib/comment_render; late status decided at grading time). This is what prevents the
"ad-hoc poster builds plain-text comments" bug (working_logs/jun-24-2026.md). There are
NO student ids / due dates / per-assignment values in this file — if you find yourself
adding one, it belongs in the grades.json instead.

grades.json schema (course-agnostic):
  { "school": "<school>",                    # -> Canvas-Auth/<school>.json for the token
    "canvas_base_url": "https://<school-domain>/api/v1",
    "course_id": int, "assignment_id": int,
    "quiz_id": int | null,                   # PRESENT -> QUIZ mode (per-question scoring, Part D)
    "quiz_question_id": int | null,          # the question id for a single-question quiz
    "students": [
      { "uid": int,
        "score": number,                     # final posted grade (raw; Canvas applies late policy)
        "question_scores": {qid: score}|null,# QUIZ multi-question: per-question map (else score->the one q)
        "comment": str | null,               # PRE-RENDERED by comment_render; transited as-is
        "late_policy_status": "none"|"late"|null,
        "seconds_late_override": int | null } ] }

QUIZ mode (Part D §1): CANVAS decides, not the JSON. The poster fetches the assignment and, if
`is_quiz_assignment`/`quiz_id`/`online_quiz`, writes the grade PER-QUESTION via
`quiz_submissions[][questions][qid][score]` (NEVER `posted_grade`, which leaves the quiz
`pending_review`; NEVER `fudge_points`) using the Canvas-supplied quiz_id, resolving the question
id from Canvas for a single-question quiz. The top-level `quiz_id`/`quiz_question_id` in grades.json
are an optional cross-check only; a mismatch with Canvas (or a quiz whose identity can't be resolved)
ABORTS — the poster never silently falls back to the assignment path. Comments still post to the
assignment submission. Non-quiz assignments run the `posted_grade` path.

COMMENT RULES — two lines, no case analysis:
  · DUPLICATE = a comment I (the token owner) already posted ON THIS ATTEMPT. Those are
    skipped. A resubmission is a NEW attempt, so its comment is not a duplicate — it posts,
    and the previous attempt's comment stays as that attempt's record.
  · DELETE = only when I MIS-GRADED and am replacing my own comment on the same attempt:
    run with `--fix`. Nothing else is ever deleted — not the student's, not a hand-typed
    instructor comment, not an earlier attempt's. Canvas comments cannot be edited and an
    HTML marker does not survive the API's flattened text, so the comment ID is recorded at
    post time in `<code>_posted_comments.json` (beside the grades.json) and `--fix` deletes
    exactly that id.

DRY-RUN by default; pass --post to write. Usage: post_grades.py <grades.json> [--post] [--fix]
"""
import sys, os, json
from datetime import datetime
from urllib.parse import urlparse

from .auth.session import CanvasSession   # credential-agnostic: token OR cookie, derived by school


# A follow-up teaching comment (stu["extra_comment"], PRE-RENDERED by comment_render.
# render_note) is posted as a SECOND submission comment, in ADDITION to the grade
# comment. Every such note contains this plain-text marker so a re-run can dedup it
# (Canvas comments are permanent) without touching the grade-comment dedup.
#
# ⚠ DEDUP IS BY COUNT, NOT BY A MARKER. Canvas returns `submission_comments[].comment` as a
# text-EXTRACTED, FLATTENED copy (Access/Canvas.md), so an HTML marker such as
# `<!-- extra-note -->` is STRIPPED and can never be found again — a marker-based check would
# silently re-post the note on every run (verified 2026-07-10). A prose marker would survive
# but only ever matched one particular note's wording.
#
# Rule instead: on a given attempt the grade comment is the FIRST token-owner comment and the
# extra note is the SECOND. So "the owner already has >= 2 comments on this attempt" means the
# extra note is already there. Conservative by construction: if the instructor added a comment
# by hand, we skip rather than duplicate (Canvas comments are permanent).
EXTRA_MIN_OWNER_COMMENTS = 2


def _put_grade(s, base, cid, aid, uid, score, comment, late, secs, attempt=None):
    """PUT the final grade (form-encoded submission fields). Returns status int."""
    data = {"submission[posted_grade]": score}
    if late is not None:
        data["submission[late_policy_status]"] = late
    if secs is not None:
        data["submission[seconds_late_override]"] = secs
    if comment:
        data["comment[text_comment]"] = comment
        # Attach the comment to the LATEST attempt explicitly. Canvas comments are PER-ATTEMPT;
        # without comment[attempt] the comment lands on Canvas's default attempt, which can be an
        # EARLIER version when the student resubmitted — so it shows on the wrong version in
        # SpeedGrader. We grade the latest attempt, so the comment must attach to it too.
        if attempt is not None:
            data["comment[attempt]"] = attempt
    return s.put(base + f"/courses/{cid}/assignments/{aid}/submissions/{uid}", data=data, csrf=True).status_code


def _put_comment(s, base, cid, aid, uid, comment, attempt=None):
    """PUT a comment-only submission update (adds a comment, no grade change)."""
    data = {"comment[text_comment]": comment}
    if attempt is not None:
        data["comment[attempt]"] = attempt   # target the latest attempt (see _put_grade)
    return s.put(base + f"/courses/{cid}/assignments/{aid}/submissions/{uid}",
                 data=data, csrf=True).status_code


def _put_quiz_scores(s, base, cid, quiz_id, qsid, attempt, question_scores, fudge=None):
    # NO LATE FIELDS HERE, BY DESIGN — do not add them.
    # An assignment has ONE submission time, so Canvas deducts once from the whole score, and
    # `_put_grade` passes `late_policy_status` for it. A quiz has one time PER ATTEMPT, which
    # Canvas cannot express: its late policy takes a single submission time and cannot deduct
    # differently per attempt. So the engine does it — each attempt is graded at its own
    # timestamp and its deduction is ALREADY INSIDE the question scores below (the quiz HOURS
    # commit-late tier; `GRADING.md` Part D, "Every attempt, graded on its own"). Adding a late
    # field would deduct twice for the same lateness. `grades_json` omits those fields for a
    # quiz for this reason — their absence is the decision, not an oversight.
    """PUT per-QUESTION scores for a quiz submission (GRADING Part D §1.1-1.2).

    A quiz total is computed by Canvas from the score written into EACH question of
    the quiz submission — setting `submission[posted_grade]` (the assignment path)
    leaves the quiz stuck at `workflow_state=pending_review`. So a quiz is scored on
    its question submission via this endpoint, form-encoded (Canvas.md [Request Body
    Format]). `question_scores` = {question_id: score}; the total is their sum.

    `fudge` is DATA transited from grades.json (the renderer sets it 0 for quizzes) —
    it is included in the SAME PUT as the question scores. We never GRADE via fudge
    (§1.3), but Canvas converts a mistaken `posted_grade` on a quiz into fudge_points;
    sending fudge=0 alongside the question score makes the total the question score
    alone and clears that stray fudge. The poster only transits the value, never decides it."""
    data = {"quiz_submissions[][attempt]": attempt}
    if fudge is not None:
        data["quiz_submissions[][fudge_points]"] = fudge
    for qqid, sc in question_scores.items():
        data[f"quiz_submissions[][questions][{qqid}][score]"] = sc
    return s.put(base + f"/courses/{cid}/quizzes/{quiz_id}/submissions/{qsid}",
                 data=data, csrf=True).status_code


def _status_ok(r):
    """True only when this student's PUT(s) all returned 2xx. A quiz writes one status per
    attempt (a list), an assignment one int; an exception leaves `error` instead. Used to
    decide the artifact's `result` — which must never be assumed successful."""
    if r.get("error"):
        return False
    st = r.get("status_code", r.get("quiz_status_code"))
    codes = st if isinstance(st, list) else [st]
    return bool(codes) and all(isinstance(c, int) and 200 <= c < 300 for c in codes)


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    grades_path = argv[0]
    do_post = "--post" in argv
    # --fix = "this run corrects MY OWN mis-grade". It is the ONLY switch that deletes a
    # comment, and it deletes only the id this poster recorded for the CURRENT attempt.
    fix_mode = "--fix" in argv
    g = json.load(open(grades_path))
    # STAGE-A FILE IS NOT POSTABLE. `<code>_grades.json` is written twice per cycle: by the
    # engine (Stage A, `stage: "A"`, carries `comment_draft` — a reason-less engine draft
    # GRADING §4.5.4 forbids posting) and by report_generator (the post-ready render). Only
    # the second one may be posted; before the envelope existed, Stage A's bare list merely
    # crashed here by luck.
    if isinstance(g, list) or g.get("stage") == "A":
        print("ABORT: this is the STAGE-A engine output, not a post-ready grades.json. "
              "Stage B must judge and render it (report_generator) before anything is posted.",
              file=sys.stderr)
        return 2

    # ── VIEW-GATE (§0Z, MECHANICAL) ─────────────────────────────────────────────
    # Every artifact Stage A surfaced (answer_images/answer_docs, recorded in
    # <code>_view_manifest.json) MUST have been READ by the AI before we post. This is
    # the root fix for the M3Q7 disaster where the engine downloaded every drawing, the
    # AI never opened them, and docked "not re-VIEWED" — then posted. If any surfaced file
    # was never Read, the post ABORTS. No manifest => nothing was recorded to enforce (skip).
    #
    # THE MANIFEST PATH IS DATA, NOT A GUESS (2026-07-30). It used to be rebuilt here by
    # cutting the code out of the file name; a record under any other name produced a path
    # that did not exist, and "no manifest" meant "skip the gate" — so following a different
    # doc's naming turned the gate off, silently. Stage A now STAMPS `view_manifest` into the
    # record (grade_skill.py) and we read that field.
    # FAIL-CLOSED: no field = we cannot prove anything was recorded = ABORT. The fix is to
    # re-run Stage A, never to add a bypass ("skipping must be impossible" —
    # CourseGlobalWorkflow/GradingEngine/ViewGate.md).
    _gdir = os.path.dirname(os.path.abspath(grades_path))
    # PORTABLE PATHS (2026-08-06). `view_manifest` / `view_verified` are STORED values, folded to
    # `~/…` by the render so the same record reads on either Mac sharing this Drive folder
    # (CourseGlobalWorkflow/Local/Paths.md). Python does not expand `~`, so handing the stored
    # string straight to `os.path.exists` reported the manifest missing and blocked a post whose
    # evidence was sitting right there. Resolve on the way in — this also re-roots a path written
    # under another machine's home, which is why records made before the fold still post.
    from .grading.lib import paths as _paths
    _manifest = _paths.resolve(g.get("view_manifest"))
    if not _manifest:
        print("⛔ VIEW-GATE: this grades.json carries no `view_manifest` field, so there is no "
              "record of what you had to look at (§0Z). Re-run Stage A (grade_skill.py) to "
              "regenerate it, then post. Post blocked.")
        return 1
    if not os.path.exists(_manifest):
        print(f"⛔ VIEW-GATE: `view_manifest` points at a missing file: {_manifest}. "
              "Re-run Stage A. Post blocked.")
        return 1
    _man = json.load(open(_manifest))
    # The manifest names the grades.json it was built from — verify it is THIS one, so a
    # stale or another assignment's manifest can never stand in for the real evidence list.
    if (_man.get("grades_json")
            and os.path.realpath(_paths.resolve(_man["grades_json"])) != os.path.realpath(grades_path)):
        print(f"⛔ VIEW-GATE: manifest belongs to {_man['grades_json']}, not {grades_path}. "
              "Re-run Stage A for this assignment. Post blocked.")
        return 1
    from .grading.lib import view_gate
    _tr = None
    for _i, _a in enumerate(argv):
        if _a == "--transcript" and _i + 1 < len(argv):
            _tr = argv[_i + 1]
    _tr = _tr or view_gate.find_transcript(_gdir)   # derive the session dir from the grades.json location, not cwd
    _total = len(json.load(open(_manifest)).get("artifacts", []))

    # STORED PROOF FIRST (2026-08-01). The render freezes `<code>_view_verified.json` in the
    # session that actually did the reading, and stamps its path here. Without it, post-ready
    # expired with the conversation: a finished grading sitting on disk became unpostable the
    # moment the chat was cleared, because the Read calls lived in a transcript nobody was
    # looking at any more. The stored proof re-binds to THIS grades.json and THIS manifest
    # (check_verified re-verifies both), so it cannot be borrowed from another assignment.
    _verified = _paths.resolve(g.get("view_verified"))   # stored folded — see Local/Paths.md
    if _verified and os.path.exists(_verified):
        _unread = view_gate.check_verified(_manifest, _verified, grades_path)
        if not _unread:
            print(f"✓ view-gate: all {_total} surfaced artifact(s) verified from stored proof "
                  f"({os.path.basename(_verified)}).")
            _unread = []
            _tr = _tr or True          # transcript no longer required
        # falls through to the transcript path below if the stored proof is short/mismatched
    else:
        _unread = None

    if _unread is None or _unread:
        if not _tr or _tr is True:
            print("⛔ VIEW-GATE: session transcript not found and no valid stored proof — cannot "
                  f"verify you viewed the {_total} surfaced artifact(s). Pass "
                  "--transcript <session.jsonl>, or re-render in the session that read them. "
                  "Post blocked.")
            return 1
        _unread = view_gate.check(_manifest, _tr)
    if _unread:
        print(f"⛔ VIEW-GATE FAILED — {len(_unread)}/{_total} surfaced artifact(s) were NEVER "
              f"READ (§0Z). You are grading without looking:")
        for _p in _unread:
            print("   -", _p)
        print("Read each file above (the ENGINE-surfaced path, not a re-downloaded copy), "
              "then re-run. Post BLOCKED.")
        return 1
    print(f"✓ view-gate: all {_total} surfaced artifact(s) were viewed.")
    # ─────────────────────────────────────────────────────────────────────────────
    # Both come from the course config, carried in the grades.json. A default here would post
    # one school's grades to another school's Canvas, so a missing key stops the run.
    for _k in ("school", "canvas_base_url"):
        if not g.get(_k):
            print(f"⛔ grades.json has no `{_k}`. Re-run Stage A so the coordinates are written "
                  "from the course config. Post BLOCKED.")
            return 1
    school = g["school"]
    base = g["canvas_base_url"]
    cid, aid = g["course_id"], g["assignment_id"]
    s = CanvasSession(school, domain=urlparse(base).netloc)
    owner = (s.get(base + "/users/self").json() or {}).get("id")

    # DECISION — is this a QUIZ? CANVAS is the source of truth, NOT the grades.json.
    # (GRADING Part D §1.1) A quiz must be scored PER-QUESTION; posting `posted_grade` (the
    # assignment path) leaves it `pending_review`. The old logic decided solely on whether the
    # grades.json carried `quiz_id`, so a hand-authored JSON that omitted it silently fell to the
    # assignment path and mis-posted a real quiz (M2QP2/M2QP3, 2026-07-19). Now we ASK Canvas:
    # `GET /assignments/{aid}` returns `is_quiz_assignment` / `quiz_id` / submission_types. Canvas
    # decides (suspenders); the JSON's quiz_id is only a cross-check (belt). On any conflict, or a
    # quiz whose identity we can't resolve, we ABORT — we NEVER silently fall back.
    asmt = s.get(base + f"/courses/{cid}/assignments/{aid}").json() or {}
    canvas_is_quiz = bool(asmt.get("is_quiz_assignment")) or bool(asmt.get("quiz_id")) \
        or ("online_quiz" in (asmt.get("submission_types") or []))
    canvas_quiz_id = asmt.get("quiz_id")
    json_quiz_id = g.get("quiz_id")

    if canvas_is_quiz and not canvas_quiz_id:
        print(f"ABORT: Canvas says assignment {aid} is a quiz but returned no quiz_id.", file=sys.stderr)
        return 2
    if not canvas_is_quiz and json_quiz_id:
        print(f"ABORT: grades.json has quiz_id={json_quiz_id} but Canvas assignment {aid} is NOT a "
              f"quiz (is_quiz_assignment={asmt.get('is_quiz_assignment')}).", file=sys.stderr)
        return 2
    if canvas_is_quiz and json_quiz_id and int(json_quiz_id) != int(canvas_quiz_id):
        print(f"ABORT: quiz_id mismatch — grades.json={json_quiz_id}, Canvas={canvas_quiz_id}.", file=sys.stderr)
        return 2

    quiz_id = canvas_quiz_id if canvas_is_quiz else None
    if canvas_is_quiz and not json_quiz_id:
        print(f"WARN: grades.json missing quiz_id; using Canvas quiz_id={quiz_id} "
              f"(the renderer should inject it).", file=sys.stderr)

    # A QUIZ HAS EXACTLY ONE ACCEPTED SHAPE: per attempt × per question
    # (`attempts[{attempt, question_scores{qid: score}}]`) — Part D §1.1–§1.2 (Canvas builds the
    # total from each question's score) and §2.1–§2.2 (every attempt is graded on its own merits;
    # Canvas aggregates via the quiz's scoring_policy). A single-question quiz is the length-1
    # case of the same shape, not a special one.
    #
    # Two looser shapes were REMOVED 2026-07-29 because each could half-post silently:
    #   · student-level `question_scores` (no `attempts`) FLATTENS the attempts, so a 2-attempt
    #     student got one attempt scored and the other left ungraded.
    #   · resolving a `quiz_question_id` and dumping the student's TOTAL onto that one question
    #     is not per-question scoring at all — it is the fudge-by-another-name path (§1.3).
    # Anything but the accepted shape ABORTS here rather than posting part of a grade. Fix by
    # rendering through `report_generator` (it computes question_scores from the rubric's
    # `question_id` and refuses to render if the attempts are incomplete).
    qmap = {}
    if quiz_id:
        _bad = [stu.get("uid") for stu in g["students"]
                if not any(a.get("question_scores") for a in (stu.get("attempts") or []))]
        if _bad:
            print(f"ABORT: quiz {quiz_id} — {len(_bad)} student(s) carry no per-attempt "
                  f"`attempts[].question_scores`: {_bad}. A quiz posts per attempt × per question "
                  f"only (Part D §1–§2); re-render via report_generator.", file=sys.stderr)
            return 2
        qsubs = (s.get(base + f"/courses/{cid}/quizzes/{quiz_id}/submissions?per_page=100").json() or {})
        for x in (qsubs.get("quiz_submissions") or []):
            qmap[x["user_id"]] = {"qsid": x["id"], "attempt": x.get("attempt")}

    # ── COMMENT LEDGER — {uid: {attempt, comment_id, posted_at}} ────────────────────────
    # Written next to the grades.json (NOT inside it: Stage A rewrites grades.json on every
    # re-run, which would erase the ids exactly when a correction needs them). One rule it
    # serves: a comment is DELETED only when I mis-graded and am replacing my own comment on
    # the same attempt (`--fix`); nothing else is ever deleted.
    _code_label = g.get("code") or os.path.basename(grades_path).split("_")[0]
    ledger_path = os.path.join(_gdir, f"{_code_label}_posted_comments.json")
    ledger = json.load(open(ledger_path)) if os.path.exists(ledger_path) else {}

    print(f"=== post_grades ({'POST' if do_post else 'DRY-RUN'}"
          f"{' · FIX (replace my own comments)' if fix_mode else ''}) "
          f"course={cid} {'quiz='+str(quiz_id) if quiz_id else 'asmt='+str(aid)} "
          f"owner={owner} n={len(g['students'])} ===")
    results, skipped_dup, replaced = [], [], []
    for stu in g["students"]:
        uid, score = stu["uid"], stu["score"]
        late, secs = stu.get("late_policy_status"), stu.get("seconds_late_override")
        comment = stu.get("comment")
        sub = s.get(base + f"/courses/{cid}/assignments/{aid}/submissions/{uid}"
                           f"?include[]=submission_comments").json() or {}
        existing = sub.get("submission_comments") or []
        latest_attempt = sub.get("attempt")   # the submission's current (latest) attempt number
        # --fix: the ONLY case a comment is ever deleted — I mis-graded, so the wrong score's
        # comment goes with the wrong score. We delete BY RECORDED ID (ledger, below), so it is
        # provably the comment this poster wrote for THIS attempt: never the student's, never
        # the instructor's hand-typed one, never a previous attempt's (that one is the record of
        # that attempt and is kept).
        _rec = ledger.get(str(uid)) or {}
        _old_id = _rec.get("comment_id") if _rec.get("attempt") == latest_attempt else None
        if _old_id is None:
            # SECOND PROOF OF AUTHORSHIP, when the ledger cannot supply one (2026-08-02).
            # The ledger is written by the run that posts; it is gone the moment a grading is
            # re-done from a different session or directory, and then a corrected score sits
            # next to a comment stating the OLD score — the grade is right and the explanation
            # contradicts it. Seen twice now (the algo labs, and A54 here). The ledger was only
            # ever a way to PROVE we wrote the comment; it is not the only way.
            #   author = this token's account  AND  same attempt  AND  the body carries the
            #   engine's own "<code> Grade Breakdown" table.
            # A student's comment fails the author test. An instructor's hand-typed note fails
            # the marker test — nothing but comment_render emits that table. So the rule this
            # guards ("never delete a comment we did not write") is unchanged; only the way of
            # establishing it is widened.
            _old_id = next((c.get("id") for c in existing
                            if c.get("author_id") == owner
                            and c.get("attempt") == latest_attempt
                            and f"{_code_label} Grade Breakdown" in (c.get("comment") or "")),
                           None)
        fix_this = bool(fix_mode and comment and _old_id)
        # Dedup is PER-ATTEMPT, not global. A resubmission is a NEW attempt, so its comment is NOT a
        # duplicate of the prior attempt's comment — skipping it (the old global check) wrongly withheld
        # re-grade feedback. Skip only when the token-owner already commented ON THIS attempt (a true
        # re-run duplicate). Comments carry `attempt`; older comments posted without it (attempt=None)
        # never match the current attempt, so a re-grade comment always posts.
        dup = any(c.get("author_id") == owner and c.get("attempt") == latest_attempt for c in existing)
        if fix_this:
            dup = False          # not a duplicate — a CORRECTION of my own wrong comment
        cmt = None if dup else comment
        if dup and comment:
            skipped_dup.append(uid)
        # optional follow-up teaching note -> a SECOND comment (own marker-based dedup)
        extra = stu.get("extra_comment")
        owner_on_attempt = sum(1 for c in existing
                               if c.get("author_id") == owner and c.get("attempt") == latest_attempt)
        extra_dup = bool(extra) and owner_on_attempt >= EXTRA_MIN_OWNER_COMMENTS
        post_extra = bool(extra) and not extra_dup
        cstate = "omit(dup)" if (dup and comment) else ("REPLACE" if fix_this else
                                                        ("yes" if cmt else "none"))
        estate = "-" if not extra else ("omit(dup)" if extra_dup else "yes")
        print(f"--- {uid} score={score} late={late} comment={cstate} extra={estate}"
              + (f" (delete comment id={_old_id} first)" if fix_this else ""))
        if do_post:
            try:
                if fix_this:
                    _d = s.delete(base + f"/courses/{cid}/assignments/{aid}/submissions/{uid}"
                                         f"/comments/{_old_id}", csrf=True).status_code
                    print(f"    -> deleted my previous comment id={_old_id} HTTP {_d}")
                    replaced.append({"uid": uid, "deleted_comment_id": _old_id,
                                     "status_code": _d})
                if quiz_id:
                    q = qmap.get(uid)
                    if not q:
                        print("    -> NO quiz submission (skip)")
                        results.append({"uid": uid, "error": "no quiz submission"})
                        continue
                    # Part D §2: `attempts` carries one entry per attempt with its own
                    # question_scores — write EVERY one and let Canvas aggregate per the quiz's
                    # scoring_policy (keep_average/highest/latest). The grader never picks a
                    # winner. Single-attempt is a length-1 list; the guard above already proved
                    # every student has this shape, so there is no fallback to fall back to.
                    st = [_put_quiz_scores(s, base, cid, quiz_id, q["qsid"], a["attempt"],
                                           a["question_scores"], fudge=a.get("fudge_points"))
                          for a in stu["attempts"]]
                    st = st[0] if len(st) == 1 else st
                    cst = _put_comment(s, base, cid, aid, uid, cmt, attempt=latest_attempt) if cmt else None
                    est = _put_comment(s, base, cid, aid, uid, extra, attempt=latest_attempt) if post_extra else None
                    print(f"    -> quiz HTTP {st}"
                          + (f" · comment HTTP {cst}" if cst is not None else "")
                          + (f" · extra HTTP {est}" if est is not None else ""))
                    results.append({"uid": uid, "score": score, "quiz_status_code": st,
                                    "comment_posted": cst is not None,
                                    "extra_comment_posted": est is not None})
                else:
                    st = _put_grade(s, base, cid, aid, uid, score, cmt, late, secs, attempt=latest_attempt)
                    est = _put_comment(s, base, cid, aid, uid, extra, attempt=latest_attempt) if post_extra else None
                    print(f"    -> HTTP {st}" + (f" · extra HTTP {est}" if est is not None else ""))
                    results.append({"uid": uid, "score": score, "status_code": st,
                                    "comment_posted": cmt is not None,
                                    "extra_comment_posted": est is not None,
                                    "extra_status_code": est})
                if cmt:
                    # LEDGER — remember the id of the comment I just wrote, so a later
                    # correction (--fix) can delete exactly it. Canvas comments cannot be
                    # edited and carry no retrievable marker (an HTML marker is stripped out
                    # of the API's flattened `comment` text), so the id is the only handle
                    # that identifies MY comment on THIS attempt with certainty.
                    _after = (s.get(base + f"/courses/{cid}/assignments/{aid}/submissions/{uid}"
                                           f"?include[]=submission_comments").json() or {})
                    _mine = [c for c in (_after.get("submission_comments") or [])
                             if c.get("author_id") == owner and c.get("attempt") == latest_attempt]
                    if _mine:
                        ledger[str(uid)] = {"attempt": latest_attempt,
                                            "comment_id": _mine[-1].get("id"),
                                            "posted_at": datetime.now().isoformat(timespec="seconds")}
            except Exception as e:
                print(f"    -> ERROR {e}")
                results.append({"uid": uid, "error": str(e)[:160]})

    if do_post:
        # THE ARTIFACT IS THE PROOF, so it must be able to say NO (Discipline/Proof.md:
        # "if the artifact is missing, the phase did not happen"). `result` used to be the
        # constant "posted" — every PUT could 401 and the one file the instructor is told to
        # trust still read success. It is now DERIVED from the statuses actually returned.
        ok = [r for r in results if _status_ok(r)]
        errors = [{"uid": r.get("uid"),
                   "status_code": r.get("status_code", r.get("quiz_status_code")),
                   "error_text": r.get("error")}
                  for r in results if not _status_ok(r)]
        result = "posted" if (results and not errors) else ("partial" if ok else "fail")
        # The record lives in <output>/grade_result/json/, so QA_artifacts sits TWO levels up
        # (<output>/QA_artifacts) — the same home it has always had, reached from the record's
        # folder. One `..` would drop the evidence inside grade_result/ instead.
        art_dir = os.path.join(os.path.dirname(os.path.abspath(grades_path)), "..", "..", "QA_artifacts")
        os.makedirs(art_dir, exist_ok=True)
        # Naming convention: {Code}_grade-post_{YYYYMMDD-HHMM}.json (skills/grade/SKILL.md
        # ARTIFACT FILES). Timestamped, so a re-post never overwrites the earlier evidence.
        art = os.path.join(art_dir, "%s_grade-post_%s.json" % (
            g.get("code") or os.path.basename(grades_path).split("_")[0],
            datetime.now().strftime("%Y%m%d-%H%M")))
        with open(art, "w") as f:
            json.dump({"result": result, "posted": len(ok),
                       "students_posted": results,
                       "students_skipped_dup_comment": skipped_dup,
                       "comments_replaced": replaced,
                       "errors": errors}, f, indent=1, ensure_ascii=False)
        with open(ledger_path, "w") as f:      # ids of the comments this run wrote
            json.dump(ledger, f, indent=1, ensure_ascii=False)
        print(f"\nposted {len(ok)}/{len(results)} (dup-comment skipped: {len(skipped_dup)}"
              f"{', errors: %d' % len(errors) if errors else ''}) — artifact: {art}")
        print(f"phase=grade-post result={result} posted={len(ok)} artifact={art}")
        if errors:
            return 1
    else:
        print(f"\nDRY-RUN — nothing written. dup-comment would-skip: {len(skipped_dup)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
