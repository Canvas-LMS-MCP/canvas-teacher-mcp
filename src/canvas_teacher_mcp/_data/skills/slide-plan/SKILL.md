---
name: slide-plan
description: "GLOBAL sub-skill of module-overview-page — turn a multi-slide module into one SECTION per slide: 'this slide covers X → do these assignments/labs based on it', with the slide deck embedded in that section. Returns section tuples that module-overview-page's make_page consumes. Use when a module has SEVERAL slide decks and you want each slide's content summarized next to the tasks derived from it. Triggers: 'slide plan', 'per-slide breakdown', 'slide N covers … do …'."
---

# slide-plan — per-slide section blocks (Skill 2)

Sub-skill of **`module-overview-page`** (Skill 1). When a module has **multiple slide decks**, each
slide reads best as its own section: **what the slide covers** + **the assignments/labs based on it**,
with **that slide embedded** right there.

## Model
```python
from slide_plan import slide_sections
sections = slide_sections([
  {"title": "📽️ Slide 1 — While Loops",
   "summary_html": "<p>Covers the while-loop pattern: condition, update, sentinel stop.</p>",
   "tasks": [("assignment", 1314443, "Assignment 5-0 — Power Number"),
             ("assignment", 1314445, "Assignment 5-1 — Input Validation")],
   "deck_id": "<SLIDE_1_DECK_ID>"},
  {"title": "📽️ Slide 2 — For Loops", "summary_html": "<p>…</p>",
   "tasks": [("assignment", 1314447, "Assignment 5-3 — Count Random")],
   "deck_id": "<SLIDE_2_DECK_ID>"},
])
# then hand `sections` to Skill 1:
#   make_page(course_slug, slug, overview_html, sections, deck_id=None, ...)
```
Each dict → a `(header, summary_html, tasks, deck_id)` section. `tasks` items = `(kind, ref, label)`
(`kind ∈ assignment/page/quiz/url/text`) — the SAME item shape Skill 1 renders.

## What is AUTHORED vs CANON
- **Authored (the AI):** each slide's `title`, `summary_html` (read the real deck to summarize it —
  concrete, NO `<code>`), and which `tasks` derive from it.
- **Canon:** the packing (`slide_plan.py`) + the rendering/embedding (Skill 1's `module_overview.py`).

## How it fits
Skill 1 (`module-overview-page`) drives the page; for a multi-slide module it calls this to produce the
`sections`. A single-slide module doesn't need this — Skill 1 uses a page-level `deck_id` + plain
category sections instead.
