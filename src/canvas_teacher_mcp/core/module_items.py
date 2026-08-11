"""canvas_core.module_items — CRUD for items INSIDE a Module.

Python port of canvas_via_playwright/api/canvas_module_items.js. A Module Item is
a link/reference (Page/Assignment/Quiz/File/ExternalUrl/SubHeader) inside a Module.
Uses canvas_auth CanvasSession.

Item type → required field:
  Page        → page_url (slug)      Assignment/Quiz/File/Discussion → content_id
  ExternalUrl → external_url + title  SubHeader → title
"""
from __future__ import annotations

from ..auth.session import CanvasSession


def create(s: CanvasSession, course_id, module_id, **payload):
    """Add an item. Always pass at least type (+position). indent defaults to 0."""
    r = s.post(f"/api/v1/courses/{course_id}/modules/{module_id}/items",
               json={"module_item": {"indent": 0, **payload}}, csrf=True)
    r.raise_for_status()
    return r.json()


def read(s: CanvasSession, course_id, module_id, item_id):
    r = s.get(f"/api/v1/courses/{course_id}/modules/{module_id}/items/{item_id}")
    r.raise_for_status()
    return r.json()


def list(s: CanvasSession, course_id, module_id, **params):
    r = s.get(f"/api/v1/courses/{course_id}/modules/{module_id}/items", params=params or None)
    r.raise_for_status()
    return r.json()


def update(s: CanvasSession, course_id, module_id, item_id, **patch):
    r = s.put(f"/api/v1/courses/{course_id}/modules/{module_id}/items/{item_id}",
              json={"module_item": patch}, csrf=True)
    r.raise_for_status()
    return r.json()


def remove(s: CanvasSession, course_id, module_id, item_id):
    """Remove item from module. The target page/assignment is NOT deleted."""
    r = s.delete(f"/api/v1/courses/{course_id}/modules/{module_id}/items/{item_id}", csrf=True)
    r.raise_for_status()
    return r.json()
