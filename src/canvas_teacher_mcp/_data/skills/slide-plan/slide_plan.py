#!/usr/bin/env python3
"""slide_plan.py — Skill 2: build per-slide SECTION BLOCKS for module-overview-page.

A multi-slide module reads best as ONE section per slide: the slide's content summary + the
tasks (assignments/labs) based on THAT slide, with the slide deck embedded in the section.

This helper only SHAPES authored data into the section tuple that
`module_overview.make_page` consumes: (header, summary_html, items, section_deck_id).
The AI authors each slide's title / summary_html / tasks; this file just packs them.
"""


def slide_section(title, summary_html, tasks, deck_id=None):
    """One slide -> one section tuple.

    title        : the slide/topic header (e.g. '📽️ Slide 1 — While Loops').
    summary_html : authored HTML summarizing what this slide covers (NO <code>).
    tasks        : [(kind, ref, label)] — the assignments/labs based on this slide.
    deck_id      : this slide's Google Slides deck id to embed in the section (or None).
    """
    return (title, summary_html, tasks or [], deck_id)


def slide_sections(slides):
    """slides = [{title, summary_html, tasks, deck_id}] -> [section tuple] for make_page(sections=...)."""
    return [slide_section(s["title"], s.get("summary_html"), s.get("tasks", []), s.get("deck_id"))
            for s in slides]
