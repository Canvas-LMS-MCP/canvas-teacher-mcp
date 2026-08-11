---
name: nb-homework-create
description: >
  Create/prepare an NB (Colab / Jupyter) homework TEMPLATE so it can be graded cleanly by the
  `grade-nb` sub-skill. Embeds a hidden per-cell ANCHOR in every instruction + provides a matching
  pre-filled ANSWER cell, structures the notebook into sections with a per-section pin + an essay
  reflection, and bakes the student "do not delete the cells" guidance. The creation and grading
  sides are mirror images — the grader anchors on exactly what this skill stamps. Global; pairs with
  `skills/grade-nb`.
tools: [create_notebook_homework, build_notebook_assignment_page]
---

# nb-homework-create — build an NB template the grader can anchor

**⛔ READ `skills/grade-nb/SKILL.md` FIRST.** Creation and grading are mirrors: the grader resolves a
question by its anchor (`@answer` → `@anchor` → instruction text → position). If you don't stamp the
anchors + answer cells here, the grader falls back to fuzzy/positional matching and flags for manual
review. Stamp them, and grading is deterministic. Policy homes: `GRADING.md Part C` + `NbInspect.md`.

## 1. Anchor the PROBLEM cells (anchor-only; answer = the REGION after it)
Every gradeable problem's instruction (markdown) carries a hidden anchor in its SOURCE — invisible in
the Colab render, preserved across "Save a copy" (more robust than cell metadata, which Colab reassigns):
```
[problem — markdown]   <!-- @anchor:P3.1 type=code -->   #### Problem 3.1  complete the function …
```
- **Anchor = "grade HERE".** Use the instructor's OWN problem number as the id (`@anchor:P3.1`,
  `@anchor:E2` for "Exercise 2"). `type=code|explain` is a SOFT hint (not a hard gate). Also write the
  nbgrader `grade_id` into metadata for tooling.
- **No separate `@answer` cell, no inserted cell.** The answer = the REGION from this anchor to the NEXT
  anchor — whatever the student writes there (a code cell, an edited "Answer here", added cells) is
  included, and the grader judges code AND explanation together against what the problem asks.
- Stamp ONE anchor per REAL problem; SKIP global "run all cells / figure out" instruction cells and pure
  examples. Stamper = `nb_create.py stamp --manifest <AI-judged problem list>` — **READ the template and
  judge which cells are problems; do NOT keyword-guess** (keyword auto-detect is noisy — proven on ch03).
- **Anchor = a cell the STUDENT fills (graded for correctness). A pre-filled example / run cell needs NO
  anchor** — completeness (`nb_inspect`: executed ÷ non-blank code cells) already enforces "run every cell".
  BUT a blank "type it yourself" slot left un-anchored is EXCLUDED (`_is_blank_code`) → graded NOWHERE;
  to make active-typing practice gradeable + tested, ANCHOR it (with an expected-output line).

## 1b. ⛔ CELL INSTRUCTION QUALITY — the notebook is the ONLY document the student gets

There is **no gDoc for an NB assignment** (`grade-nb`: *"the template notebook IS the instruction
source"*). A second document would go stale against the notebook and the grader never reads it. So
everything a beginner needs must be IN THE CELL. A problem cell that only says *"Let's multiply 24.0
and 25.4"* above `result = ...` fails them: they cannot tell what to type, and cannot tell whether
what they got is right.

**Every `problem` cell carries all four:**

| # | Required | Bad | Good |
|---|---|---|---|
| 1 | **Goal, one line** — what this cell produces | "Let's divide 100 by 20" | "Divide 100 by 20 and print the result as a whole number." |
| 2 | **How** — the operator / function / variable to use, named | (nothing) | "Use the floor-division operator `//`." |
| 3 | **Expected output** — so the student can self-check | (nothing) | ``Expected output: `5` `` |
| 4 | **Where the answer goes** | `#### Your answer here` | "Double-click the markdown cell below and type your answer there." (explain-type) |

**Answer-slot rules — ⛔ EVERY answer cell must PARSE as Python before you ship it**

An answer slot that raises `SyntaxError` on the student's first run teaches them nothing but panic,
and it can't be graded (a cell that never runs has no output to judge). Test the shape, don't assume:

| Shape | Parses? | Verdict |
|---|---|---|
| `result =   # your expression here` | **NO — SyntaxError** | ⛔ an assignment needs a right-hand side; the comment is not one |
| `lname = # complete this code` | **NO — SyntaxError** | ⛔ the original ch02 shape, in 8 cells |
| `# complete this code = 100` | yes (it's just a comment) | ⛔ not Python; students copy the shape |
| `result = ...` | yes | ⛔ runs and prints `Ellipsis` — a beginner reads that as success |
| **`result = 0   # <-- replace 0 with your expression`** | yes | ✅ **use this** — runs, and the obviously-wrong `0` shows it is unfinished |
| **`# your code here`** (whole cell) | yes | ✅ use this when the student writes the whole block (drills) |

Pick a placeholder value of the right TYPE (`0`, `0.0`, `''`, `[]`) so the cell runs end to end.
**Verify mechanically before shipping: `ast.parse` every code cell.** Also fix typos in any cell you
touch (`varibles`, `repectivelu`, `Calcurate`, `seprated` …). *(Both wrong shapes shipped in <course>
ch02; the `=  #` one was introduced by this very skill's earlier wording — 2026-08-02.)*

**Practice + a final DRILL section (this is what `enrich`'s `add` is for)**
- After each real problem, add **one PRACTICE problem** — same concept, different numbers — so the
  idea is repeated while it is fresh. Practice keeps the body's teaching register (`How.` names the
  operator/function), because the concept was just introduced.
- **Do NOT scatter harder problems through the body.** Combining problems mid-chapter breaks the
  teaching flow. Put them ALL in a **final section** — *"Putting It Together"* — a comprehensive
  DRILL that makes the student connect what the chapter taught.
- **The drill's register is different, and this is the point:**

  | | Body problem / practice | Final drill |
  |---|---|---|
  | States the goal | yes | yes |
  | Names the operator / function to use (`How.`) | **yes** | **NO** |
  | Skeleton code, variable names, hint comments | sometimes | **NO — an empty cell only** |
  | Expected output | yes | **yes** (keep it: the student self-checks, and it is the grader's correctness signal) |

  A drill cell is: a short real-world situation, what to print, the expected output — then
  `# your code here`. The student must recall the tool themselves; that recall IS the assessment.
- **Scope the drill to what the chapter actually taught.** For an intro chapter (arithmetic,
  variables, output, input, strings) a drill may combine 2–3 of those and reuse a computed value.
  It may NOT need `if`, loops, functions, lists, files, or exceptions — anything not yet taught is a
  trap, not rigor (mirrors `git-asmt-repo` §3: only test what the instruction states).
- Size: **one drill item per body section** (5 sections → 5 drills), then a pin + a reflection
  ("which idea in this chapter was the most confusing?").
- **Every practice and drill item gets an `anchor`, so all are GRADED.** An un-anchored blank slot is
  graded NOWHERE (§1). Adding problems changes the completeness denominator `N` — rebuild the
  manifest and re-confirm the assignment's points with the instructor.

**⛔ SHIP THE TEMPLATE CLEAN — every cell UNEXECUTED (no `outputs`, `execution_count: null`).**
Running the example cells is itself a GRADED item: `grade-nb` scores completeness as *"every EXAMPLE
cell run (has `execution_count` + `outputs`)"*, and a pre-filled `code` cell is graded on
**completeness only** — "did they run it". So a template shipped WITH outputs
- hands the student the results without their running anything, and
- can read as already-executed, so the completeness signal is gone.

`nb_create.py` strips outputs on write (`clean_outputs`). Verify before the push: no cell has
`outputs` or an `execution_count`. *(ch02 was about to be shipped with 5 of 69 cells executed —
caught 2026-08-02. `01-strings_1` being 0-of-31 was CORRECT, not a defect.)*

## 2. Section structure — pin + essay per section (builds the graded PROCESS)
Lay the notebook out in SECTIONS. Each section, in order:
1. Section header (markdown) + instruction cells (anchored) + worked examples.
2. Student task(s) → the anchored answer cell(s).
3. **An essay REFLECTION question** — an `@anchor … type=explain` instruction + its `@answer` markdown
   cell — that makes the student PAUSE and write the section's lesson/takeaway before moving on.
4. A markdown note: **"File → Save and pin revision → name it 'Section N'."**
→ This is exactly what `grade-nb` scores: pinned-per-section revision history (real time gaps) +
per-section reflection. The structure MANUFACTURES the process signal.

## 3. Student guidance baked into the template (wording matters)
Put a banner at the TOP and a short note per section. **Do NOT reveal the auto-grader or say
"auto-grading is impossible."** Use this register:
- "Write your answers ONLY inside the provided answer cells. **Do not delete or recreate the provided
  cells** (the instruction cells and the answer cells)."
- "If a provided cell is deleted or replaced, **your work in that part may be excluded from grading.**"
- **Recovery (always include):** "Accidentally deleted a cell? Open a FRESH copy of the template from
  the assignment link and paste your work into the matching answer cells — or use Colab **File →
  Revision history** to restore the earlier version. Do not rebuild cells by hand."
- "Save and **pin a revision at the end of each section** (File → Save and pin revision)."

## 4. Build / stamp the anchors — the creation CODE
**Location: `$CANVAS_LMS_ROOT/.claude/skills/nb-homework-create/nb_create.py`** (in THIS skill dir —
the ONE creation-side driver, mirror of grade-nb's single `grade_nb_skill.py`; named so it's never
confused with the grading driver or the operational engine tree). Four subcommands —
`build` / `enrich` / `prune` / `stamp`:
- **`build <spec.json> -o out.ipynb`** — assemble AI-authored cells (problem/answer/reflection, optionally
  onto a `base` notebook), then anchor them via `stamp_manifest`. **THE path for new templates** (incl.
  adding sections to a copied base — the AI authors the cell content as data; the tool splices + stamps).
  Spec items → what each becomes, and **which of the two gradings it lands in**:

  | item | cell(s) made | graded as |
  |---|---|---|
  | `section` / `markdown` | headers + prose | — (not graded) |
  | **`code`** | a **pre-filled, runnable EXAMPLE** cell — anchor NOT stamped | **completeness only** ("did they run it", `executionInfo`) |
  | `problem` | instruction (anchored) + a blank answer cell | **correctness** (the answer region is judged) |
  | `reflection` | an `type=explain` prompt + answer cell + a Save-and-pin note | correctness (the takeaway) |

  **`reflection` takes `title` + `pin`** — `title` names the section in the heading
  (`### Reflection — Section 3: Missing Data`), `pin` is the exact revision name the student must
  type (`name it `Section 3``). PASS BOTH: §2 wants one pin per section and the grader matches pins
  to sections, so a generic "name it for this section" leaves the student guessing the name.

  **`code` vs `problem` is the §1 line:** the answer is GIVEN and the student only RUNS it → `code`
  (a pre-filled example needs NO anchor). The STUDENT must fill it → `problem`. Never wrap a
  worked example as a `problem` — that stamps an anchor and grades a cell whose answer you supplied.
- **`enrich <spec.json> -o out.ipynb`** — **THE path for an existing chapter notebook.** Rewrites a
  problem's instruction + answer slot IN PLACE (§1b) and inserts practice / challenge problems right
  after it, anchoring every one. `build` only APPENDS to the end, which cannot fix problems that are
  already interleaved through the chapter.
  ```json
  {"base": "ch02.ipynb", "banner": true,
   "enrich": [{"find": "Problem #1.3", "anchor": "P1.3", "type": "code",
               "instr": "#### Problem #1.3\nDivide 100 by 20 ... Expected output: `5`",
               "answer": "result =   # your expression here\nresult",
               "add": [{"problem": {"anchor": "P1.3p", "instr": "... practice ...", "answer": "..."}},
                       {"problem": {"anchor": "P1.3x", "instr": "... challenge ...", "answer": "..."}}]}]}
  ```
  `find` must match EXACTLY ONE cell (it raises otherwise). Every key but `find` is optional — give
  `instr` alone to only fix wording, `add` alone to only append practice.
  **`absorb: N`** deletes the N markdown cells that FOLLOW the instruction cell. A chapter notebook
  usually splits one problem over several cells (a `Problem #1.3` header, then a separate
  *"Let's divide 100 by 20 …"* line); rewriting only the header leaves the OLD wording sitting
  between the anchor and the answer slot, so the student reads two conflicting instructions. Fold
  that text into your `instr` and absorb the leftovers. **Check the cell layout of each problem
  before writing the spec** — the count is per-problem, not global.
- **`prune <in.ipynb> --match "<text>" [--dry] [-o out]`** — **delete template cells the other three
  subcommands cannot remove.** `build` appends, `enrich` rewrites in place, `stamp` annotates; none of
  them deletes, so a template rewritten from an older base keeps the older base's cells alongside the
  new ones and the two can contradict each other. Markdown cells only unless `--any-type` is passed
  deliberately — a stray code cell may be an answer slot a student has already filled. Every dropped
  cell is printed; `--dry` shows them without writing.
  **Why it exists:** `01-strings_1`'s 2026-08-02 rewrite gave all 7 sections a correct pin prompt but
  left the January notebook's own three pin cells in place, so sections 4, 6 and 7 each told the
  student to name the same revision `Section 1`, `Section 2` and `Section 3`. It was a <course> student
  who noticed, mid-assignment. **After any `enrich` onto an existing base, grep the result for the old
  base's instruction wording** — the contradiction is invisible until someone reads both cells.
  ```
  nb_create.py prune 01-strings_1.ipynb --match "Rename the current pinned revision" --dry
  ```
- **`stamp <in.ipynb> [--manifest m]`** — anchor an EXISTING template's problem cells (retrofit).
Existing templates (e.g. `<org>/PythonCH03/ch03.ipynb`) have NO anchors. Run the stamper to inject
`@anchor`/`@answer` (source comments) + `grade_id` (metadata) into instruction/answer cells, and to
insert missing answer cells + section pin/essay prompts. New templates are built stamped from the start.

## 5. Mirror with `grade-nb` (bidirectional link)
- THIS skill STAMPS: `@anchor:P#.#` on each PROBLEM cell (anchor-only) + `grade_id`.
- `grade-nb` RESOLVES per student, **REGION-based** (never mis-grades, never crashes):
  1. Locate the anchor: `@anchor` tag → (legacy student, no anchor) instruction TEXT **CONTAINS**.
  2. Answer = the REGION `[this anchor + 1 .. NEXT anchor]` — student-added cells included.
  3. Not located → `needs_ai_read` (the inline AI reads/locates it) → instructor flag ONLY if the AI
     also can't. Proven crash-safe (anchors present / all removed / cells deleted / empty notebook).
- Deleting cells is a graded-risk for the student, never a silent zero and never a grader crash.

## 6. Canvas PAGE — rubric TABLE + grading guide + submission spec (REQUIRED — removes ambiguity)
The Canvas assignment page (built via `assignment-page`) MUST carry these, so grading is not ambiguous
and students submit correctly. **ch03/Lab Ch3 failed this** — no rubric on the page, and it never said
WHERE the per-section summary goes → students wrote one overall blurb in the body → Reflection
under-scored. Do NOT repeat that.

**(a) Rubric TABLE — formatted (real HTML table, inline Courier per the <course> code-font rule).**
Keys MUST be the engine's `comp / rev / refl` — that is what `grade_engine/graders/nb.py` scores.
Example for a 50-pt lab:
| Item | Pts | What earns it |
|---|---|---|
| Completeness (`comp`) | 25 | Every problem solved + every example cell RUN with output |
| Revision process (`rev`) | 10 | Pin a revision per section; realistic time gaps; NO copy-paste / burst |
| Reflection (`refl`) | 15 | A short takeaway of your work + roughly how long it took (rough time is fine) |

**(b) "How this is graded" — FORMAL, student-facing (state EXPECTATIONS only, in official language):**
- *Completeness* — complete every problem and run every cell so its output is shown.
- *Revision history* — as you work, **Save and pin a revision at the end of each section**; your
  revision history is part of your grade (it shows your work developed over time).
- *Reflection* — include a short summary of what you learned and roughly how long it took.
- *Process over result* — passing the tests alone is not full marks; show your work, and **do not
  copy-paste code or submit work you did not do yourself.**

⛔ **Do NOT put the authenticity-DETECTION policy on the page.** How revision timing / pinned-revision
server times are used to flag copy-paste or AI assistance (the 괘씸도 lever) is the **AI's Stage-B
grading policy** — it lives ONLY in `GRADING.md Part C §4b` + <course> `CLAUDE.md`, is used by the AI
when grading, and is **NEVER shown to students** (revealing it teaches evasion).

**(c) Submission spec — say WHERE each part goes:**
1. Colab link **shared as Editor** (a Viewer/restricted link cannot be graded).
2. Revision-history **screenshot** (File → Revision History).
3. **A short summary/takeaway + a rough time estimate** (a per-section note is welcome, but a rough
   overall is fine) → PICK ONE location and STATE it: the Canvas submission text box, OR a designated
   `## Reflection` markdown cell at the end of the notebook. (Leaving the location unstated = the ch03
   failure.)

The template's anchors (§1) + this page's rubric/guide MUST agree — the grader (`nb.py` → `nb_inspect` +
region resolution) reads exactly what the page tells the student to produce.

## See also
- `skills/grade-nb/SKILL.md` (the grading mirror) · `GRADING.md Part C` · `GradingEngine/NbInspect.md`.
- Canvas page for the assignment: `skills/assignment-page` / `assignment-page-builder` (the page links
  the template + states the rubric); this skill produces the NOTEBOOK, not the Canvas page.
