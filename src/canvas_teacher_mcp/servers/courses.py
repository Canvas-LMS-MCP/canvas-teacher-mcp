"""Course tools — which courses this install knows, and where each one is."""

from __future__ import annotations

from .. import course_config
from ..core import links as _links
from . import _ctx

TOOLS = ("list_courses", "get_course", "list_students", "extract_links", "canvas_api_request")


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


def canvas_api_request(course: str, method: str, path: str, params: dict | None = None,
                       body: dict | None = None) -> object:
    """Call a Canvas REST endpoint no other tool covers.

    The dedicated tools are the way in; this is what remains when none of them reaches the
    endpoint — discussions, rubrics, outcomes, anything Canvas offers with no wrapper here. It
    goes only to this course's Canvas, with this install's own credential.

    `path` is relative to /api/v1, e.g. `/courses/{course_id}/discussion_topics`; `get_course`
    gives the id. `method` is GET, POST or PUT.

    Deleting is not available here. Whatever is created stays unpublished — the instructor
    publishes.
    """
    from ..rest import client

    verb = method.strip().upper()
    if verb == "DELETE":
        raise ValueError("canvas_api_request does not delete. Remove content in Canvas itself.")
    if verb not in ("GET", "POST", "PUT"):
        raise ValueError(f"unsupported method {method!r}; use GET, POST or PUT")

    cfg = _ctx.config(course)
    base, token = cfg["canvas_base_url"], _ctx.credential(course)
    if verb == "GET":
        return client.get(base, token, path, params=list((params or {}).items()) or None)
    payload = body or {}
    return client.post(base, token, path, payload) if verb == "POST" \
        else client.put(base, token, path, payload)


def register(server) -> None:
    for fn in (list_courses, get_course, list_students, extract_links, canvas_api_request):
        server.add_tool(fn)
