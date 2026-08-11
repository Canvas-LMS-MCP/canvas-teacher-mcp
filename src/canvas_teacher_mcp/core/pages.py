"""canvas_core.pages — CRUD for Canvas wiki Pages (cookie session, CSRF-gated).

Python port of canvas_via_playwright/api/canvas_pages.js. Uses the canvas_auth
CanvasSession (cookies + CSRF + auto-relogin); no node, no Playwright ctx.

Endpoints:
  POST   /api/v1/courses/{cid}/pages           — create
  GET    /api/v1/courses/{cid}/pages/{slug}    — read one
  GET    /api/v1/courses/{cid}/pages           — list
  PUT    /api/v1/courses/{cid}/pages/{slug}    — update
  DELETE /api/v1/courses/{cid}/pages/{slug}    — delete

All create/update default published=False (the do-not-publish rule);
publishing is a manual instructor action — never automate.
"""
from __future__ import annotations

from urllib.parse import quote

from ..auth.session import CanvasSession


def create(s: CanvasSession, course_id, *, title, body, published=False, **extra):
    """Create a page. Returns the created page dict (incl. `url` slug)."""
    r = s.post(f"/api/v1/courses/{course_id}/pages",
               json={"wiki_page": {"title": title, "body": body, "published": published, **extra}},
               csrf=True)
    r.raise_for_status()
    return r.json()


def read(s: CanvasSession, course_id, slug):
    """Read one page by URL slug."""
    r = s.get(f"/api/v1/courses/{course_id}/pages/{quote(str(slug))}")
    r.raise_for_status()
    return r.json()


def list(s: CanvasSession, course_id, **params):
    """List pages. Pass per_page=100, sort='title', ... as kwargs."""
    r = s.get(f"/api/v1/courses/{course_id}/pages", params=params or None)
    r.raise_for_status()
    return r.json()


def update(s: CanvasSession, course_id, slug, **patch):
    """Update a page by slug. Only fields in `patch` are sent. Never auto-publish."""
    r = s.put(f"/api/v1/courses/{course_id}/pages/{quote(str(slug))}",
              json={"wiki_page": patch}, csrf=True)
    r.raise_for_status()
    return r.json()


def remove(s: CanvasSession, course_id, slug):
    """Delete a page by slug. Irreversible."""
    r = s.delete(f"/api/v1/courses/{course_id}/pages/{quote(str(slug))}", csrf=True)
    r.raise_for_status()
    return r.json()
