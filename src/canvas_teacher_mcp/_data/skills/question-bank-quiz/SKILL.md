---
name: question-bank-quiz
description: "GLOBAL — turn a plain-text question bank into a Canvas CLASSIC quiz. Any text works once it is in the bank shape (numbered stem, lettered choices, an answer key); a publisher test bank is the common case, not the requirement. Parses the bank into quiz_builder's question JSON, renders a preview HTML for review, then delegates the Canvas write to quiz-builder. Multiple-choice and multiple-answer items; per-question points are an input. Triggers: 'question bank', 'test bank', 'publisher bank', 'chapter N quiz from the bank', '문제은행', '뱅크로 퀴즈'."
tools: [parse_question_bank, create_quiz, add_quiz_questions, finalize_quiz]
---

# question-bank-quiz — a text bank → Canvas quiz

An **adapter in front of `quiz-builder`**, not a second quiz engine. It converts an
unstructured publisher bank into the JSON `quiz_builder.build_quiz_from_file` already
consumes. Every Canvas call still happens in `quiz_builder.py` — there is one quiz machine.

```
bank.txt ──▶ bank_parse.py ──▶ Ch<N>_quiz.json ──▶ quiz_builder ──▶ Canvas quiz
                   │                                                  (unpublished)
                   └──▶ Ch<N>_quiz.html  ← REVIEW THIS FIRST
```

**What this is NOT:** hand-authoring questions from a doc or slide (that is `quiz-builder`
directly, or a course's `customize-quiz`), and not a git-program question (that is
`git-asmt` → `quiz-builder`). Nothing here knows about git.

## Input — the bank format

```
Chapter 7 Single-Dimensional Arrays        title line
Section 7.5 Copying Arrays                 section marker, skipped ("Sections" too)
12.<TAB>stem text
                                           blank line separates stem from code
int[] list = {1, 2, 3};                    code block
a.<TAB>choice
...
Key:cde  optional rationale                answer letters, then the author's prose
#                                          block separator
```

**Three parsing rules exist because breaking any of them loses questions silently:**

1. **`key:` is matched case-insensitively.** In the Liang chapter-7 bank, 5 of 53 items use
   lowercase `key:`. A case-sensitive parser drops exactly those five and the count still
   looks plausible.
2. **Only the run of `[a-e]` right after `key:` is the answer.** The rest is the author's
   rationale (`Key:abcd e is incorrect because…`) and never reaches the student.
3. **Escaping is entity-aware.** The bank already contains `&lt;`; a plain escape would show
   students `&amp;lt;`.

One answer letter → `mc`. Two or more → `ma` (`multiple_answers_question`).

## The input shape IS the contract

The parser reads exactly one shape:

```
12.<TAB>stem text
a.<TAB>choice
b.<TAB>choice
Key:b
```

Text that arrives in any other shape — `Q1)` numbering, `Answer: C`, a table pasted out of a
PDF, a slide's bullet list — is REWRITTEN into the shape above before parsing. **The parser is
never widened to accept a new shape.** One accepted shape means the format is knowable; a parser
that grew a branch per source is a format nobody can state. Save the rewritten text as an output:
it is what the questions were parsed from, and the provenance only holds if it is kept.

## Run it

```
parse_question_bank(text, chapter=7, points=3)   -> questions + preview_html
   review the preview, then
create_quiz(course, title)                       -> an empty unpublished quiz
add_quiz_questions(course, quiz_id, questions)
finalize_quiz(course, quiz_id)
```

Review the preview before anything reaches Canvas.

Writes to `<output_dir>/quiz_build/Ch<N>/` (path derived via `course_config`):

| File | What |
|---|---|
| `Ch<N>_source.txt` | the bank as parsed — UTF-8, LF. **Provenance for the JSON** |
| `Ch<N>_quiz.json` | `quiz_builder` input |
| `Ch<N>_quiz.html` | preview — every question, choices, correct ones in green |

Exit status is non-zero when the report lists problems.

## ⛔ Step 2 is REVIEW, and it is not optional

**Open `Ch<N>_quiz.html` in a browser before building anything.** A bank is a text file
written by a human at a publisher; it is not validated data. Check:

- every question has its choices, and no choice text is truncated or merged
- code blocks render as code (Courier), indentation intact
- the green-marked answer is actually correct — **verify the ones with code by tracing them**
- multiple-answer items really have several correct choices

**A content error in the bank is fixed in the SOURCE, never in the parser.** Edit
`Ch<N>_source.txt`, re-run the parser on it, and record what was changed. The parser stays a
faithful translator, so any output can be traced back to a file. (Chapter 7 example: item 40
asked for low/high *"after the first iteration"* while its key `d` was the state after the
loop **terminates** — no choice matched the stem. The stem was corrected in the source.)

## Step 3 — build the quiz

```bash
python3 quiz-builder/quiz_builder.py <course_slug> <…/Ch7_quiz.json> --quiz-id <N>
```
Create the empty quiz first (`quiz_builder.create_quiz`, `published=False`) if it does not
exist, then pass its id. `upsert_questions` matches on `question_name`, so re-running is
idempotent and question names must be unique — this skill names them `<CC>-<NNN>`
(`07-001`…`07-053`).

## Step 4 — settings, and who publishes

Match the course's existing review quizzes rather than inventing settings. CSCI-19A
Chapter 5 (`[Quiz] Chapter 5. Review Questions`, quiz 711759) is the model: `quiz_type`
`assignment`, 3 points per question, 5 attempts, `keep_average`, 90-minute limit, shuffle
off, show correct answers on.

**The instructor publishes. This skill never sets `published`** (`Access/Canvas.md`
[Don't Publish]).

## House style for code inside a question

Follow what the course's existing quiz already does — for CSCI-19A that is a single
`<span style="font-family: Courier New;">` with `<br>` between lines and `&nbsp;` for
indentation (NOT `<pre>`). Canvas strips `<style>` blocks, so styling is inline
(`Access/Canvas.md` [Code Font in HTML]). `bank_parse.py` emits exactly this.

**Apply the code font to the code BLOCK in the stem only. Leave answer choices and inline
tokens in plain text** — that is what the course's existing quizzes do, and it is the
intended behaviour, not an omission. Measured on chapter 7: an automatic detector flagged 77
of 228 choices as code and **16 were wrong** — whole English sentences such as *"The program
has a compile error because `String argv[]` is wrong…"* would render as one grey monospace
box. Worse, it split a single question's choices across two fonts (`a[2]` code, `a(2)`
prose) in item 07-001 — where telling `[ ]` from `( )` IS the question, so the font
difference hands the student the answer. If a chapter ever needs styled choices, declare it
per question as DATA reviewed in the preview step; do not infer it from the text.

Do **not** reproduce a `<link rel="stylesheet" href="…StyleSheetforCSS.txt">` prefix if you
see one on existing questions — that is a QTI/Respondus import artifact that does nothing.

## Related

- `quiz-builder` — the quiz machine this delegates to (also the home of the git-program path).
- `canvas_core/MANUAL.md` — Canvas resource functions.
- `CourseGlobalWorkflow/Access/Canvas.md` — publish rule, form-encoding, code font.
