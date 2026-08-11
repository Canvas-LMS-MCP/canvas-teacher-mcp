---
name: module-overview-page
description: "GLOBAL, config-driven — build a module OVERVIEW page (the representative page at the top of a Canvas module): 📌 Overview (the plan) + an optional slide embed + FLEXIBLE SECTION BLOCKS grouping that module's items (readings/videos/quizzes/assignments) as a roadmap. Categories are DATA — add/remove freely per course, no fixed columns, no wrappers needed. Renderer = module_overview.py (coords from course_config.load(<course_slug>)). For per-slide breakdowns it uses the slide-plan skill. Triggers: 'module overview page', 'make the overview/representative page for module N', '대표 페이지'."
---

# module-overview-page — GLOBAL module overview page (Skill 1)

> ⛔ **READ FIRST: this skill reuses the `assignment-page-builder` skeleton** (`section` / `slide_embed` /
> `embed_block` / `NAVY`). Read `assignment-page-builder/SKILL.md` before building — the embed & renderer
> rules live there and are NOT duplicated here: **passing raw HTML into a helper (e.g. a raw `<iframe>` in
> a section's `summary_html`) is a MISTAKE** — embeds go through `slide_embed`/`embed_block` only, and an
> existing slide's URL is **reused verbatim** (never copy the old iframe). Skipping that read is how a
> session ends up hand-pasting a raw embed.

The page at the **top of a Canvas module** that gives students the plan: **📌 Overview** + (optionally)
the module's **slide deck**, then a **roadmap** of everything in the module grouped into flexible
**section blocks**. Goal: *summarize the module/slides and hand students a concrete "here's what you do."*

## One GLOBAL skill — no wrappers
`module_overview.py` is fully **config-driven**: pass `course_slug`, coords resolve from
`course_config.load(<course_slug>)` (`canvas_base_url`, `course_id`, `canvas_token_env`). Course
values that aren't coordinates (a page stylesheet URL, slide-source folders) go in that course's config
or are passed as arguments. **No per-course wrapper is made** — add one later only if a course needs
genuinely special handling.

## Design — flexible section blocks (categories = DATA)
```python
from module_overview import make_page
make_page(course_slug, slug, overview_html, sections, *,
          deck_id=None, stylesheet=None, push=False, backup_dir="<scratchpad>")
```
- `sections = [(header, summary_html|None, items, section_deck_id|None), ...]`  (2..4-length tuples ok)
- `items = [(kind, ref, label), ...]`, `kind ∈ {assignment, page, quiz, url, text}` → native Canvas
  link dispatch (assignment/quiz id, page slug, external url, or plain text).
- **No fixed columns.** A category that doesn't apply just isn't in `sections`. Empty → nothing shown.
- `deck_id` = page-level deck (single-slide module). `section_deck_id` = per-section deck
  (multi-slide module — see the `slide-plan` skill, which builds one section per slide).
- **A deck ref is a FULL embed URL or a bare presentation id.** A full URL is passed **verbatim** to
  `slide_embed` (so an existing page's embed — incl. a published `/d/e/2PACX…/embed` — is preserved);
  a bare id is wrapped with `DECK_EMBED`. Never slice a URL down to an id (matches `git_page`/`build`).

## Flow
1. **Inventory the module** (source of the roadmap = the REAL Canvas module, not the slide text):
   `python3 -m canvas_core.canvas_link_extractor <course_id> module:<id>` or the module-items API.
   Group items by the module's own SubHeaders into `sections` (📙/🎥/💯/⬆️ …).
2. **AUTHOR** (the AI's only job — judgment + data):
   - `overview_html` — 1-2 `<p>`: what the module teaches + the "read/watch → practice → submit" arc.
     Read the real slide/page/assignment content so it's concrete, not generic. **NO `<code>`** (a
     linked stylesheet can break it — use `<b>`/plain).
   - `sections` — the grouped items. Add per-section `summary_html` / `section_deck_id` for
     per-slide breakdowns (delegate that authoring to the `slide-plan` skill).
3. **Build + PUT** (dry first): `make_page(..., push=False, backup_dir=...)` → review → `push=True`.
   Backs up the FIRST original body; **never sets `published`**. Verify `status==200`, `published==False`.

## What is CANON vs AUTHORED
- **Canon (never hand-roll):** the section/link/embed render + PUT (= `module_overview.py`, reusing
  `assignment_page_builder` `section`/`slide_embed`/`NAVY` + `canvas_rest`).
- **Authored (the AI writes only this):** `overview_html` + the `sections` grouping/summaries.

## Sub-skill
- **`slide-plan`** (Skill 2) — builds per-slide sections ("this slide covers X → do these tasks").
  Skill 1 calls it for multi-slide modules; each returned section carries its `summary_html` +
  `section_deck_id` + task items.

## Lessons baked in
- No `<code>` (page stylesheet breaks it). `%`→`%%` in `%`-format strings. Back up the FIRST original
  body only. Embed helper is `assignment_page_builder.slide_embed` (old `_slide_embed` removed).

## Change-trigger
Downstream of its module + decks. Rebuild when a deck is re-copied or an item is added/removed/renamed.

## History
Extracted 2026-07-10 from the CSCI-19A Ch3 build; generalized to GLOBAL + section-block API + renamed
`chapter-slide-page`→`module-overview-page` on 2026-07-18 (categories = data, no wrappers).
