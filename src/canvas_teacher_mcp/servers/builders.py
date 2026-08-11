"""Authoring tools — the page and document builders.

These wrap several code packages rather than one, because they are one job: turning a
specification into the page a student reads. The tool names say what the page IS, not which
module builds it — a client's model reads the name and nothing else.

Every builder renders by default and only writes to Canvas when `publish_to_canvas` is set; even
then the page is created UNPUBLISHED, and the instructor publishes.
"""

from __future__ import annotations

from ..pages import git_page as _git_page
from ..pages import nb_page as _nb_page
from ..richdoc import build as _richdoc

TOOLS = ("build_coding_assignment_page", "build_notebook_assignment_page", "build_rich_doc",
         "build_weekly_agenda", "build_module_overview", "plan_slide_sections",
         "create_notebook_homework")


def build_coding_assignment_page(course: str, assignment: dict, points: float,
                                 due_at: str | None = None, rubric_weights: dict | None = None,
                                 publish_to_canvas: bool = False) -> dict:
    """Build the Canvas page for a programming assignment whose starter repo is on GitHub.

    `assignment` carries the content: code, title, gist, spec, restrictions, elaboration,
    test_items, and either `prototype` + `params` + `returns` (a function to write) or
    `input` + `output` + `expected` (a program reading stdin). Read the `git-asmt-page` skill
    before filling it — the field list and the section order are its subject.

    Returns the rendered HTML; with `publish_to_canvas` it also creates the Canvas assignment.
    """
    return _git_page.git_page(course, assignment, points=points, rubric_weights=rubric_weights,
                              push=publish_to_canvas, due_at=due_at)


def build_notebook_assignment_page(course: str, lab: dict, points: float | None = None,
                                   due_at: str | None = None,
                                   publish_to_canvas: bool = False) -> dict:
    """Build the Canvas page for a Colab/Jupyter notebook assignment.

    `lab` describes the notebook. The rubric TEXT is derived from the notebook itself; only the
    weight split is a default. Read the `nb-homework-create` skill first.
    """
    return _nb_page.nb_page(course, lab, push=publish_to_canvas, due_at=due_at, points=points)


def build_rich_doc(blocks: list, name: str, folder_id: str | None = None) -> dict:
    """Build a formatted Google Doc — banners, section boxes, callouts, coloured code blocks.

    `blocks` is the document's content in the generator's block form; read the `gws-richdoc`
    skill for the shapes. `folder_id` is a Drive folder; omitted, the doc lands in the default
    location and the answer says where.

    Needs the `gws` CLI on this machine; without it the call fails with that message rather than
    producing a broken document.
    """
    return _richdoc.make(blocks, name, folder_id=folder_id)


def build_weekly_agenda(course: str, module_id: int, week: str, intro: str,
                        topic_bullets: list[str], review_note: str, closing: str,
                        learned: list[str] | None = None) -> dict:
    """Build a week's Agenda page, and the Wrap-up when `learned` is given.

    Both are generated from the SAME module contents, so what the week promised and what it
    reports having covered cannot drift. Read the `agenda-wrapup` skill first.
    """
    from ..pages import agenda

    return agenda.build_and_place(course, module_id, week=week, intro=intro,
                                  topic_bullets=topic_bullets, review_note=review_note,
                                  closing=closing, learned=learned)


def build_module_overview(course: str, slug: str, overview_html: str, sections: list,
                          deck_id: str | None = None) -> dict:
    """Build a module's overview page — the plan, then a block per group of items.

    `sections` are the blocks; `plan_slide_sections` produces them when the module is organised
    by slide deck. Read the `module-overview-page` skill first.
    """
    from ..pages import module_overview

    return module_overview.make_page(course, slug, overview_html, sections, deck_id=deck_id)


def plan_slide_sections(slides: list) -> list:
    """Turn a per-slide plan into overview sections: what this deck covers, then what to do with it.

    Each slide is `{"title", "summary_html", "tasks", "deck_id"}`. Feed the result to
    `build_module_overview` as its `sections`.
    """
    from ..pages import slide_plan

    return slide_plan.slide_sections(slides)


def create_notebook_homework(spec: dict) -> dict:
    """Build a notebook homework template with the per-cell anchors the grader reads.

    The anchors are what makes `grade-nb` able to say WHICH section a student left unrun, so a
    notebook authored any other way cannot be graded the same way. Read the `nb-homework-create`
    skill first.
    """
    from ..pages import nb_create

    return nb_create.build(spec)


def register(server) -> None:
    for fn in (build_coding_assignment_page, build_notebook_assignment_page, build_rich_doc,
               build_weekly_agenda, build_module_overview, plan_slide_sections,
               create_notebook_homework):
        server.add_tool(fn)
