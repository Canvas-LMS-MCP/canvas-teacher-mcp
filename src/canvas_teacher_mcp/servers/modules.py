"""Module tools — wraps `core/modules.py` and `core/module_items.py`.

Creates leave the module UNPUBLISHED. Nothing here deletes.
"""

from __future__ import annotations

from ..core import module_items, modules
from . import _ctx

TOOLS = ("list_modules", "get_module", "create_module", "list_module_items", "add_module_item")


def list_modules(course: str) -> list[dict]:
    """Every module: id, name, position, published state."""
    out = modules.list(_ctx.session(course), _ctx.course_id(course))
    return [
        {"id": m.get("id"), "name": m.get("name"), "position": m.get("position"),
         "published": m.get("published")}
        for m in out or []
    ]


def get_module(course: str, module_id: int) -> dict:
    """One module."""
    return modules.read(_ctx.session(course), _ctx.course_id(course), module_id)


def create_module(course: str, name: str) -> dict:
    """Create a module, unpublished."""
    return modules.create(_ctx.session(course), _ctx.course_id(course), name=name)


def list_module_items(course: str, module_id: int) -> list[dict]:
    """What is inside a module, in order."""
    out = module_items.list(_ctx.session(course), _ctx.course_id(course), module_id)
    return [
        {"id": i.get("id"), "title": i.get("title"), "type": i.get("type"),
         "content_id": i.get("content_id"), "position": i.get("position"),
         "published": i.get("published")}
        for i in out or []
    ]


def add_module_item(course: str, module_id: int, title: str, item_type: str,
                    content_id: int | None = None, page_url: str | None = None) -> dict:
    """Add an item to a module, unpublished.

    `item_type` is Canvas's own: Page, Assignment, Quiz, File, Discussion, ExternalUrl,
    SubHeader. A Page item needs `page_url`; Assignment/Quiz/File need `content_id`.
    """
    payload = {"title": title, "type": item_type, "published": False}
    if content_id is not None:
        payload["content_id"] = content_id
    if page_url is not None:
        payload["page_url"] = page_url
    return module_items.create(_ctx.session(course), _ctx.course_id(course), module_id, **payload)


def register(server) -> None:
    for fn in (list_modules, get_module, create_module, list_module_items, add_module_item):
        server.add_tool(fn)
