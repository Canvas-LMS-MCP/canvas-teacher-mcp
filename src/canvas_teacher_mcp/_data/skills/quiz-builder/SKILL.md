---
name: quiz-builder
description: "GLOBAL methodology for building/updating a Canvas CLASSIC quiz — its question items + the description summary. Create a quiz from nothing OR modify an existing one. Dispatches question items by type (native MCQ/T-F/essay/fill-in via the Quizzes API; a git-program question defers to the course-local git-homework). All Canvas quiz API calls go through the co-located quiz_builder.py — never hand-rolled. Use when making/updating any Canvas quiz's questions or details."
tools: [create_quiz, update_quiz, get_quiz, list_quiz_questions, add_quiz_questions, finalize_quiz]
---

# quiz-builder — GLOBAL quiz-building methodology

Build or update a Canvas **Classic quiz**: its **question items** + the **description summary**.
Idempotent — create a quiz's questions from nothing OR modify an existing quiz (questions matched by
`question_name`). Pairs with the machinery `quiz_builder.py` (same dir) the way `assignment-page-builder`
pairs with `assignment_page_builder.py`.

## ⛔ HARD RULE — the machinery is the ONLY path (gate, don't hand-roll)
- **ALL Canvas quiz API calls go through `skills/quiz-builder/quiz_builder.py`** (co-located). NEVER write
  ad-hoc `canvas_rest.get/post/put` to `/quizzes/...` in a session — that is the recurring hand-roll bug
  (grade_nb_skill / Stage-B finalize). If a needed call is missing, ADD it to `quiz_builder.py`, never
  improvise. The entry is `quiz_builder.make_quiz(base, token, course_id, quiz_id, questions, ...)`.
- **NEVER publishes.** No `published` set — the instructor publishes.
- **Full payload always** (`question_type` / `points_possible` / `question_text` / `answers`) — a missing
  field silently fails. `make_quiz` refreshes the STALE `question_count`/`points_possible` cache after
  changes, and reorders (the question endpoint ignores `position`). All per Access/Canvas.md.

## Two parts
1. **Question items** — built by TYPE (dispatch below), then `upsert_questions` (create-or-update by name).
2. **Description summary** — `build_description_summary` renders a student-facing table: Questions · Total
   points · Time limit · Attempts · Due (computed from the questions, since the quiz's own fields are stale
   until refresh). Add a short intro via `intro_html`.

## Question dispatch — by type
| Question type | How | Builder |
|---|---|---|
| **MCQ / True-False / essay / fill-in** (native) | `quiz_builder.q_multiple_choice / q_true_false / q_essay` → full payload | this skill's `quiz_builder.py` |
| **git-program** (a coding question) | defer to the **course-local `git-homework`** (repo + autograder + assignment page); the quiz question is an **essay** (`q_essay`) whose text links to the coding assignment / Request repo. **NO new git-program skill.** | local `git-homework` + `assignment-page-builder` for the page |
| bulk MCQ (e.g. all-50) | run the MCQ helper N times from the source bank — one plugin, not a new skill | `quiz_builder.py` |

An unusual one-off type with no helper → the AI builds the payload dict inline (still POSTed via
`quiz_builder`), or a thin plugin is added. The orchestrator (`make_quiz`) still owns the flow.

## Build-time → grading link (leave placeholders now, full setup at grade time)
While building, **persist the grading info each question needs** so the grade sub-skill reads it later
(NB-manifest pattern) — for a git-program question: the rubric in force (`GRADING.md`, or the document
named by a `Grading override:` line in that course's `CLAUDE.md`),
forbidden functions, the T1–T4 test design, and the repo/`<CODE>`. Store as PLACEHOLDER/partial now; the
**`grade-git-program`** sub-skill does the full setup when grading. (Quiz grading is per-question, NOT
`posted_grade` — Access/Canvas.md [Quiz Submission Scoring].)

## Quiz spec — the input contract (fill ONCE; NEVER ad-hoc-prompt the user field by field)
The builder is driven by a single **quiz spec** dict — the quiz-level analogue of the page-builder's
`asmt`. Collect it UP FRONT; defaults fill the rest; ask the user ONCE only for missing REQUIRED bits,
never one question per setting (that ad-hoc interrogation is the anti-pattern this contract removes).

| Field | Meaning | Default |
|---|---|---|
| `title` | quiz title | **required** |
| `quiz_type` | assignment / practice_quiz / graded_survey / … | `"assignment"` |
| `time_limit` | minutes (int) or None | None |
| `allowed_attempts` | int; `-1` = unlimited | 1 |
| `assignment_group_id` | gradebook group id (columns roll up under one group) | None |
| `due_local` | **Pacific wall-clock** `"YYYY-MM-DD HH:MM"` → pass through `canvas_rest.to_utc(due_local)` for the API. **NEVER hand-compute the `…Z` UTC offset** — DST makes it wrong half the year. | None |
| `intro_html` | description-summary intro | `""` |
| `questions` | list of items per the dispatch table (type · name · text_html · points · …) | `[]` |
| `published` | — | **NEVER set** (only the instructor publishes) |

Map the spec → `create_quiz`/`update_quiz` (shell + settings, using `to_utc(due_local)`) → `make_quiz`
(questions + description summary). One spec in, one quiz built — no piecemeal Q&A.

## Flow
0. **No quiz on Canvas yet? Make the SHELL first** — `create_quiz(base, token, course_id, title=…, quiz_type="assignment", time_limit=…, allowed_attempts=…, assignment_group_id=…)` returns a fresh quiz `id` (**NEVER publishes**). This is the true "from nothing" path. Rename / retune an existing shell (or split one quiz into several) with `update_quiz(base, token, course_id, quiz_id, title=…, …)`; drop unwanted questions with `delete_question`.
1. Fetch the quiz (`fetch_quiz`) — id from the URL `.../quizzes/<qid>/edit`, or the id returned by step 0. Create-or-update; never publish.
2. Build each question by type (dispatch) → a list of full-payload dicts.
3. `make_quiz(base, token, course_id, quiz_id, questions, intro_html=…)` → upsert + reorder + description
   + cache refresh. ONE call.
4. **GATE (BLOCK on fail):** re-GET the quiz + questions → every question present with its `points_possible`;
   the description summary table present; `question_count`/`points_possible` non-stale (refreshed); no emoji;
   code-font spans on any code (per Access/Canvas.md). Validate the FINAL rendered HTML.

## Reference (current, authoritative — no deprecated docs)
- **`CourseGlobalWorkflow/Access/Canvas.md`** — [Quiz Question Updates] (payload · stale-cache refresh ·
  reorder) + [Quiz Submission Scoring] (grading: per-question, not posted_grade) + general (no-emoji,
  code-font, backup-then-overwrite). The machinery `quiz_builder.py` encodes these.
- **`CourseGlobalWorkflow/GRADING.md`** — the rubric + forbidden-function rule for a git-program quiz
  question. A course that weights its quiz questions differently declares a `Grading override:` line in
  its own `CLAUDE.md` (GRADING.md Q4); read whichever is in force. Referenced, never copied.
- **`assignment-page-builder`** — building the git-program question's assignment page (the course's page
  skill supplies the content).
- Machinery: `skills/quiz-builder/quiz_builder.py` (same dir).
