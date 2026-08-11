---
name: agenda-wrapup
description: "GLOBAL — generate the weekly Agenda (week start) and Wrap-up (week end) Canvas pages for a module, from the same module data. Config-driven per course (course_slug -> course_config). Triggers: 'week N agenda', 'wrap-up for week N', 'update the agenda', 'make the week 3 agenda/wrapup'."
---

# Weekly Agenda + Wrap-up pages (GLOBAL, config-driven)

Two Canvas **PAGES** per week/module, both derived from the **same module data**:
- **Agenda** (week start): what to do this week.
- **Wrap-up** (week end): the same to-dos as a checklist + what you learned + confirm you finished.

The Wrap-up is the Agenda's to-do list, condensed and recast — so generate both from one module read.
Reference origin: <course> `.claude/code/gen_agenda.py` + `workflows/45weekagenda.md` (<school>; that was a
per-course `requests` script — this uses the central `canvas_rest` instead).

## Shared core — read the module ONCE

1. **Find the module** for the week: `canvas_rest.list_modules(base, tok, cid)` → match the week in the
   name (`[Week N]`, `Week N`, `👉 Week N`, …); a week can span multiple modules → collect all. (Or the
   user gives the module id directly (usually they do). Per-course week↔module ids are not stored here —
   pass the module id, or keep a map in that course's `input/course-info.md` if you want one.)
2. **Read items:** `canvas_rest.get(base, tok, f"/courses/{cid}/modules/{mid}/items")`.
3. **Categorize** (item `type` + SubHeader labels): Readings/OER, Video lectures, Lecture slides,
   Jupyter/practice, Labs, Assignments, Quizzes, Exams. **Skip** existing Agenda/Wrap-up Page items
   (we're regenerating those).
4. **Due dates:** each Assignment item → `fetch_assignment(base, tok, cid, content_id)["due_at"]`; each
   Quiz item → `fetch_quiz(base, tok, cid, content_id)["due_at"]`. **Convert with
   `canvas_rest.to_localtime(due)` — NEVER show raw UTC** (this Canvas = CCC / California). Null → "No due
   date set".

## Render — Agenda (week start), 3 sections

1. **This week's to-dos** — what to **read**, what to **practice**, **further reading / references**
   (pulled & condensed from the module's pages/readings).
2. **Graded — do these** — assignments / quizzes / exams, each with its **due date in PDT/PST**.
3. **Closing** — a short encouragement, an easy "reach out anytime" line, kind words.

## Render — Wrap-up (week end)

Same to-do list, recast for the end of the week:
- **Checklist** — the same items as "Did you finish this?" checkboxes.
- **This week you learned …** — a short summary built from the categories/topics covered.
- **Confirm** — ask the student to confirm they completed everything.
- **Closing** — encouragement + easy contact.

## Style + policy (non-negotiable)

- **No emoji.** Inline/block **code font** on every code segment (see `assignment-page/SKILL.md` umbrella).
- **Dates: `to_localtime` ALWAYS.** Never raw UTC, never a hardcoded offset (ZoneInfo handles DST).
- Pages created/updated **`published: False`** — only the instructor publishes (never Claude).

## Placement — MODULE-SCOPED target selection (NEVER get_page by a guessed slug)

⛔ **NEVER `get_page(guessed_slug)` to find the page.** `get_page` RETRIEVES a KNOWN page by url — it is
NOT a search. Canvas resolves OLD url aliases (a page renamed across terms keeps its old `week-N` urls),
so a guessed slug can return a **DIFFERENT** page and you will silently **CLOBBER** it.
*Real incident 2026-07-06:* `get_page("week-4-agenda")` returned the renamed **"[WEEK 3] Agenda"** page
and overwrote Week 3 — because that page still owned the old `week-4-agenda` url.

**Find the target ONLY inside the module.** For each page (agenda, then wrap-up):

1. **Confirm the module id** (given, or matched by week name).
2. **List the module's items** (`GET /courses/:cid/modules/:mid/items`) → keep **Page** items → match by
   title ("Agenda" / "Wrap-up"). The real `page_url` comes from the **module item**, never a guess.
3. Branch on the count:
   - **exactly 1** → that is the target. **Confirm with the instructor before overwriting**, then
     `update_page(cid, item.page_url, {...})` (its REAL, in-module url).
   - **2 or more** → ambiguous → pick the `page_url` whose title matches THIS week number, **confirm**,
     then update that one. Never guess silently.
   - **0** → nothing to overwrite: `create_page(...)` → `add_module_item(..., page_url=<url create returns>)`
     (the returned url may be auto-suffixed if an alias holds the plain slug — that is fine).
4. **Wrap-up uses the same algorithm.**

`update_page` is safe ONLY with a `page_url` taken from a **module item** (or a `search_term` result) —
never a hand-built slug. A keyword search, if ever needed, is `GET /courses/:cid/pages?search_term=<kw>`
(title match), NOT `get_page`.

## Machinery — `gen_agenda.py` (this dir; use it, don't hand-build)
`build_and_place(course_slug, module_id, *, week, intro, topic_bullets, review_note, closing, learned)`
reads the module ONCE → builds the rich Agenda + Wrap-up HTML (Week-3 house format: bold intro, h3
sections, **navy Graded table `max-width:900px` — NOT 100%** — with due via `to_localtime` + Total,
inline code font, `modules/items/<id>` links) → **MODULE-SCOPED placement** (find the page IN the module,
update its real url; 0 → create+add — never `get_page(guessed_slug)`) → **saves HTML to
`.claude/output/Canvas-Pages/`**. Per-week prose (`intro/topic_bullets/review_note/closing/learned`) is
passed in; everything mechanical is fixed in code. NEVER hand-build the HTML inline (it is thrown away).
- **`topic_bullets` and `learned` are LISTS** (one string per bullet). A bare string is coerced to a
  1-item list — passing a plain string used to iterate char-by-char and render one bullet **per letter**.
- **`place_ends=True` (default)** puts the **Agenda at the TOP** of the module and the **Wrap-up at the
  BOTTOM** automatically (Canvas renumbers on each move, so it re-reads before placing the wrap-up).
  Pass `place_ends=False` to leave both appended at the module end.
- **`exclude_content_ids=[…]`** — assignment/quiz ids the agenda must NOT list. The module item is left
  exactly as it is (still there, still unpublished) — this only stops the page telling students to do
  it. Use it instead of deleting or unlinking an item.
- **`also_graded_from=[module_id, …]`** — fold ANOTHER module's graded items into this agenda's table.
  The last week of a term owns the final-exam module's quizzes even though they sit in their own
  module; the Agenda/Wrap-up pages are still created in `module_id` only, never in the extra module.

## Tools (all `canvas_rest`)

`list_modules` · `get` (module items) · `fetch_assignment` · `fetch_quiz` · `to_localtime` ·
`get_page` · `update_page` · `create_page` · `add_module_item`.
**Course coordinates (course_id, base, token_env, output_dir) come from `course_config.load(<course_slug>)`** —
`gen_agenda.build_and_place(course_slug, module_id, …)` resolves them; nothing is hardcoded. Links are relative.

## Reference
- <course> `gen_agenda.py` + `45weekagenda.md` — origin (categorization + `to_localtime` idea).
- Canvas style policy (no emoji, code font, API upload, `published:false`) — `CourseGlobalWorkflow/Access/Canvas.md`.
- Per-course config = `course_config.load(<course>)`; term links (per course) = that course's `input/course-info.md`.
