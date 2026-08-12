---
name: assignment-page-builder
description: "GLOBAL methodology for building a Canvas ASSIGNMENT/LAB page from the universal skeleton `canvas_core/assignment_page_builder.py`. The skeleton is the CODE (machinery); this skill is the HOW (authoring method + finalize order). Per-course skills (e.g. CSCI-19A customize-assignment-page = git plugin, jshell-lab = jshell plugin) supply the course config + content and reuse this. Policy (grading %, published, dates) lives in CourseGlobalWorkflow and is only REFERENCED here. Use when building/updating any Canvas assignment or lab page."
tools: [build_coding_assignment_page, build_notebook_assignment_page, get_assignment, create_assignment, update_assignment]
---

# assignment-page-builder — GLOBAL page-building methodology

> **System map (START HERE): `CourseGlobalWorkflow/README.md`** — the 3 layers (local conductor / global
> builder / policy+config), per-type conductors, and the assignment-creation workflow. This skill is the
> **AUTHORING METHOD** (how to write page content + finalize order); it does not re-describe the architecture.

The pairing of:
- **CODE (machinery):** `$CANVAS_LMS_ROOT/.claude/code/canvas_core/assignment_page_builder.py` — the SKELETON.
  Universal: make the instruction gdoc in place, clean-view embeds, rich-format HTML helpers, slide embed
  (single or list), Canvas push (canvas_rest), `make_page()` orchestrator (returns `out["html"]`). **No type-specifics.**
- **BUILDERS (content):** turn an `asmt` dict into `doc_blocks` + `canvas_summary_html` and call
  `skel.make_page(...)`. **git / program → `git_page.py`** · **NB / notebook → `nb_page.py`** (both GLOBAL +
  config-driven — read `course_config.load(<course>)`, NO per-course code). Per-course plugins remain
  only for not-yet-migrated types: CSCI-19A `jshell_lab.py` (JShell lab — no global equivalent exists).
  The git/Java plugin `gh_assignment.py` was **absorbed into `git_page.py` and deleted 2026-07-31**;
  its seven course-locked features (`signature`, `what_to_complete`, `io_block`/`io_lines`/`io_table`,
  `input_spec`, `concept`, `guide_steps`, 3-level `RUBRIC_LEVELS`) are global now.
  - **flowchart lab (draw.io PNG submission) needs NO dedicated builder.** It has **no special page items**
    (no autograder test-table / restrictions / commit rubric / repo link), so a plugin would add nothing.
    Author `doc_blocks` + `canvas_summary_html` with the skeleton helpers
    (`section`/`rich_ul`/`rich_ol`/`callout`/`slide_embed`) and call `skel.make_page` directly — the
    generic page path. Only add a builder if flowchart pages later grow a genuinely shared special section.
- **THIS SKILL (how):** the authoring method + finalize order every builder follows.
- **POLICY (separate):** grading split, `published:false`, dates → `CourseGlobalWorkflow/` only (referenced, never copied here).

## ⛔ RENDERING LIVES IN THE SKELETON — a builder writes TEXT, never HTML

**Write plain text with this notation; the skeleton renders it. Never hand-build HTML in a builder.**

| Write | Get |
|---|---|
| `` `code` `` | code-font span (Canvas code-font rule) |
| `**bold**` | bold |
| `[text](url)` · a bare `https://…` | a **clickable** link |

Every helper (`rich_ul` / `rich_ol` / `rich_table` / `section` / `callout` / `page_title`) runs its text
through **`ic()`**, so the notation works everywhere — in a bullet, a table cell, a heading, a box.

| Need | Skeleton helper |
|---|---|
| bullets / numbered | `rich_ul(items)` · `rich_ol(items)` — an item may be `(label, [sub, …])` |
| table | `rich_table(headers, rows)` |
| section | `section(title, body)` · page title → `page_title(t)` |
| **highlight box** | **`callout(items, kind="warn"\|"note", title=None)`** — `warn` = yellow/bold (restrictions, "do not"), `note` = navy ("this is graded", a deadline) |
| code block | `pre(text)` |
| link in a paragraph | `link(url, text)` — *not needed inside a list/table; write the URL* |
| slide deck | `slide_embed(url_or_list)` |

**Passing real HTML into these is a MISTAKE** — `ic()` escapes it and the student sees the tags.

**If a shape is missing → ADD IT TO THE SKELETON.** Never write a private renderer in a builder.
*(2026-07-17: `git_page` held a private `_CODESPAN`/`_ic`/`_ul`/`_restrict`/`_elab`, so NB, jshell and
flowchart pages could not render backticks AT ALL — the renderer was locked inside the git builder, and
`rich_ul` merely escaped. Every new builder then grew its own copy. The copies are gone; one renderer, here.)*

## Layering (don't mix)
| Layer | What | Where |
|---|---|---|
| Code | skeleton + builders | `canvas_core/assignment_page_builder.py` + global `git_page.py` / `nb_page.py` (per-course plugins only for not-yet-migrated types) |
| **How-to (this)** | authoring method, finalize order | global skill (here) + per-course refinements |
| Policy | grading %, published, dates | `CourseGlobalWorkflow/` (GRADING.md, Access/Canvas.md) |
| Local config | course id, token, org, pages_folder, output_dir, dispatch | **`course_config.load(<course>)`** (single source) |

## Builder contract (what a builder passes to the skeleton)
The git/program builder is the GLOBAL `git_page.py` (config-driven — reads `comsc240.json`). The contract
below is what ANY builder (git_page, or a not-yet-migrated per-course plugin) hands `skel.make_page`:
- `doc_blocks` — gws-richdoc blocks for the detailed instruction doc (or None → gdoc-less, summary-only page).
- `canvas_summary_html` — the Canvas page's summary sections (built with the skeleton's rich helpers:
  `section`, `rich_ul`, `rich_ol`, `rich_table`, `code_span`, `NAVY`).
- config: `pages_folder`, `output_path`, `slide_embed_url` (str OR list), `course/assignment_id`, `base/token_env`.
- then call `skel.make_page(course_id, assignment_id, name, doc_blocks, canvas_summary_html, *, pages_folder,
  output_path, slide_embed_url=None, push_canvas=False, due_at=None, points=None, base, token_env)`.

## Instruction-gDoc NAME — it must IDENTIFY the assignment, and match the course's folder

The gDoc a builder renders into `pages_folder` sits in a shared Drive folder with every other
assignment's doc. Its name is how the instructor finds it there, so:

- **The name identifies the assignment: its CODE + its title.** Never a free-typed name, never a
  title alone.
- **Follow the naming already used in that course's Pages folder** — list the folder and copy the
  existing shape before creating. A doc that breaks the pattern is a defect: it sorts wrong and reads
  as someone else's file. The exact shape is a course fact and lives in the **L3 course wrapper**.
- **The builder assembles the name from `asmt`** (code + title); a caller should not be able to type
  a different one. *(Real failure 2026-08-01: a CS120 doc was created as `A1102 - Structure Student
  Array` while all eleven of its neighbours were `[Assignment A711] …` — the rule existed nowhere, so
  the name was invented.)*

## ★ Authoring method — write it so a beginner finishes from the page ALONE

> **CLEAR is the only acceptable bar.** A student must finish from the page ALONE. The #1 rule:
> **every example shows INPUT → OUTPUT** — the actual call/args AND its result, taken from the
> spec/slide VERBATIM and confirmed by actually RUNNING it. **Output with no input is a DEFECT, not a
> page** — it wastes the student's time (they cannot tell what produced what). If the spec already gives
> `call → output` (the slides do), use it as-is; never strip the call off.
1. **👉 GIST (one line, at the VERY top).** One plain-language sentence of WHAT to do — no types, no
   constraints, no "how". e.g. *"Read two numbers and print their sum!"* (`asmt["gist"]`). The how comes below.
   - **★ FISHING rule (applies to EVERY section, not just the top): bait first, detail on the bite.**
     Lead each section with ONE clear big-picture line — the hook — then the details underneath for the
     reader who wants more. NEVER open with a dense multi-step wall of explanation; that is the #1 way a
     doc becomes unreadable. If YOU can't state the section's point in one line, you don't understand it
     yet — find that line first. One idea per line; progressive disclosure, not a data dump.
     (e.g. a "returns a lambda" section opens with just *"gen_lambda returns a lambda (a function), not a
     list."* — the criteria table and examples follow as the detail.)
2. **Beginner-complete instructions.** Terse abstractions are a failure (*"compute x*0.62 and print"* is NOT
   enough). Every step gives concrete, copyable guidance + a **worked code example using the REAL values**
   (show 1–2 lines, leave the rest for the student). **Do NOT obfuscate with a different example value when the
   code is the same and only the value changes** — that hides nothing and confuses. (Exception: value-agnostic
   tasks where the student supplies their OWN value → a sample value like "John Doe" is correct.)
3. **[Expected Output] MUST pair INPUT → OUTPUT — never output alone.** Output with no input is useless: the
   student cannot tell which call produced what. For a FUNCTION assignment, show the actual CALL (with its
   arguments) and its result — `func(args)  ->  result` — one pair per example. **Use the spec/slide's own
   examples verbatim** (the slides already give `call → expected output`; do NOT strip the call off). For a
   stdin program, show the given input then the printed output. Render as a CODE BLOCK (`build.code` / `<pre>`)
   — never plain text (it collapses leading spaces). **RUN the function/program yourself and paste the REAL
   result** — never hand-type or guess. (Fields: `expected_output`, plus `expected_input`/`expected_return`
   when they fit.) *Real failure 2026-06-29:* a page showed only `[[1,4,7,10],...]` with no call — meaningless;
   the slide had `make_new_list([...],3) -> [[1,4,7,10],...]` all along, and it was thrown away.
3b. **[Input / Output] = the FUNCTION's contract, not the driver's stdin.** For a function assignment, describe
   the function's PARAMETERS and RETURN VALUE (e.g. *"Parameter: n (int); Return value: a generator of the
   primes less than n"*) — NOT "Input: none, set inside main()", which is a property of the `main.py` driver the
   student does not edit. If the spec names a return TYPE (generator, list, None/in-place), the test MUST check
   it (e.g. `isinstance(g, types.GeneratorType)` / AST `yield` for a generator).
4. **[Restrictions] (required).** What the student must NOT do — extracted from the slides + how the test is
   built (the test enforces them). e.g. "no input — store literals", "no loops — use substring".
5. **Test-items table.** Per grader (Compile/Run/T1..T4 or Compile + pytest T1..T4): runner · max · what it
   checks. `checks` text comes from the ACTUAL test file (never invented). Note "the autograder reports 100".
6. **outline form — ALWAYS, every section. NEVER dense prose paragraphs.** Section content
   is SHORT bullets in a HIERARCHY: a topic is a top-level bullet; its sub-points are a **nested, INDENTED**
   bullet list under it. Heavy indentation = scannable (scannable at a glance). A wrapped wall-of-text paragraph (e.g. an
   Overview or "Parameter: …; Return: …" run together on one line) is a DEFECT — break it into bullets, one
   idea per line. **Pass section content as a LIST (or nested list), not a paragraph string** — the skeleton's
   `rich_ul`/`rich_ol` render nested indented bullets; a `(label, [sub, sub])` tuple becomes a bold label + an
   indented sub-list. Plugin convention: `overview`, `io` (Parameter/Return lines), `what_to_complete`,
   `restrictions` are LISTS → bullets; only Expected Output stays a code block. Mirror the per-course
   canvas-assignment format note (uniform nested `<ul>`, hierarchical). Navy `#1F3864` headers, monospace code,
   shaded table headers come from the skeleton helpers.

## ★ FINALIZE — canonical order (global 1·2·3·4; a course may refine to 3-1·3-2…)
1. **Find the Canvas item id** (by id, or look up by name).
2. **Fetch + BACK UP the existing description, then OVERWRITE** (not merge). The skeleton's `push` saves the old
   description to `/tmp/asmt_<id>_desc.backup.html` and replaces it. (Backup = the old content is safe.)
3. **Set attributes** from input: due_at, points_possible. **NEVER set `published`** — stays unpublished;
   only the instructor publishes.
4. **Place in the module** if not already there (`add_module_item`, end of module; instructor reorders).
5. **Share every embedded gdoc/slides anyone-with-link (reader)** so the embed renders. (gws-richdoc `make`/
   `rebuild` already forces this for the instruction doc; check slide decks.)
6. **Warn if an embedded file lives OUTSIDE the course's Drive folder** (don't move it — tell the instructor).

## Policy — referenced, NOT stored here
- **Grading split** (e.g. git: 50% autograder / 20% elaboration / 20% commit / 10% link → actual points) →
  `CourseGlobalWorkflow/GRADING.md`. Convert % to real points for the assignment's `points_possible`.
  - **★ Points = INPUT, weights = RATIO. To change an assignment's total, pass `points=N` only** — `git_page`
    distributes it by `rubric_weights` (auto/elab/commit/link, summing to 100). **Never hardcode per-assignment
    point numbers**; adjust the `points` arg (and, if the emphasis changes, the `rubric_weights` %). e.g. an
    elaboration-heavy homework: `points=80, rubric_weights={auto:37.5, elab:31.25, commit:25, link:6.25}`.
- **Canvas policy** (published=false; dates PST/PDT via `canvas_rest.to_localtime`; backup-then-overwrite) →
  `CourseGlobalWorkflow/Access/Canvas.md`. PolicyScope: policy read from outside CourseGlobalWorkflow is
  discarded — so this skill only points to it.

## Slide embeds — use the GIVEN URL verbatim
Reuse the assignment's existing embed URL(s) unchanged — never re-pick the `slide=id.<objectId>` page.
`slide_embed_url` accepts a single URL or a LIST (a lab/assignment spanning several slides).
`git_page` places the slide embed(s) at the **TOP** of the Canvas summary (right under title + gist) for
intuition-first, NOT appended last. Order in the list = order shown.

## git_page asmt fields — special renderings (COMSC240-proven)
- `restrictions: [str,…]` → a **yellow bold** highlight box (forbidden functions must stand out).
- `elaboration: [str,…]` → a **navy emphasis box** listing exactly what the student must write (the
  elaboration is graded; spell it out — algorithm detail, map/zip usage, correctness for all inputs,
  errors/fixes). Use whenever elaboration carries real weight.

## Per-course plugins that use this skill
- **CSCI-19A `customize-assignment-page`** (git program assignment) — an L3 POINTER now; the page is
  built by the global `git_page.py` (the local plugin was absorbed 2026-07-31). Course config +
  git-specific content; pairs with `git-homework` (which owns the repo + tests, incl. multi-input / pytest-parser).
- **CSCI-19A `jshell-lab`** (JShell lab) — `jshell_lab.py`. Lab content; grading in `GRADING.md Part E`.

## Per-type instruction-doc format (pinned section templates)
The generic authoring method above is shared, but the instruction doc's **pinned section order + names**
are TYPE-SPECIFIC — a plugin builds `doc_blocks` following its type's format file (this dir):
- **CODE / GitHub-program** assignment → `program-assignment-format.md`.
- **NB / Colab notebook** assignment → `nb-assignment-format.md`.
- Other types (jshell lab, essay, …) → their own plugin's structure.

**Inline code / parameters = `` `backticks` `` in body/bullet text** (both formats) → `build.py` renders code font.

## Reference
- Code: `canvas_core/assignment_page_builder.py` (skeleton) · the plugins.
- Policy: `CourseGlobalWorkflow/GRADING.md` · `CourseGlobalWorkflow/Access/Canvas.md`.
- Access layers: `code/playbook/canvas-github-access-layers.md`.
