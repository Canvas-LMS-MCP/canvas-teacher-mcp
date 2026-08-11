"""Announcement tools — wraps `core/announcements.py`.

An announcement emails the whole class the moment it posts, so it is two steps: preview, then
send with the confirmation string the preview returns. Nothing sends on one call.
"""

from __future__ import annotations

from ..core import announcements
from . import _ctx

TOOLS = ("preview_announcement", "send_announcement")

_CONFIRM = "SEND"


def preview_announcement(course: str, title: str, message: str) -> dict:
    """Render what would be sent, and say how to send it. Sends nothing."""
    cfg = _ctx.config(course)
    return {
        "course": course,
        "canvas_course_id": cfg["course_id"],
        "title": title,
        "message": message,
        "next_step": (
            "Show this to the instructor. Sending emails every student immediately, so call "
            f"send_announcement with confirm='{_CONFIRM}' only after they say to."
        ),
    }


def send_announcement(course: str, title: str, message: str, confirm: str) -> dict:
    """Post an announcement. Requires `confirm='SEND'`, which the preview explains."""
    if confirm != _CONFIRM:
        raise ValueError(
            f"send_announcement needs confirm='{_CONFIRM}'. Run preview_announcement, show it to "
            "the instructor, and send only once they agree."
        )
    return announcements.send_announcement(
        _ctx.session(course), _ctx.course_id(course),
        title=title, message=message, confirm=confirm,
    )


def register(server) -> None:
    for fn in (preview_announcement, send_announcement):
        server.add_tool(fn)
