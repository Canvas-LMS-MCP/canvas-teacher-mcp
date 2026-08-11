"""Course tools — which courses this install knows, and where each one is."""

from __future__ import annotations

from .. import course_config
from ..core import links as _links
from . import _ctx

TOOLS = ("list_courses", "get_course", "list_students", "extract_links")


def list_courses() -> list[str]:
    """Every course slug registered in the course root."""
    return list(course_config.slugs())


def get_course(course: str) -> dict:
    """A course's coordinates: Canvas id, base url, school, GitHub org, output paths.

    Never returns a secret — `canvas_token_env` names the variable, it is not the token.
    """
    cfg = dict(_ctx.config(course))
    cfg.pop("canvas_token", None)
    return cfg


def list_students(course: str) -> list[dict]:
    """Active students: id, name, email."""
    from ..rest import resources

    cfg = _ctx.config(course)
    users = resources.fetch_users(cfg["canvas_base_url"], _ctx.credential(course), cfg["course_id"])
    return [
        {"id": u.get("id"), "name": u.get("name"), "email": u.get("email") or u.get("login_id")}
        for u in users or []
    ]


def extract_links(html: str) -> list:
    """Every link in a block of Canvas HTML, classified by kind."""
    return _links.extract_links(html)


def register(server) -> None:
    for fn in (list_courses, get_course, list_students, extract_links):
        server.add_tool(fn)
