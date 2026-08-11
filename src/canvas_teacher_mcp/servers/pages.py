"""Page tools — wraps `core/pages.py`.

Creates and updates leave the page UNPUBLISHED. The instructor publishes.
"""

from __future__ import annotations

from ..core import pages
from . import _ctx

TOOLS = ("list_pages", "get_page", "create_page", "update_page")


def list_pages(course: str) -> list[dict]:
    """Every page in the course: title, url slug, published state."""
    out = pages.list(_ctx.session(course), _ctx.course_id(course))
    return [
        {"title": p.get("title"), "url": p.get("url"), "published": p.get("published")}
        for p in out or []
    ]


def get_page(course: str, slug: str) -> dict:
    """One page, body included. `slug` is the page's url segment."""
    return pages.read(_ctx.session(course), _ctx.course_id(course), slug)


def create_page(course: str, title: str, body: str) -> dict:
    """Create a page, unpublished."""
    return pages.create(_ctx.session(course), _ctx.course_id(course), title=title, body=body)


def update_page(course: str, slug: str, title: str | None = None, body: str | None = None) -> dict:
    """Update a page's title and/or body. Publish state is left alone."""
    patch = {k: v for k, v in (("title", title), ("body", body)) if v is not None}
    if not patch:
        raise ValueError("nothing to update — pass title, body, or both")
    return pages.update(_ctx.session(course), _ctx.course_id(course), slug, **patch)


def register(server) -> None:
    for fn in (list_pages, get_page, create_page, update_page):
        server.add_tool(fn)
