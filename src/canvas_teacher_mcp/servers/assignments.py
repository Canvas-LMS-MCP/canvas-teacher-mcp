"""Assignment tools — wraps `core/assignments.py` and `core/assignment_groups.py`.

Creates leave the assignment UNPUBLISHED. Nothing here deletes.
"""

from __future__ import annotations

from ..core import assignment_groups, assignments
from . import _ctx

TOOLS = ("list_assignments", "get_assignment", "create_assignment", "update_assignment",
         "set_due_dates", "needs_grading", "list_assignment_groups")


def list_assignments(course: str) -> list[dict]:
    """Every assignment: id, name, points, due date, published state."""
    out = assignments.list(_ctx.session(course), _ctx.course_id(course))
    return [
        {"id": a.get("id"), "name": a.get("name"), "points_possible": a.get("points_possible"),
         "due_at": a.get("due_at"), "published": a.get("published")}
        for a in out or []
    ]


def get_assignment(course: str, assignment_id: int) -> dict:
    """One assignment, description included."""
    return assignments.read(_ctx.session(course), _ctx.course_id(course), assignment_id)


def create_assignment(course: str, name: str, description: str = "",
                      points_possible: float | None = None, due_at: str | None = None,
                      assignment_group_id: int | None = None) -> dict:
    """Create an assignment, unpublished. `due_at` is ISO-8601 UTC."""
    fields = {"name": name, "description": description}
    for key, value in (("points_possible", points_possible), ("due_at", due_at),
                       ("assignment_group_id", assignment_group_id)):
        if value is not None:
            fields[key] = value
    return assignments.create(_ctx.session(course), _ctx.course_id(course), **fields)


def update_assignment(course: str, assignment_id: int, name: str | None = None,
                      description: str | None = None, points_possible: float | None = None,
                      due_at: str | None = None) -> dict:
    """Update an assignment. Publish state is left alone."""
    patch = {k: v for k, v in (("name", name), ("description", description),
                               ("points_possible", points_possible), ("due_at", due_at))
             if v is not None}
    if not patch:
        raise ValueError("nothing to update")
    return assignments.update(_ctx.session(course), _ctx.course_id(course), assignment_id, **patch)


def set_due_dates(course: str, assignment_ids: list[int], due_at: str) -> dict:
    """Set one due date on several assignments. `due_at` is ISO-8601 UTC."""
    return assignments.set_due_dates(_ctx.session(course), _ctx.course_id(course),
                                     assignment_ids, due_at)


def needs_grading(course: str, only_open: bool = False) -> list[dict]:
    """Assignments with submissions waiting to be graded."""
    return assignments.needs_grading(_ctx.session(course), _ctx.course_id(course),
                                     only_open=only_open)


def list_assignment_groups(course: str) -> list[dict]:
    """Assignment groups and their weights."""
    out = assignment_groups.list(_ctx.session(course), _ctx.course_id(course))
    return [
        {"id": g.get("id"), "name": g.get("name"), "group_weight": g.get("group_weight")}
        for g in out or []
    ]


def register(server) -> None:
    for fn in (list_assignments, get_assignment, create_assignment, update_assignment,
               set_due_dates, needs_grading, list_assignment_groups):
        server.add_tool(fn)
