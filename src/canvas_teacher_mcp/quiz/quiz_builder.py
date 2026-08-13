#!/usr/bin/env python3
"""quiz_builder — Classic Quizzes API machinery for the `quiz-builder` skill.

The ONE code the quiz-builder skill calls to create-or-update a Canvas CLASSIC quiz:
its question items + the description summary. NEVER hand-roll quiz API calls anywhere else —
this module is the single machinery (skill hard rule + gate). Idempotent: build a quiz's
questions from nothing OR update an existing quiz; each question is matched by its stable
`question_name` → update in place, else create.

Canvas gotchas baked in (CourseGlobalWorkflow/Access/Canvas.md [Quiz Question Updates]):
  - a question PUT/POST needs the FULL payload (question_type / points_possible /
    question_text / answers) or Canvas silently fails.
  - after ANY question change the parent quiz's question_count / points_possible go STALE →
    refresh_quiz() forces a refresh (PUT no-op).
  - `position` is IGNORED at the question endpoint → use reorder().

NEVER publishes — the instructor publishes. NEVER sets `published`.
Grading of a built quiz is a SEPARATE concern (per-question scores, NOT posted_grade —
Access/Canvas.md [Quiz Submission Scoring]); see the grade-git-program sub-skill.
"""
import os
import sys

# skills/quiz-builder/quiz_builder.py  ->  up two = .claude/ , then code/  => .claude/code
_CODE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "code"))
if _CODE not in sys.path:
    sys.path.insert(0, _CODE)

from .. import rest as canvas_rest  # noqa: E402  (the ONLY Canvas access — never raw HTTP here)

# The generated part of a description is fenced by these, so a rebuild replaces its own work and
# leaves the instructor's alone. Canvas keeps `data-` attributes; it strips `<style>` blocks, not
# these. Never change the opening string — a description written by an older version keeps it.
_SUMMARY_OPEN = '<div data-canvas-teacher="summary">'
_SUMMARY_CLOSE = '</div><!--/canvas-teacher-->'

_TD = 'style="border:1px solid #ccc;padding:6px 10px;"'
_TH = 'style="border:1px solid #ccc;padding:6px 10px;background-color:#1F3864;color:#fff;text-align:left;"'


# ── raw endpoints (thin wrappers over canvas_rest) ────────────────────────────────────────────
def _unwrap(resp):
    """canvas_rest.post/put/delete return (status, body) tuples (get returns the body directly).
    Raise on a non-2xx status so silent failures surface; return the response body."""
    if isinstance(resp, tuple):
        status, body = resp
        if not (200 <= status < 300):
            raise RuntimeError(f"Canvas quiz API HTTP {status}: {str(body)[:300]}")
        return body
    return resp


def fetch_quiz(base, token, course_id, quiz_id):
    return canvas_rest.get(base, token, f"/courses/{course_id}/quizzes/{quiz_id}", paginate=False)


def list_questions(base, token, course_id, quiz_id):
    return canvas_rest.get(base, token, f"/courses/{course_id}/quizzes/{quiz_id}/questions",
                           params=[("per_page", "100")]) or []


def create_question(base, token, course_id, quiz_id, q):
    return _unwrap(canvas_rest.post(base, token, f"/courses/{course_id}/quizzes/{quiz_id}/questions",
                                    {"question": q}))


def update_question(base, token, course_id, quiz_id, question_id, q):
    return _unwrap(canvas_rest.put(base, token,
                                   f"/courses/{course_id}/quizzes/{quiz_id}/questions/{question_id}",
                                   {"question": q}))


def delete_question(base, token, course_id, quiz_id, question_id):
    return _unwrap(canvas_rest.delete(base, token,
                                      f"/courses/{course_id}/quizzes/{quiz_id}/questions/{question_id}"))


def reorder(base, token, course_id, quiz_id, ordered_ids):
    """`position` is ignored at the question endpoint → set order here (Access/Canvas.md)."""
    order = [{"type": "question", "id": qid} for qid in ordered_ids if qid]
    return _unwrap(canvas_rest.post(base, token, f"/courses/{course_id}/quizzes/{quiz_id}/reorder",
                                    {"order": order}))


def refresh_quiz(base, token, course_id, quiz_id, title):
    """Bust the STALE question_count / points_possible cache after question changes."""
    return _unwrap(canvas_rest.put(base, token, f"/courses/{course_id}/quizzes/{quiz_id}",
                                   {"quiz": {"title": title, "notify_of_update": False}}))


def put_description(base, token, course_id, quiz_id, html, title=None):
    payload = {"quiz": {"description": html, "notify_of_update": False}}
    if title:
        payload["quiz"]["title"] = title
    return _unwrap(canvas_rest.put(base, token, f"/courses/{course_id}/quizzes/{quiz_id}", payload))


def create_quiz(base, token, course_id, *, title, description="", quiz_type="assignment",
                time_limit=None, allowed_attempts=1, assignment_group_id=None,
                due_at=None, shuffle_answers=False):
    """Create a NEW empty Classic quiz SHELL (the container `make_quiz` then fills with questions).
    This is the 'from nothing' entry — Canvas has no quiz yet, so make one first, then feed its `id`
    to `make_quiz`. NEVER sets `published` (the instructor publishes). Returns the created quiz dict.
    `due_at` = ISO-8601 UTC (e.g. '2026-07-13T06:59:00Z'); pass Pacific-local converted, per Canvas.md."""
    quiz = {"title": title, "description": description, "quiz_type": quiz_type,
            "allowed_attempts": allowed_attempts, "shuffle_answers": shuffle_answers}
    if time_limit is not None:
        quiz["time_limit"] = time_limit
    if assignment_group_id is not None:
        quiz["assignment_group_id"] = assignment_group_id
    if due_at is not None:
        quiz["due_at"] = due_at
    return _unwrap(canvas_rest.post(base, token, f"/courses/{course_id}/quizzes", {"quiz": quiz}))


def update_quiz(base, token, course_id, quiz_id, **fields):
    """Update quiz-level settings (title, time_limit, allowed_attempts, assignment_group_id, …).
    NEVER pass `published` — the instructor publishes. `notify_of_update` defaults False."""
    fields.setdefault("notify_of_update", False)
    return _unwrap(canvas_rest.put(base, token, f"/courses/{course_id}/quizzes/{quiz_id}", {"quiz": fields}))


# ── full-payload question helpers (a missing field silently fails — Access/Canvas.md) ────────
def q_multiple_choice(name, text_html, points, choices, correct_index):
    """choices = list[str]; correct_index = 0-based index of the correct choice."""
    answers = [{"answer_text": c, "answer_weight": (100 if i == correct_index else 0)}
               for i, c in enumerate(choices)]
    return {"question_name": name, "question_type": "multiple_choice_question",
            "question_text": text_html, "points_possible": points, "answers": answers}


def q_true_false(name, text_html, points, correct_true):
    answers = [{"answer_text": "True", "answer_weight": 100 if correct_true else 0},
               {"answer_text": "False", "answer_weight": 0 if correct_true else 100}]
    return {"question_name": name, "question_type": "true_false_question",
            "question_text": text_html, "points_possible": points, "answers": answers}


def q_multiple_answers(name, text_html, points, choices, correct_indexes):
    """choices = list[str]; correct_indexes = list of 0-based indexes that are ALL correct.

    Canvas `multiple_answers_question`: EVERY correct choice carries weight 100, the rest 0
    (there is no single 'correct_index'). The student must select all of them and none of the
    others. Used for publisher test-bank items whose key names several letters (`Key:cde`)."""
    correct = set(correct_indexes)
    answers = [{"answer_text": c, "answer_weight": (100 if i in correct else 0)}
               for i, c in enumerate(choices)]
    return {"question_name": name, "question_type": "multiple_answers_question",
            "question_text": text_html, "points_possible": points, "answers": answers}


def q_essay(name, text_html, points):
    """Essay / manually-graded. Used for a git-program question (the coding submission)."""
    return {"question_name": name, "question_type": "essay_question",
            "question_text": text_html, "points_possible": points, "answers": []}


# ── idempotent upsert (match by question_name) ─────────────────────────────────────────────────
class DuplicateQuestionNames(RuntimeError):
    """The quiz's own questions share a name, so name-keyed upsert would destroy items."""


def upsert_questions(base, token, course_id, quiz_id, questions):
    """Create-or-update each question keyed by `question_name`. Returns the resulting ids (in order).

    ⛔ REFUSES to run when the quiz's EXISTING questions share a `question_name`. The match is by
    name, so a bank whose 50 items are all called "Question" would have 49 of them overwritten by
    the 50th and the quiz would silently shrink to one. Rename the items first, or write only what
    you meant to change (`put_description` / `update_quiz` / `update_question` by id).
    (Hit 2026-08-02 on <course> quiz 373736 — 50 imported MCQs, every one named "Question".)
    """
    current = list_questions(base, token, course_id, quiz_id)
    seen, dupes = set(), set()
    for q in current:
        nm = q.get("question_name")
        (dupes.add(nm) if nm in seen else seen.add(nm))
    if dupes:
        raise DuplicateQuestionNames(
            "quiz %s has %d questions but duplicate question_name(s) %s — name-keyed upsert would "
            "DESTROY items. Rename them, or edit by id / write only the description."
            % (quiz_id, len(current), sorted(dupes)))
    existing = {q.get("question_name"): q for q in current}
    ids = []
    for q in questions:
        old = existing.get(q.get("question_name"))
        r = (update_question(base, token, course_id, quiz_id, old["id"], q) if old
             else create_question(base, token, course_id, quiz_id, q))
        ids.append((r or {}).get("id"))
    return ids


# ── description summary table (student-facing; computed from the questions, not the stale meta) ─
def build_description_summary(quiz_meta, questions, intro_html=""):
    n = len(questions)
    pts = sum((q.get("points_possible") or 0) for q in questions)
    tl = quiz_meta.get("time_limit")
    at = quiz_meta.get("allowed_attempts")
    # AUTO descriptive paragraph so the description is never a bare table. Structural facts come from
    # the questions + quiz settings (type, count, points-each, total, time, attempts, scoring policy);
    # the caller's intro_html adds the TOPIC (what the quiz is about). Result = auto + intro + table.
    def _g(x): return ("%g" % x)
    allmc = bool(n) and all("multiple_choice" in (q.get("question_type") or "") for q in questions)
    per = (pts / n) if n else 0
    auto = "<p>This %squiz has <strong>%d</strong> question%s" % (
        "multiple-choice " if allmc else "", n, "" if n == 1 else "s")
    if n:
        auto += " worth <strong>%s</strong> point%s each (<strong>%s</strong> points total)" % (
            _g(per), "" if per == 1 else "s", _g(pts))
    auto += "."
    if tl:
        auto += " You have <strong>%d minutes</strong>." % tl
    if at not in (-1, None):
        auto += " Up to <strong>%d</strong> attempt%s." % (at, "" if at == 1 else "s")
    sp = {"keep_average": "the <strong>average</strong> of your attempts",
          "keep_highest": "your <strong>highest</strong> attempt",
          "keep_latest": "your <strong>latest</strong> attempt"}.get(quiz_meta.get("scoring_policy"))
    if sp:
        auto += " Your recorded score is %s." % sp
    auto += "</p>"
    rows = [("Questions", n), ("Total points", pts),
            ("Time limit", f"{tl} minutes" if tl else "None"),
            ("Attempts allowed", "Unlimited" if at in (-1, None) else at)]
    if quiz_meta.get("due_at"):
        rows.append(("Due", canvas_rest.to_pacific(quiz_meta["due_at"])))
    trs = "".join(f"<tr><td {_TD}><strong>{k}</strong></td><td {_TD}>{v}</td></tr>" for k, v in rows)
    table = ('<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;">'
             f'<tr><th {_TH}>Item</th><th {_TH}>Value</th></tr>{trs}</table>')
    # The intro goes ABOVE the fence, not inside it. It is the instructor's sentence about what
    # the quiz covers, and everything inside the fence is replaced wholesale on the next rebuild —
    # so an intro inside would be written once and silently dropped the next time. It also reads
    # better first: the topic, then the mechanics.
    return f'{intro_html or ""}{_SUMMARY_OPEN}{auto}{table}{_SUMMARY_CLOSE}'


def split_summary(html):
    """(what the instructor wrote, the generated summary) — either may be empty.

    A description written before the fence existed has none, so it comes back whole as the
    instructor's. Keeping something that turns out to be generated is the harmless mistake;
    discarding something they wrote is not.
    """
    html = html or ""
    i = html.find(_SUMMARY_OPEN)
    if i < 0:
        return html.strip(), ""
    j = html.find(_SUMMARY_CLOSE, i)
    if j < 0:                                   # truncated fence — keep what precedes it
        return html[:i].strip(), html[i:]
    end = j + len(_SUMMARY_CLOSE)
    return (html[:i] + html[end:]).strip(), html[i:end]


# ── ORCHESTRATOR — the ONE entry the skill calls ───────────────────────────────────────────────
def make_quiz(base, token, course_id, quiz_id, questions, *, intro_html="", do_reorder=True):
    """Upsert questions → rebuild+PUT the description summary → refresh the stale cache. NEVER publishes.
    `questions` = list of full-payload dicts (use the q_* helpers or a plugin, e.g. a git-program essay)."""
    meta = fetch_quiz(base, token, course_id, quiz_id)
    title = meta.get("title")
    ids = upsert_questions(base, token, course_id, quiz_id, questions)
    if do_reorder and all(ids):
        reorder(base, token, course_id, quiz_id, ids)
    now_qs = list_questions(base, token, course_id, quiz_id)
    put_description(base, token, course_id, quiz_id,
                    build_description_summary(meta, now_qs, intro_html), title=title)
    refresh_quiz(base, token, course_id, quiz_id, title)   # bust the stale count/points cache
    return {"quiz_id": quiz_id, "question_ids": ids, "n": len(now_qs),
            "total_points": sum((q.get("points_possible") or 0) for q in now_qs)}


# ── DATA ENTRY — build a quiz from a questions JSON, so a quiz is DATA, not a script ──────────
#
# Why this lives here: like git_page before 2026-07-20, this module was importable ONLY as
# Python functions, so every session had to hand-write a throwaway driver just to hold the
# question list. That is session code — it drifts and is never reviewed. A quiz's content is
# DATA; it belongs in a .json the instructor can read, diff and re-run.
#
#   python3 quiz_builder.py <course_slug> <quiz.json> [--quiz-id N]
#
# quiz.json = {"quiz_id": N, "intro_html": "...", "questions": [ ... ]}
# Each question is one of:
#   {"type":"essay", "name":"Question 10", "points":25, "text_html":"<p>...</p>"}
#   {"type":"essay", "name":"Question 11", "points":25, "html_file":"/abs/path.html"}
#       html_file = HTML produced by a canonical builder (e.g. `git_page ... --quiz` writes the
#       git-program question's HTML to output_dir/Canvas-Pages/<CODE>.html). Referencing the
#       file keeps that body machine-built instead of pasted into the JSON.
#   {"type":"mc", "name":"...", "points":N, "text_html":"...", "choices":[...], "correct":0}
#   {"type":"ma", "name":"...", "points":N, "text_html":"...", "choices":[...], "correct":[2,3,4]}
#   {"type":"tf", "name":"...", "points":N, "text_html":"...", "correct_true":true}
_QTYPES = ("essay", "mc", "ma", "tf")


def _question_from_data(item):
    t = item.get("type", "essay")
    if t not in _QTYPES:
        raise ValueError("quiz_builder: unknown question type %r (expected one of %s)"
                         % (t, list(_QTYPES)))
    html = item.get("text_html")
    if item.get("html_file"):
        with open(item["html_file"], encoding="utf-8") as f:
            html = f.read()
    if not html:
        raise ValueError("quiz_builder: %r has neither text_html nor html_file" % item.get("name"))
    name, pts = item["name"], item["points"]
    if t == "essay":
        return q_essay(name, html, pts)
    if t == "mc":
        return q_multiple_choice(name, html, pts, item["choices"], item["correct"])
    if t == "ma":
        # `correct` is a LIST of indexes here (a single int for "mc") — a bare int would make
        # set(...) iterate nothing and silently produce a question with no correct answer.
        idx = item["correct"]
        if isinstance(idx, int):
            raise ValueError("quiz_builder: %r is type 'ma' but `correct` is an int; "
                             "multiple-answers needs a LIST of indexes" % name)
        return q_multiple_answers(name, html, pts, item["choices"], idx)
    return q_true_false(name, html, pts, item["correct_true"])


def build_quiz_from_file(course_slug, json_path, quiz_id=None):
    """Build every question in `json_path` into the quiz. Returns make_quiz's result."""
    import json
    from .. import course_config
    from ..auth.token import get_token
    # Course coordinates come from THE one reader (CourseGlobalWorkflow/README ◆ Config).
    # This used to `open()` grade_engine/config/<slug>.json directly — a directory deleted
    # 2026-07-28 — so every call raised FileNotFoundError. Never re-open a config by path.
    cfg = course_config.load(course_slug)
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    qid = quiz_id or data.get("quiz_id")
    if not qid:
        raise ValueError("quiz_builder: no quiz_id (set it in the JSON or pass --quiz-id)")
    base = cfg["canvas_base_url"]
    token = get_token(cfg["canvas_token_env"], base)
    qid = int(qid)

    # DESCRIPTION-ONLY: no "questions" key (or an empty list) => rebuild the description summary
    # from the questions ALREADY on the quiz and touch nothing else. Required whenever a quiz's
    # items must not be re-upserted — e.g. an imported exam whose 50 items all carry the same
    # `question_name`, which upsert (keyed on that name) would collapse into one.
    if not data.get("questions"):
        meta = fetch_quiz(base, token, cfg["course_id"], qid)
        now_qs = list_questions(base, token, cfg["course_id"], qid)
        put_description(base, token, cfg["course_id"], qid,
                        build_description_summary(meta, now_qs, data.get("intro_html", "")),
                        title=meta.get("title"))
        refresh_quiz(base, token, cfg["course_id"], qid, meta.get("title"))
        return {"quiz_id": qid, "question_ids": [], "n": len(now_qs),
                "total_points": sum((q.get("points_possible") or 0) for q in now_qs)}

    return make_quiz(base, token, cfg["course_id"], qid,
                     [_question_from_data(q) for q in data["questions"]],
                     intro_html=data.get("intro_html", ""))


if __name__ == "__main__":
    _argv = sys.argv[1:]
    _pos = [x for x in _argv if not x.startswith("--")]
    if len(_pos) < 2:
        print("usage: python3 quiz_builder.py <course_slug> <quiz.json> [--quiz-id N]")
        raise SystemExit(2)
    _qid = _argv[_argv.index("--quiz-id") + 1] if "--quiz-id" in _argv else None
    _res = build_quiz_from_file(_pos[0], _pos[1], quiz_id=_qid)
    print("quiz=%s questions=%s total_points=%s"
          % (_res["quiz_id"], _res["n"], _res["total_points"]))
