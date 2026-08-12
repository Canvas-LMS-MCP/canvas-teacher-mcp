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
    """
    base, token, cid = _conn(course)
    payload = [_question(q) for q in questions]
    result = qb.upsert_questions(base, token, cid, quiz_id, payload)
    return {"written": len(payload), "result": result}


def finalize_quiz(course: str, quiz_id: int, intro_html: str = "") -> dict:
    """Rewrite the description summary and refresh the quiz's stale counts.

    Canvas leaves `question_count` and `points_possible` stale after any question change, so this
    runs after the questions are in.
    """
    base, token, cid = _conn(course)
    meta = qb.fetch_quiz(base, token, cid, quiz_id)
    questions = qb.list_questions(base, token, cid, quiz_id) or []
    html = qb.build_description_summary(meta, questions, intro_html=intro_html)
    qb.put_description(base, token, cid, quiz_id, html)
    qb.refresh_quiz(base, token, cid, quiz_id, meta.get("title"))
    return {"quiz_id": quiz_id, "questions": len(questions), "title": meta.get("title")}


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


def parse_question_bank(text: str, chapter: int = 1, points: float = 1) -> dict:
    """Turn a plain-text question bank into questions `add_quiz_questions` accepts.

    The text must be in the bank shape — a numbered stem, lettered choices, an answer key:

        12.<TAB>What does this print?
        a.<TAB>1
        b.<TAB>2
        Key:b

    Text in any other shape is REWRITTEN into this shape first; the parser is not widened.
    Returns the parsed questions plus a preview HTML to show the instructor before anything
    reaches Canvas.
    """
    from ..quiz import bank_parse

    questions, problems = bank_parse.parse(text)
    items = bank_parse.to_items(questions, int(chapter), points)
    return {
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
