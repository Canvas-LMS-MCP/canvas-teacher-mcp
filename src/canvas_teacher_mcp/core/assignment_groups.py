"""canvas_core.assignment_groups — CRUD for Canvas Assignment Groups.

Python port of canvas_via_playwright/api/canvas_assignment_groups.js. Uses
canvas_auth CanvasSession. Groups have no publish flag (publish is per-assignment).

Common fields: name, group_weight, position, rules.
"""
from __future__ import annotations

from ..auth.session import CanvasSession


def create(s: CanvasSession, course_id, **fields):
    r = s.post(f"/api/v1/courses/{course_id}/assignment_groups", json=fields, csrf=True)
    r.raise_for_status()
    return r.json()


def read(s: CanvasSession, course_id, group_id):
    r = s.get(f"/api/v1/courses/{course_id}/assignment_groups/{group_id}")
    r.raise_for_status()
    return r.json()


def list(s: CanvasSession, course_id, **params):
    r = s.get(f"/api/v1/courses/{course_id}/assignment_groups", params=params or None)
    r.raise_for_status()
    return r.json()


def update(s: CanvasSession, course_id, group_id, **patch):
    r = s.put(f"/api/v1/courses/{course_id}/assignment_groups/{group_id}", json=patch, csrf=True)
    r.raise_for_status()
    return r.json()


def remove(s: CanvasSession, course_id, group_id):
    r = s.delete(f"/api/v1/courses/{course_id}/assignment_groups/{group_id}", csrf=True)
    r.raise_for_status()
    return r.json()


def find_by_name(s: CanvasSession, course_id, name):
    """Find a group by name (returns None if missing). Uses list()."""
    for g in list(s, course_id, per_page=100):
        if g.get("name") == name:
            return g
    return None
