"""canvas_core.announcements — Canvas announcement (discussion_topic, is_announcement) posting.

Python port of canvas_via_playwright/post_announcement.kick.js + send_announcement.sh + the
run.sh/dispatch.sh entry role, all via CanvasSession (urllib + CSRF). No node, no page.evaluate.

⚠️ SAFETY — publishing an announcement EMAILS ALL STUDENTS (outward-facing, not undoable).
The JS kept `published:false` FROZEN as a tripwire (Canvas rejects published:false announcements
with HTTP 400 → nothing sent). Preserved here: `post_announcement(published=False)` = PREVIEW
(400, no email). Actually sending requires `send_announcement(..., confirm=SEND_CONFIRM)` — an
explicit acknowledgement, mirroring the old `CANVAS_SEND_CONFIRMED=YES_...` env gate.
"""
from __future__ import annotations

from ..auth.session import CanvasSession

SEND_CONFIRM = "YES_I_REALLY_WANT_TO_EMAIL_ALL_STUDENTS_NOW"


def post_announcement(session: CanvasSession, course_id, *, title, message, published=False):
    """Create an announcement. Returns (status_code, response_dict).

    published=False → PREVIEW/tripwire: Canvas returns HTTP 400 and NOTHING is sent (safe).
    published=True  → LIVE: the announcement posts and Canvas EMAILS ALL STUDENTS.
    Prefer send_announcement() (confirm-gated) over passing published=True here directly.
    """
    r = session.post(f"/api/v1/courses/{course_id}/discussion_topics",
                     json={"title": title, "message": message,
                           "is_announcement": True, "published": published}, csrf=True)
    return r.status_code, (r.json() if r.content else {})


def send_announcement(session: CanvasSession, course_id, *, title, message, confirm=None):
    """LIVE send (published=True) → EMAILS ALL STUDENTS. Requires confirm=SEND_CONFIRM.

    The ONE sanctioned send path (mirrors the old run.sh announce-send env gate)."""
    if confirm != SEND_CONFIRM:
        raise RuntimeError(
            "send_announcement is OUTWARD-FACING (emails ALL students, not undoable). "
            f"Pass confirm=announcements.SEND_CONFIRM ('{SEND_CONFIRM}') to proceed.")
    return post_announcement(session, course_id, title=title, message=message, published=True)


def _parse_frontmatter(text):
    """Extract `<!-- title: ... -->` + the HTML body (everything after)."""
    import re
    m = re.search(r"<!--\s*title:\s*(.+?)\s*-->", text)
    title = m.group(1).strip() if m else None
    message = text[m.end():].strip() if m else text.strip()
    if not title or not message:
        raise RuntimeError("announcement file needs `<!-- title: ... -->` + an HTML body")
    return title, message


def _main(argv):
    """CLI = PREVIEW only (safe, HTTP 400 tripwire, 0 email):

        python3 -m canvas_core.announcements <school> <course_id> <file.html>

    To send, call the function directly (no CLI flag):
        send_announcement(CanvasSession(school), course_id, title=T, message=M, confirm=SEND_CONFIRM)

    <file.html> = `<!-- title: ... -->` frontmatter + HTML body.
    """
    if len(argv) < 3:
        print(_main.__doc__)
        return 2
    school, course_id, path = argv[0], int(argv[1]), argv[2]
    title, message = _parse_frontmatter(open(path, encoding="utf-8").read())
    s = CanvasSession(school)
    status, _ = post_announcement(s, course_id, title=title, message=message, published=False)
    print(f"PREVIEW (published=false) → HTTP {status} (400 expected = tripwire, no email sent).")
    print(f"  title: {title!r}  body: {len(message)} chars")
    if status == 400:
        # Diagnostic device (NOT memory): preview is the control experiment. A 400 here PROVES
        # code + auth + HTML are all good. So if the live send call is then refused, the only
        # thing that differs is the outward effect → by elimination the block is the PERMISSION
        # MODE, never this code. Do not edit code / reword / build a driver — switch the mode.
        print("  CONTROL PASSED: code + auth + HTML proven good.")
        print("  → If the send is then REFUSED, it is the permission mode (by elimination), NOT this code.")
        print("    Fix = instructor switches permission mode; do NOT touch code.")
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(_main(sys.argv[1:]))
