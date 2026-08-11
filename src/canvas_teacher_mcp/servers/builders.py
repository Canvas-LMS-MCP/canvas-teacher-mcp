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

TOOLS = ("build_coding_assignment_page", "build_notebook_assignment_page", "build_rich_doc")


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


def register(server) -> None:
    for fn in (build_coding_assignment_page, build_notebook_assignment_page, build_rich_doc):
        server.add_tool(fn)
