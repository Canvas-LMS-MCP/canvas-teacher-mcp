"""Course coordinates and credentials, resolved the one canonical way.

Every tool takes a course slug and nothing else about identity: the course config answers where
the course is, and the credential is DERIVED from whether the school issues tokens.
"""

from __future__ import annotations

from .. import course_config
from ..auth.session import CanvasSession


def config(course: str) -> dict:
    return course_config.load(course)


def session(course: str) -> CanvasSession:
    """A session for the `core/` modules. Token or cookie is decided inside, by school."""
    cfg = config(course)
    return CanvasSession(cfg["school"], domain=course_config.domain(course))


def credential(course: str):
    """A token string, or a session when the school issues none. `rest/` accepts either."""
    cfg = config(course)
    try:
        from ..auth.token import get_token

        return get_token(cfg["canvas_token_env"], base_url=cfg["canvas_base_url"])
    except RuntimeError:
        return CanvasSession(cfg["school"])


def course_id(course: str):
    return config(course)["course_id"]
