"""canvas_core.modules — CRUD for Canvas Modules (containers).

Python port of canvas_via_playwright/api/canvas_modules.js. A Module groups
Module Items (see canvas_core.module_items); it has no content body itself.
Uses canvas_auth CanvasSession. create/update default published=False.
"""
from __future__ import annotations

from ..auth.session import CanvasSession


def create(s: CanvasSession, course_id, *, name, published=False, **extra):
    """Create a module. Returns module dict incl. `id`."""
    r = s.post(f"/api/v1/courses/{course_id}/modules",
               json={"module": {"name": name, "published": published, **extra}}, csrf=True)
    r.raise_for_status()
    return r.json()


def read(s: CanvasSession, course_id, module_id):
    r = s.get(f"/api/v1/courses/{course_id}/modules/{module_id}")
    r.raise_for_status()
    return r.json()


def list(s: CanvasSession, course_id, **params):
    r = s.get(f"/api/v1/courses/{course_id}/modules", params=params or None)
    r.raise_for_status()
    return r.json()


def update(s: CanvasSession, course_id, module_id, **patch):
    r = s.put(f"/api/v1/courses/{course_id}/modules/{module_id}",
              json={"module": patch}, csrf=True)
    r.raise_for_status()
    return r.json()


def remove(s: CanvasSession, course_id, module_id):
    r = s.delete(f"/api/v1/courses/{course_id}/modules/{module_id}", csrf=True)
    r.raise_for_status()
    return r.json()
