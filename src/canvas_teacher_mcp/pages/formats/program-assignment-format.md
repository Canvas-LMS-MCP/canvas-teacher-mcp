# Program-assignment page format (CODE / GitHub-program type)

The FIXED instruction-doc structure for a **program / GitHub-code** assignment — the gws-richdoc
gdoc that the git plugin embeds. Use this whenever the task is *"implement a function / write a
program."* Other types (jshell lab, essay, …) use THEIR own plugin's structure — **this file is the
CODE/FUNCTION type only.**

> The GENERIC authoring rules — bait-first ("fishing"), INPUT→OUTPUT examples, finalize order —
> live in `$CANVAS_LMS_ROOT/.claude/skills/assignment-page-builder/SKILL.md`. This file adds ONLY the
> pinned section order + the function-manual shape for a code assignment.

## ⛔ Pinned sections — fixed NAMES + ORDER (do NOT rename or reorder per session)

| # | Section | What goes in it |
|---|---|---|
| **[1]** | **What you write** | ONE line: the single function/program to write + the one most important fact (e.g. *"returns a lambda, not a list"*). This is the bait — big picture first. |
| **[2]** | **The function** ★ | The MOST IMPORTANT section — a Python-manual entry (see below). |
| **[3]** | **What each `<X>` does** | The detail behind [2] (each criteria / mode / case). Bullets, one per line. |
| **[4]** | **Examples** | A **call and its returned value**. When it is NOT stdin/stdout, LABEL it: *"a call and its returned value — not keyboard input"* (parameter-in → return-out, never confused with I/O). Code block. |
| **[5]** | **Restrictions** | What the student must NOT use; the autograder enforces each (AST source-check). |
| **[6]** | **How your work is tested** | `T1`–`T4`, one line each; and how to run locally (`pytest -m T1`, `pytest`). |

Add an **Algorithm** section between [4] and [6] ONLY when the problem needs a stepwise algorithm
(bullets, one idea per line — never a dense paragraph).

## ★ [2] The function — Python-manual shape (the section that matters most)

Lead with the prototype, then Parameters and Returns like a standard reference manual — the reader
must grasp **what it receives and what it produces from [2] ALONE**:

- **prototype** (code block): `def <name>(<params>):`
- **Parameters** — for EACH parameter: `` `name` `` (`type`) — its purpose / allowed values.
- **Returns** — `type` → what it is + its meaning. (For a factory function: *"a `lambda`; when you
  later call it with `<X>`, it returns `<Y>`."*)
- **one-line intuition** — *"takes `<X>` and MAKES `<Y>`"* — what goes in, what comes out, instantly.

## Inline code font = BACKTICKS (required — easy to forget)

Every identifier, parameter, literal, type, and command inside body/bullet text MUST be wrapped in
`` `backticks` `` — `build.py` renders those as inline code font. A plain, un-backticked code term is
a DEFECT (applies everywhere in prose, not only inside code boxes).
e.g. `` `criteria` ``, `` `"square"` ``, `` `gen_lambda` ``, `` `N // 2` ``, `` `pytest -m T1` ``.

## Build (never hand-author HTML)

Assemble the sections as gws-richdoc blocks (`banner`, `section_box`, `code`, `body`, `bullets`,
`tip`) and render with `build.make(...)` (new) / `build.rebuild(...)` (in place). The look is fixed in
`build.py`; only the text changes.

## Used by / pairs with

- <course> `git-assignment` (conductor) → global `git_page.py` (this dir, the builder). Any course's git-program build.
- Generic method: `assignment-page-builder/SKILL.md` — this file is the code-type **delta**, invoked
  when the dispatched type is a GitHub/program assignment.
