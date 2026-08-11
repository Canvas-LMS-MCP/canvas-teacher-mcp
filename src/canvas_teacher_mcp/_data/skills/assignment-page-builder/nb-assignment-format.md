# NB-assignment page format (Colab / Jupyter notebook type)

The FIXED instruction-doc structure for an **NB (Colab / Jupyter notebook)** assignment. Use this
whenever the submission is a notebook the student completes section by section. This is the NB type
only — CODE/program assignments use `program-assignment-format.md`; other types use their own plugin.

> Canonical NB logic (do NOT invent it): the create side is `$CANVAS_LMS_ROOT/.claude/skills/nb-homework-create/SKILL.md`
> and the grade side is `$CANVAS_LMS_ROOT/.claude/skills/grade-nb/SKILL.md` (+ `CourseGlobalWorkflow/GradingEngine/NbInspect.md`).
> Creation and grading are **mirrors**. This file is the student-facing page shape drawn from them.
> Generic authoring rules (bait-first "fishing", finalize order) live in `assignment-page-builder/SKILL.md`.

## How an NB is graded (grade-nb — state EXPECTATIONS on the page, never the auto-grader internals)

The notebook score = four parts, all mirrored on the page:
1. **Correctness** — each task judged; **code AND explanation evaluated separately** (both count).
2. **Completeness** — every problem's answer region is filled.
3. **Process** — a **pinned revision at the end of each section**, growing content over realistic time
   (not one bulk pin, not a burst). Pinned revisions only — auto-saves don't count.
4. **Reflection** — the per-section takeaway is written.

> The revision-history **screenshot is a formality**; grading reads the actual file's pinned revisions
> (times + content). Never expose the auto-grader mechanics — state only what the student must DO.

## ⛔ Pinned sections — fixed NAMES + ORDER (do NOT rename or reorder per session)

| # | Section | What goes in it |
|---|---|---|
| **[1]** | **What you build** | ONE line: complete the notebook, section by section. The bait — big picture first. |
| **[2]** | **How the notebook works** | The section rhythm: instructions → **your answer cells (code cells AND explanation/markdown cells)** → a reflection → **File → Save and pin revision, named `Section N`**. |
| **[3]** | **The tasks (per section)** | What each section asks — every task LABELED (below): `[code]` and/or `[explain]`. A section may hold both; both are graded. |
| **[4]** | **Keep the cells** | Do NOT delete/reorder the given cells; write your answer in the marked region. |
| **[5]** | **Submit** | The Colab link **shared as Editor**, plus a **screenshot of the Revision-history panel** showing your `Section N` pins. |
| **[6]** | **How you're graded** | Correctness (`[code]` **and** `[explain]` each) · completeness · **process = a pinned revision per section over real time** · per-section reflection. |

## ★ [3] Task type labels — mark EVERY task (code vs explanation must be unmistakable)

- **`[code]`** — write / complete code in a code cell.
- **`[explain]`** — write your answer / reasoning in words, in a markdown cell.
- One section can carry BOTH; label each task so the student never confuses "write code" with "write an
  explanation." A section the instructions ask to explain MUST show an `[explain]` task (grade-nb scores
  it). Mirror the anchors `nb-homework-create` stamps (`type=code|explain`).

## Inline code font = BACKTICKS (required)

Every identifier, cell name, path, and command in body/bullet text is wrapped in `` `backticks` `` →
`build.py` renders inline code font. e.g. `` `Section N` ``, `` `File -> Save and pin revision` ``.

## Build (never hand-author HTML)

Assemble sections as gws-richdoc blocks (`banner`, `section_box`, `body`, `bullets`, `tip`) and render
with `build.make(...)` / `build.rebuild(...)`. The look is fixed in `build.py`.

## Used by / pairs with

- The NB assignment plugin (per course), the global `nb-homework-create` (template) + `grade-nb` (grading).
- Generic method: `assignment-page-builder/SKILL.md`. Sibling: `program-assignment-format.md` (code type).
