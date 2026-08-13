"""Quiz tools — wraps `quiz/quiz_builder.py`, the one place Canvas quiz calls are made.

Quizzes are created UNPUBLISHED. Questions are matched by name, so building the same quiz twice
updates it rather than duplicating it.
"""

from __future__ import annotations

from ..quiz import quiz_builder as qb
from . import _ctx

TOOLS = ("get_quiz", "list_quiz_questions", "create_quiz", "update_quiz", "add_quiz_questions",
         "finalize_quiz", "parse_question_bank")


def _conn(course: str):
    cfg = _ctx.config(course)
    return cfg["canvas_base_url"], _ctx.credential(course), cfg["course_id"]


def get_quiz(course: str, quiz_id: int) -> dict:
    """One quiz: title, description, question count, points."""
    base, token, cid = _conn(course)
    return qb.fetch_quiz(base, token, cid, quiz_id)


def list_quiz_questions(course: str, quiz_id: int) -> list[dict]:
    """Every question on a quiz: id, name, type, points."""
    base, token, cid = _conn(course)
    return [
        {"id": q.get("id"), "question_name": q.get("question_name"),
         "question_type": q.get("question_type"), "points_possible": q.get("points_possible")}
        for q in qb.list_questions(base, token, cid, quiz_id) or []
    ]


def create_quiz(course: str, title: str, description: str = "", time_limit: int | None = None,
                allowed_attempts: int = 1, due_at: str | None = None,
                assignment_group_id: int | None = None) -> dict:
    """Create an empty quiz, unpublished. `due_at` is ISO-8601 UTC, `time_limit` is minutes."""
    base, token, cid = _conn(course)
    return qb.create_quiz(base, token, cid, title=title, description=description,
                          time_limit=time_limit, allowed_attempts=allowed_attempts,
                          due_at=due_at, assignment_group_id=assignment_group_id)


def update_quiz(course: str, quiz_id: int, title: str | None = None,
                description: str | None = None, time_limit: int | None = None,
                allowed_attempts: int | None = None, due_at: str | None = None) -> dict:
    """Update a quiz's settings. Publish state is left alone — the instructor publishes."""
    base, token, cid = _conn(course)
    fields = {k: v for k, v in (("title", title), ("description", description),
                                ("time_limit", time_limit),
                                ("allowed_attempts", allowed_attempts), ("due_at", due_at))
              if v is not None}
    if not fields:
        raise ValueError("nothing to update")
    return qb.update_quiz(base, token, cid, quiz_id, **fields)


def add_quiz_questions(course: str, quiz_id: int, questions: list[dict]) -> dict:
    """Add or update questions. A question already carrying the same `name` is updated in place.

    Each question is `{"name", "type", "text", "points", ...}` where type is one of:
      multiple_choice   choices: list[str]        correct: index
      multiple_answers  choices: list[str]        correct: list[index]
      true_false        correct: true | false
      essay             (no extra fields)
    `text` is HTML.

    Finishes by rebuilding the description summary and clearing Canvas's stale counts, because a
    quiz whose questions changed and whose description did not is a quiz that states the wrong
    number of questions and the wrong total. Anything the instructor wrote in the description is
    kept — see `finalize_quiz`.
    """
    base, token, cid = _conn(course)
    payload = [_question(q) for q in questions]
    result = qb.upsert_questions(base, token, cid, quiz_id, payload)
    return {"written": len(payload), "result": result,
            "finalized": finalize_quiz(course, quiz_id)}


def finalize_quiz(course: str, quiz_id: int, intro_html: str = "") -> dict:
    """The description summary is written HERE and nowhere else, from the quiz's own state.

    `add_quiz_questions` already calls this, so it is needed by hand only to change the intro or
    to repair a quiz edited elsewhere. Canvas also leaves `question_count` and `points_possible`
    stale after any question change, and this clears that.

    Whatever the instructor wrote survives: the generated part is fenced, and everything outside
    the fence is carried back in as the intro. `intro_html` replaces it when given — passing the
    empty string does not, or every automatic run would erase their writing.
    """
    base, token, cid = _conn(course)
    meta = qb.fetch_quiz(base, token, cid, quiz_id)
    questions = qb.list_questions(base, token, cid, quiz_id) or []
    theirs, _ = qb.split_summary(meta.get("description"))
    intro = intro_html or theirs
    html = qb.build_description_summary(meta, questions, intro_html=intro)
    qb.put_description(base, token, cid, quiz_id, html)
    qb.refresh_quiz(base, token, cid, quiz_id, meta.get("title"))
    return {"quiz_id": quiz_id, "questions": len(questions), "title": meta.get("title"),
            "intro_kept": bool(intro), "intro_replaced": bool(intro_html and theirs)}


def _question(q: dict) -> dict:
    """One question in this tool's plain shape -> the full Canvas payload."""
    kind = q.get("type", "multiple_choice")
    name, text, points = q["name"], q.get("text", ""), q.get("points", 1)
    if kind == "multiple_choice":
        return qb.q_multiple_choice(name, text, points, q["choices"], q["correct"])
    if kind == "multiple_answers":
        return qb.q_multiple_answers(name, text, points, q["choices"], q["correct"])
    if kind == "true_false":
        return qb.q_true_false(name, text, points, bool(q["correct"]))
    if kind == "essay":
        return qb.q_essay(name, text, points)
    raise ValueError(f"unknown question type {kind!r}; use multiple_choice, multiple_answers, "
                     "true_false or essay")


def parse_question_bank(text: str, chapter: int = 1, points: float = 1,
                        course: str | None = None, save: bool = False) -> dict:
    """Turn a plain-text question bank into questions `add_quiz_questions` accepts.

    The text must be in the bank shape — a numbered stem, lettered choices, an answer key:

        12.<TAB>What does this print?
        a.<TAB>1
        b.<TAB>2
        Key:b

    Text in any other shape is REWRITTEN into this shape first; the parser is not widened.
    Returns the parsed questions plus a preview HTML to show the instructor before anything
    reaches Canvas.

    Pass `course` for its build directory, and `save=True` to write the three build files there —
    the source text, the quiz JSON and the preview — exactly what the command line writes. The
    preview is what the instructor reviews, so it is worth a file; the source is the provenance
    for the JSON. Without `course` there is nowhere to write: an output directory belongs to a
    course, and this server holds no notion of a current one.
    """
    from ..quiz import bank_parse

    questions, problems = bank_parse.parse(text)
    items = bank_parse.to_items(questions, int(chapter), points)

    # A null with no reason is how the last three sessions went wrong: the caller reads "there is
    # no output directory" when what happened is that nobody said which course.
    written, out, note = None, None, None
    if course:
        out = bank_parse.build_dir(course, int(chapter))
        if save:
            written = bank_parse.write_build(out, text, questions, items, int(chapter),
                                             "pasted text")
        else:
            note = ("Nothing was written. Call again with save=true to put the source, the JSON "
                    "and the preview in %s." % out)
    else:
        note = ("No course was given, so there is nowhere to write: an output directory belongs "
                "to a course and this server has no notion of a current one. Call again with "
                "course='<slug>' (list_courses names them) and save=true. The course config "
                "never stores an output directory — it is derived, and get_course returns it.")
    return {
        "build_dir": out,
        "written": written,
        "note": note,
        "count": len(items),
        # Handed straight to add_quiz_questions. The parser's own shape is its business; a caller
        # asked to translate between two of our formats will eventually get it wrong.
        "questions": [
            {"name": it["name"],
             "type": "multiple_choice" if it["type"] == "mc" else "multiple_answers",
             "text": it["text_html"],
             "points": it["points"],
             "choices": it["choices"],
             "correct": it["correct"]}
            for it in items
        ],
        # What the parser could not read. Reported, never dropped: a bank whose shape drifted
        # would otherwise yield a short quiz that looks complete.
        "problems": problems,
        "preview_html": bank_parse.preview_html(f"Chapter {chapter}", questions, items),
    }


def register(server) -> None:
    for fn in (get_quiz, list_quiz_questions, create_quiz, update_quiz, add_quiz_questions,
               finalize_quiz, parse_question_bank):
        server.add_tool(fn)
