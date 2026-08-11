#!/usr/bin/env python3
"""module_overview.py — GLOBAL module "overview" page builder (Skill 1).

Builds a module overview/representative page = 📌 Overview + an OPTIONAL page-level slide embed +
FLEXIBLE SECTION BLOCKS (each block = a category/topic header, an optional summary, its items, and
an optional per-section slide embed). No fixed columns — categories are DATA, added/removed freely
per course/module.

CONFIG-DRIVEN: every course coordinate (base_url, course_id, token) comes from
`course_config.load(slug)` — NO course value is baked in. Reuses the universal skeleton
(canvas_core.assignment_page_builder) + canvas_rest. Backs up the current body before overwriting;
NEVER sets `published` (only the instructor publishes).

Data model:
  sections = [(header, summary_html|None, items, section_deck_id|None), ...]   # 2..4-length tuples ok
  items    = [(kind, ref, label), ...]   kind ∈ {assignment, page, quiz, url, text}

Lessons baked in (2026-07-10):
  * NO <code> tags — a linked page stylesheet can break them. Use <b>/plain.
  * escape a literal % as %% inside any %-format string (e.g. width:100%%;).
  * back up the FIRST (true original) body only — never clobber the backup on a re-run.
"""
import os
import sys
from urllib.parse import urlparse

from .page_builder import section, slide_embed, NAVY
from .. import rest as canvas_rest
from ..auth.token import get_token
from .. import course_config  # THE config reader (single source; never re-implement)

DECK_EMBED = "https://docs.google.com/presentation/d/%s/embed?start=false&loop=false&delayms=3000"


def _deck_url(deck):
    """Resolve a deck ref to the URL handed to slide_embed. A FULL embed URL is passed through
    VERBATIM (preserves the instructor's existing embed, incl. a published /d/e/2PACX.../embed one);
    a bare presentation id is wrapped with DECK_EMBED (back-compat). slide_embed owns the format from
    there. NEVER slice a URL down to an id — pass the whole thing (matches git_page / build)."""
    return deck if str(deck).startswith("http") else DECK_EMBED % deck


def _token(cfg):
    return get_token(cfg.get("canvas_token_env", ""), cfg["canvas_base_url"])


def link(cfg, kind, ref, label):
    """A native Canvas link (RCE pill) by kind. ref = assignment/quiz id, page slug, or url."""
    base, course = cfg["canvas_base_url"], cfg["course_id"]
    domain = urlparse(base).netloc
    if kind == "text":
        return label
    if kind == "url":
        return '<a href="%s" target="_blank">%s</a>' % (ref, label)
    noun = {"assignment": ("assignments", "Assignment"),
            "page": ("pages", "WikiPage"),
            "quiz": ("quizzes", "Quiz")}[kind]
    u = "https://%s/courses/%d/%s/%s" % (domain, course, noun[0], ref)
    api = "%s/courses/%d/%s/%s" % (base, course, noun[0], ref)
    return ('<a href="%s" data-api-endpoint="%s" data-api-returntype="%s">%s</a>'
            % (u, api, noun[1], label))


def _items_html(cfg, items):
    if not items:
        return ""
    lis = "".join("<li>%s</li>" % link(cfg, k, r, l) for (k, r, l) in items)
    return "<ul style='margin:4px 0 4px 1.2em;line-height:1.7;'>%s</ul>" % lis


def _unpack(sec):
    """A section is a 2..4-length tuple: (header, summary_html?, items?, section_deck_id?)."""
    header = sec[0]
    summary = sec[1] if len(sec) > 1 else None
    items = sec[2] if len(sec) > 2 else []
    sdeck = sec[3] if len(sec) > 3 else None
    return header, summary, items, sdeck


def render_section(cfg, sec):
    header, summary, items, sdeck = _unpack(sec)
    body = ""
    if summary:
        body += summary                          # summary_html is caller-authored HTML, inline as-is
    body += _items_html(cfg, items)
    if sdeck:
        body += slide_embed(_deck_url(sdeck))  # per-section deck: full URL (verbatim) or bare id
    return section(header, body)                 # heading (NAVY) + indented body


def build_body(cfg, overview_html, sections, *, deck_id=None, stylesheet=None):
    """Assemble the page body = [stylesheet] + 📌 Overview + [page deck] + section blocks."""
    style = ('<link rel="stylesheet" href="%s">' % stylesheet) if stylesheet else ""
    parts = [style, section("📌 Overview", overview_html)]
    if deck_id:
        parts.append(slide_embed(_deck_url(deck_id)))
    parts += [render_section(cfg, s) for s in (sections or [])]
    return "".join(parts)


def make_page(course_slug, slug, overview_html, sections, *,
              deck_id=None, stylesheet=None, push=False, backup_dir=None, token=None):
    """Build (and optionally PUT) a course's module overview page.

    course_slug   : course_config slug, e.g. '<course>' (coords come from there).
    slug          : Canvas page url slug (e.g. 'git-and-github-systems').
    overview_html : AUTHORED — 1-2 <p> paragraphs (NO <code>).
    sections      : AUTHORED — [(header, summary_html|None, items, section_deck_id|None)].
    deck_id       : page-level slide deck under the overview — a FULL embed URL (passed VERBATIM, so
                    an existing page's embed is preserved) or a bare presentation id (None -> none).
                    Same for each section's section_deck_id.
    stylesheet    : optional page stylesheet URL (course-specific; None -> none).
    push          : False = assemble + backup only (dry) ; True = PUT the page.
    backup_dir    : if given, save the FIRST original body to <slug>_BACKUP.html there.

    Never sets `published` (stays unpublished). Returns {html, status, published}.
    """
    cfg = course_config.load(course_slug)
    base, course = cfg["canvas_base_url"], cfg["course_id"]
    token = token or _token(cfg)
    body = build_body(cfg, overview_html, sections, deck_id=deck_id, stylesheet=stylesheet)
    cur = canvas_rest.get_page(base, token, course, slug)
    if backup_dir:
        bk = os.path.join(backup_dir, "%s_BACKUP.html" % slug)
        if not os.path.exists(bk):            # keep only the TRUE original
            with open(bk, "w") as f:
                f.write(cur.get("body") or "")
    if not push:
        return {"html": body, "status": None, "published": cur.get("published")}
    status, _ = canvas_rest.update_page(base, token, course, slug, {"body": body})
    chk = canvas_rest.get_page(base, token, course, slug)
    return {"html": body, "status": status, "published": chk.get("published")}
