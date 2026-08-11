"""Fetch a Canvas page/module/assignment/quiz and inventory ALL its links.

    link_extractor(course, ref) -> list[dict]

`course` = a Canvas course_id, a course slug (`"<slug>"`), or None when `ref` is a full
Canvas URL. `ref` = `"module:ID"` | `"page:SLUG"` | `"assignment:ID"` | `"quiz:ID"`, or a
full Canvas URL (course + type + id parsed from the path).

ANY course, ANY school: the base_url + token env are resolved from the course's config via
`course_config` (Where/CourseConfig.md — course identity is DATA, never a literal). Until 2026-07-17 this
module hardcoded one institution's BASE, so it crashed on every other course (fetch returned
None -> AttributeError). Never re-add a school constant here.

Fetches every relevant body via **canvas_rest** (no inline HTTP), extracts links with
**canvas_core.links.extract_links**, merges by url with a `where` set (which item each
link appeared in). One entry point for both a single object and a whole module.

Quizzes: embeds live in the QUESTION items, not just the description — so this scans the
quiz description AND every question's text + answer HTML (+ comments). Module items are
dispatched by type (page/assignment/quiz scanned; external_url = a direct link;
file/subheader skipped — no body).

CLI:  python3 -m canvas_core.canvas_link_extractor <course_id> <ref>
      python3 -m canvas_core.canvas_link_extractor 58774 module:584239
Index: code/playbook/canvas-github-access-layers.md
"""
import re
import sys

from ..auth.token import get_token
from ..rest import client, resources
from ..core.links import extract_links
from .. import course_config


def _parse_ref(course_id, ref):
    """Return (course_id, kind, ident). Accepts 'kind:id' or a full Canvas URL."""
    if ref.startswith("http"):
        cm = re.search(r"/courses/(\d+)", ref)
        if cm:
            course_id = cm.group(1)
        for kind, pat in (("module", r"/modules/(\d+)"),
                          ("assignment", r"/assignments/(\d+)"),
                          ("quiz", r"/quizzes/(\d+)"),
                          ("page", r"/pages/([^/?#]+)")):
            m = re.search(pat, ref)
            if m:
                return course_id, kind, m.group(1)
        raise ValueError(f"cannot parse Canvas URL: {ref}")
    if ":" not in ref:
        raise ValueError("ref must be 'kind:id' (module/page/assignment/quiz) or a Canvas URL")
    kind, ident = ref.split(":", 1)
    return course_id, kind.strip().lower(), ident.strip()


def _chunks(base, token, course, kind, ident):
    """Yield (where_label, html) for every body that may contain links."""
    if kind == "page":
        pg = resources.get_page(base, token, course, ident)
        yield (f"page:{pg.get('title', ident)}", pg.get("body", "") or "")
    elif kind == "assignment":
        a = resources.fetch_assignment(base, token, course, ident)
        yield (f"asmt:{a.get('name', ident)}", a.get("description", "") or "")
    elif kind == "quiz":
        q = resources.fetch_quiz(base, token, course, ident)
        title = q.get("title", ident)
        yield (f"quiz:{title} [desc]", q.get("description", "") or "")
        questions = client.get(base, token,
                               f"/courses/{course}/quizzes/{ident}/questions", paginate=True)
        for n, qq in enumerate(questions or [], 1):
            yield (f"quiz:{title} Q{n}", qq.get("question_text", "") or "")
            for ans in (qq.get("answers") or []):
                h = ans.get("html") or ans.get("text") or ""
                if h:
                    yield (f"quiz:{title} Q{n} answer", h)
            for ck in ("correct_comments_html", "incorrect_comments_html", "neutral_comments_html"):
                if qq.get(ck):
                    yield (f"quiz:{title} Q{n} comment", qq[ck])
    elif kind == "module":
        items = client.get(base, token,
                           f"/courses/{course}/modules/{ident}/items", paginate=True)
        for it in (items or []):
            t = it.get("type")
            title = it.get("title", "")
            if t == "Page" and it.get("page_url"):
                yield from _chunks(base, token, course, "page", it["page_url"])
            elif t == "Assignment" and it.get("content_id"):
                yield from _chunks(base, token, course, "assignment", str(it["content_id"]))
            elif t == "Quiz" and it.get("content_id"):
                yield from _chunks(base, token, course, "quiz", str(it["content_id"]))
            elif t == "ExternalUrl" and it.get("external_url"):
                # the item's own external link
                yield (f"exturl:{title}", f'<a href="{it["external_url"]}">{title}</a>')
            # File / SubHeader: no body to scan
    else:
        raise ValueError(f"unknown ref kind: {kind} (use module/page/assignment/quiz)")


def link_extractor(course, ref, token=None, base=None):
    """course + ref -> list[dict] (every link, deduped by url, with `where` set).

    `course` = a Canvas course_id, a course slug ('<slug>'), or None with a full Canvas URL as
    `ref`. The SCHOOL is resolved from the course's config (course_config) — works for every course,
    nothing hardcoded. `base`/`token` override only if you already have them.
    """
    course_id, kind, ident = _parse_ref(str(course) if course else None, ref)
    if not course_id:
        raise ValueError("course required (or pass a full Canvas URL containing /courses/<id>)")
    school = None
    if not base:
        cfg = course_config.load(course_id)          # by id, or by slug when a slug was passed
        base, env = cfg["canvas_base_url"], cfg["canvas_token_env"]
        school = cfg.get("school")
        course_id = str(cfg["course_id"])            # a slug resolves to the real Canvas id
    else:
        env = "CANVAS_TOKEN"
    # Credential: token when the school has one, else the cookie session. canvas_rest.client
    # accepts either (a token str or a CanvasSession) — so a token-less school works too.
    # Was token-only once, which made this crash on every cookie school.
    if not token:
        try:
            token = get_token(env, base)
        except RuntimeError:
            if not school:
                raise
            from ..auth.session import CanvasSession
            token = CanvasSession(school)
    merged = {}  # url -> dict(+where)
    for where, html in _chunks(base, token, course_id, kind, ident):
        for d in extract_links(html):
            u = d["url"]
            if u not in merged:
                merged[u] = {**d, "where": set()}
            merged[u]["where"].add(where)
    out = []
    for d in merged.values():
        d = {**d, "where": sorted(d["where"])}
        out.append(d)
    return out


if __name__ == "__main__":
    import json
    if len(sys.argv) < 3:
        print("usage: python3 -m canvas_core.canvas_link_extractor <course_id|-> <ref>", file=sys.stderr)
        print("  ref = module:ID | page:SLUG | assignment:ID | quiz:ID | <Canvas URL>", file=sys.stderr)
        sys.exit(2)
    cid = None if sys.argv[1] == "-" else sys.argv[1]
    links = link_extractor(cid, sys.argv[2])
    for d in links:
        print(json.dumps(d, ensure_ascii=False))
    print(f"# {len(links)} unique links", file=sys.stderr)
