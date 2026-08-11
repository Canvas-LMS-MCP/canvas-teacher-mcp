---
name: git-asmt-page
description: "GLOBAL L1 child of git-asmt — build the Canvas ASSIGNMENT PAGE for a git coding assignment via the global git_page (assignment-page-builder). Your job = fill the asmt dict well (gist, spec, I/O = function contract, examples call→output, restrictions, elaboration, test-items table, per-item points/rubric, per-item guide, function prototype+params) → git_page(course_slug, asmt). Language-agnostic; which fields to use (stdin-program vs function) comes from the L3 course wrapper's curriculum. Use to make/renew any git-assignment Canvas page. Canvas side ONLY — the repo is git-asmt-repo."
tools: [build_coding_assignment_page, create_assignment, update_assignment]
---

# git-asmt-page — Canvas page for a git assignment (L1 child)

The Canvas half of `git-asmt`. It does **not** build the repo (that's `git-asmt-repo`). It builds the
**page** and its **parts**, in the standard format the global builder produces. **You never hand-write
the page HTML or the gDoc** — you fill the `asmt` dict and call `git_page`; it renders the instruction
gDoc AND the page from the same dict (so they always agree) and uploads it (unpublished).

```python
import sys
sys.path.insert(0, "$CANVAS_LMS_ROOT/.claude/skills/assignment-page-builder")
from git_page import git_page
out = git_page(course_slug, asmt, points=N, push=True, due_at="…Z")
```

## The parts this page must carry (the "common elements")
Every git-assignment page, built from the `asmt` dict:
- **Instruction** — what to make: `gist` (1 line) + `spec` (what each case does) + `algorithm`.
- **Function contract** — the core **prototype, parameters, return** (`io`: Parameter / Return lines).
  For a stdin program instead, the I/O is the stdin→stdout contract (no prototype).
- **Examples** — `call → output` pairs (verbatim from the spec/slides; RUN it, paste the real result).
- **Restrictions** — yellow box (what NOT to do; mirrors what the tests enforce).
- **Elaboration** — navy box: exactly what the student must WRITE (graded) — algorithm, edge
  correctness, errors→fixes with commit links.
- **Test-items table** — per grader (Compile/Run/T1..Tn) with **max points** and *what it checks*,
  taken from the ACTUAL test file (never invented).
- **Per-item points / Rubric** — the `Item | Points | Criteria` table summing to `points_possible`
  (autograder / elaboration / commit / repo-link split — GRADING.md). `points=N` → git_page distributes
  by `rubric_weights`; never hardcode per-item numbers.
- **Request link** — `…/classroom/issues/new?template=<request_form>&assignment=<CODE>` (git_page builds
  it from `request_id`=CODE; requires the CODE registered by `git-asmt-repo` first).
  ⛔ **ONE VALUE, FOUR PLACES.** `request_id` = `code` = the assignment slot in the student repo
  name = the org-hub `config.json` key:
  `csci19a-su26-`**`A612`**`-akshat0714` · `CSCI19`**`A612`**`Starter` · key `"A612"`.
  `request_id` exists only for the ~1% assignment whose request key genuinely differs — passing a
  different value is a DECLARATION, not a default, and `git_page` now STOPS on a silent
  divergence. Why: on 2026-08-04 all 14 CSCI-19A chapter-5 pages shipped `assignment=5-6`-style
  TITLES while the register held `A56`, and nothing noticed for a whole chapter — the student
  request form is a dropdown generated from `config.json`, so students picked the right entry and
  the broken pre-fill stayed invisible.
- **Full guide** — the embedded instruction gDoc (git_page makes it in `pages_folder`).

## Authoring method (the only job)
Read the instruction source with canonical readers → restructure into the `asmt` fields: clear,
beginner-complete, **every example shows INPUT→OUTPUT**, outline/bullet format, no emoji, inline code in
`` `backticks` ``, and the **instruction must MATCH the tests** (no word-hunting). Follow
`assignment-page-builder/program-assignment-format.md` for the pinned section order + field shapes.

## Language / curriculum = L3, not here
Which fields fit (function `prototype/params/returns` vs a stdin program's I/O), the `local_test`
baseline command, and the reference page URL come from the **L3 course wrapper** (its curriculum map +
the reference page it names). Coordinates come from `course_config`. This skill is language-agnostic —
it renders whatever `asmt` carries.

## Finalize gates (every gate BLOCKS)
- Embedded gDoc/slides shared **anyone-with-link Viewer** (else the embed breaks) — [[verify-gdoc-share-before-embed]].
- **Re-GET** the Canvas description → validate the FINAL rendered HTML: Request link present
  (`href == visible text`, substring `assignment=<CODE>`), **Rubric table sums to `points`**, gDoc embed
  present, Submit items present, slides iff passed.
- **No emoji**; **unpublished** (never set `published` — only the instructor publishes);
  **instruction ↔ tests agree**.

## References
- Builder: `assignment-page-builder/SKILL.md` + `git_page.py`; format: `program-assignment-format.md`.
- Sibling: `git-asmt-repo` (the repo + tests this page describes). Parent: `git-asmt`.
- Policy: `CourseGlobalWorkflow/GRADING.md` (rubric %), `Access/Canvas.md` (no-emoji, code-font, backup-then-overwrite).
- Per-course specifics: the L3 wrapper + `course_config.load(<course>)`.
