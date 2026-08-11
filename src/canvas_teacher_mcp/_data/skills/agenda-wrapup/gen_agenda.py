"""gen_agenda — GLOBAL weekly Agenda + Wrap-up builder (MACHINERY for the agenda-wrapup skill).

Config-driven: takes `course_slug`, calls `course_config.load(slug)` for course_id, base,
token_env, output_dir — no course/domain hardcoded. Links are relative (course-agnostic).

Reads a MODULE once → builds the rich Agenda + Wrap-up HTML (the Week-3 house format: bold intro,
sectioned h3, navy Graded table with due + points + Total, inline code font) → places them by the
MODULE-SCOPED algorithm (find the page IN the module, never by a guessed slug) → saves the HTML to
`.claude/output/Canvas-Pages/`.

Prose that changes per week (intro line, topic bullets, review note, closing) is passed in; the
mechanical parts (Graded table, due dates via to_localtime, links to module items, placement, save)
are fixed here so every week looks the same.

Usage:
    from gen_agenda import build_and_place
    build_and_place("<course>", module_id, week="Week 4",
                    intro="Week 4 — Midterm 2 (Chapter 5. Functions)",
                    topic_bullets=[...], review_note="...", closing="...",
                    learned=[...])   # learned -> wrap-up "you learned" bullets
"""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
# The tree root comes from the environment, never from a directory NAME — walking up looking for
# one only works inside this tree, and an installed package sits outside it.
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "..", "code")))
from canvas_root import root  # noqa: E402
_CG = str(root())
sys.path.insert(0, os.path.join(_CG, ".claude", "code"))
import canvas_rest as cr  # noqa: E402
import course_config  # noqa: E402  # THE config reader (single source; never open a json here)
_CODE = ("<span style=\"font-family:'Courier New',monospace;background-color:#f2f2f2;"
         "padding:1px 5px;border-radius:3px;border:1px solid #e0e0e0;\">%s</span>")
_TH = "background-color:#1F3864;color:#fff;padding:8px;text-align:left;border:1px solid #ccc;"
_TD = "padding:8px;border:1px solid #ccc;"
_TC = "padding:8px;border:1px solid #ccc;text-align:center;"


def _cfg(course_slug):
    # Was `open(grade_engine/config/<slug>.json)` — that dir was deleted 2026-07-28, so this
    # broke outright. `course_config` is the ONE reader (code/README.md): it locates the
    # per-course file, derives course_id/base/token_env/output_dir, and raises on an unknown
    # slug instead of returning a half-empty dict.
    return course_config.load(course_slug)


def cf(t):
    return _CODE % t


def _itemlink(cid, item_id, text):
    # RELATIVE link — Canvas resolves it within the course; no domain needed (course-agnostic).
    return "<a href='/courses/%d/modules/items/%s'>%s</a>" % (cid, item_id, text)


def read_module(base, tok, course_id, module_id, skip_labs=False, skip_todo=False,
                exclude_content_ids=()):
    """Return (graded, todo, pages) — module items split. graded = Assignment/Quiz with due+points.
    skip_labs=True drops lab items (title marked with the microscope emoji or 'Lab Activity').
    skip_todo=True drops the non-graded to-dos (content pages / files / links) — the agenda then
    shows only the graded items (still tracks Pages for Agenda/Wrap-up placement).
    exclude_content_ids = assignment/quiz ids to leave OUT of the agenda while leaving the module
    item itself untouched (an item the instructor keeps but is not asking students to do)."""
    items = cr.get(base, tok, "/courses/%d/modules/%d/items" % (course_id, module_id),
                   params=[("per_page", "100")]) or []
    exclude = {int(x) for x in exclude_content_ids}
    graded, todo, pages = [], [], []
    for it in items:
        t = it.get("type")
        title = it.get("title", "") or ""
        if it.get("content_id") in exclude:
            continue
        if skip_labs and ("\U0001f52c" in title or "lab activity" in title.lower()):
            continue
        if t in ("Assignment", "Quiz"):
            fetch = cr.fetch_assignment if t == "Assignment" else cr.fetch_quiz
            meta = fetch(base, tok, course_id, it["content_id"]) or {}
            graded.append({"item": it, "due": meta.get("due_at"),
                           "points": meta.get("points_possible")})
        elif t == "Page":
            # `pages` = placement lookup (find THIS module's Agenda / Wrap-up page to update).
            # Content pages are ALSO to-dos — only the Agenda/Wrap-up pages themselves are skipped
            # (skill: "Skip existing Agenda/Wrap-up Page items — we're regenerating those").
            pages.append(it)
            low = title.lower()
            if not skip_todo and "agenda" not in low and "wrap-up" not in low and "wrapup" not in low:
                todo.append(it)
        elif t in ("ExternalUrl", "File", "ExternalTool"):
            if not skip_todo:
                todo.append(it)
    return graded, todo, pages


def _graded_table(course_id, graded):
    rows = ""
    total = 0
    for g in graded:
        it = g["item"]
        due = cr.to_localtime(g["due"]) if g["due"] else "No due date set"
        pts = g["points"] or 0
        total += pts
        link = _itemlink(course_id, it["id"], it.get("title", ""))
        rows += ("<tr><td style='%s'>%s</td><td style='%s'>%s</td><td style='%s'>%s</td></tr>"
                 % (_TD, link, _TD, due, _TC, int(pts) if pts == int(pts) else pts))
    rows += ("<tr><td style='%s'><strong>Total</strong></td><td style='%s'></td>"
             "<td style='%s'><strong>%s</strong></td></tr>"
             % (_TD, _TD, _TC, int(total) if total == int(total) else total))
    return ("<table style='border-collapse:collapse;max-width:900px;'>"
            "<thead><tr><th style='%s'>Item</th><th style='%s'>Due</th><th style='%s'>Points</th></tr>"
            "</thead><tbody>%s</tbody></table>" % (_TH, _TH, _TH, rows))


def build_agenda(course_id, graded, todo, *, intro, topic_bullets, review_note, closing,
                 review_materials="", greeting=""):
    if isinstance(topic_bullets, str):   # a lone string would iterate char-by-char -> one <li> per letter
        topic_bullets = [topic_bullets]
    tb = "".join("<li>%s</li>" % b for b in topic_bullets)
    todo_links = "".join("<li>%s</li>" % _itemlink(course_id, it["id"], it.get("title", "")) for it in todo)
    todo_block = ("<ul>%s</ul>" % todo_links) if todo_links else ""
    greet = ("<p>%s</p>" % greeting) if greeting else ""
    return (
        "<p style='font-size:1.15em;'><strong>%s</strong></p>"
        "<p>Hello students,</p>"
        "%s"                      # greeting lead-in (warm intro before the topic bullets)
        "<ul>%s</ul>"
        "<h3>1. This week's to-dos</h3>"
        "%s"                      # review_materials (Read / Watch / Practice — carried in for review weeks)
        "<p>%s</p>%s"
        "<h3>2. Graded &mdash; do these</h3>%s"
        "<h3>3. Before you start</h3><p>%s</p>"
        % (intro, greet, tb, review_materials, review_note, todo_block, _graded_table(course_id, graded), closing))


def build_wrapup(course_id, graded, *, intro, learned, closing):
    if isinstance(learned, str):   # a lone string would iterate char-by-char -> one <li> per letter
        learned = [learned]
    check = "".join("<li>&#9744; %s</li>" % _itemlink(course_id, g["item"]["id"], g["item"].get("title", ""))
                    for g in graded)
    lrn = "".join("<li>%s</li>" % x for x in learned)
    return (
        "<p style='font-size:1.15em;'><strong>%s</strong></p>"
        "<h3>1. Did you finish this?</h3><ul>%s</ul>"
        "<h3>2. This week you learned</h3><ul>%s</ul>"
        "<h3>3. Confirm</h3><p>Confirm you completed everything above.</p>"
        "<h3>4. Closing</h3><p>%s</p>" % (intro, check, lrn, closing))


def _place(base, tok, course_id, module_id, kw, title, html, pages):
    """MODULE-SCOPED: find the kw page IN the module → update its REAL url; 0 → create + add. Never guess a slug."""
    hits = [p for p in pages if kw.lower() in (p.get("title") or "").lower()]
    if len(hits) == 1:
        url = hits[0]["page_url"]
        cr.update_page(base, tok, course_id, url, {"body": html, "published": False})
        return "UPDATED", url
    if len(hits) > 1:
        return "AMBIGUOUS (%d) — resolve by week number, confirm" % len(hits), [h["page_url"] for h in hits]
    pg = cr.create_page(base, tok, course_id, {"title": title, "body": html, "published": False})
    body = pg[1] if isinstance(pg, tuple) else pg
    url = body.get("url")
    cr.post(base, tok, "/courses/%d/modules/%d/items" % (course_id, module_id),
            {"module_item": {"type": "Page", "page_url": url}})
    return "CREATED+placed", url


def _save(cfg, name, html):
    d = os.path.join(cfg["output_dir"], "Canvas-Pages")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "%s.html" % name)
    with open(path, "w") as f:
        f.write(html)
    return path


def _order_ends(base, tok, cid, mid, agenda_url, wrap_url):
    """Agenda -> position 1 (top of the module); Wrap-up -> last. Canvas renumbers positions on each
    move, so re-read the items before placing the wrap-up (they are contiguous after the agenda move)."""
    def _items():
        return cr.get(base, tok, "/courses/%d/modules/%d/items" % (cid, mid), params=[("per_page", "100")]) or []
    def _setpos(iid, pos):
        cr.put(base, tok, "/courses/%d/modules/%d/items/%s" % (cid, mid, iid), {"module_item": {"position": pos}})
    if agenda_url:
        a = next((it for it in _items() if it.get("page_url") == agenda_url), None)
        if a:
            _setpos(a["id"], 1)
    if wrap_url:
        its = _items()
        w = next((it for it in its if it.get("page_url") == wrap_url), None)
        if w:
            # positions can be NON-contiguous (gaps), so len(items) != last position -> use max+1
            last = max((it.get("position") or 0) for it in its) + 1
            _setpos(w["id"], last)


def build_and_place(course_slug, module_id, *, week, intro, topic_bullets, review_note, closing,
                    learned, review_materials="", agenda_title=None, wrap_title=None, place_ends=True,
                    skip_labs=False, greeting="", skip_todo=False,
                    exclude_content_ids=(), also_graded_from=()):
    """Build + place + save both pages. Returns a dict of results. skip_labs=True omits lab items;
    skip_todo=True omits the non-graded to-dos (readings/videos/files) so only graded items show;
    greeting = a warm lead-in paragraph shown after 'Hello students,' before the topic bullets.

    exclude_content_ids = assignment/quiz ids to leave OUT of the agenda. The module item stays in
      place and keeps its published state — this only stops the agenda from telling students to do it.
    also_graded_from = OTHER module ids whose graded items are folded into THIS agenda's table. The
      last week of a term owns the final-exam module's items even though they live in their own
      module; the pages are still created in `module_id` only."""
    cfg = _cfg(course_slug)
    base, tok = cfg["canvas_base_url"], __import__("canvas_token_auth").get_token(cfg["canvas_token_env"], cfg["canvas_base_url"])
    C = cfg["course_id"]
    graded, todo, pages = read_module(base, tok, C, module_id, skip_labs=skip_labs,
                                      skip_todo=skip_todo, exclude_content_ids=exclude_content_ids)
    for extra_mid in also_graded_from:
        g2, _, _ = read_module(base, tok, C, extra_mid, skip_labs=skip_labs, skip_todo=True,
                               exclude_content_ids=exclude_content_ids)
        graded += g2
    agenda = build_agenda(C, graded, todo, intro=intro, topic_bullets=topic_bullets,
                          review_note=review_note, closing=closing, review_materials=review_materials,
                          greeting=greeting)
    wrap = build_wrapup(C, graded, intro=intro.replace(" &mdash;", " Wrap-up &mdash;", 1) if "&mdash;" in intro else intro + " Wrap-up",
                        learned=learned, closing=closing)
    slug = week.lower().replace(" ", "-")
    a = _place(base, tok, C, module_id, "agenda", agenda_title or ("%s Agenda" % week), agenda, pages)
    w = _place(base, tok, C, module_id, "wrap-up", wrap_title or ("%s Wrap-up" % week), wrap, pages)
    if place_ends:   # Agenda -> top of the module, Wrap-up -> bottom (no manual reorder needed)
        _order_ends(base, tok, C, module_id,
                    a[1] if isinstance(a[1], str) else None,
                    w[1] if isinstance(w[1], str) else None)
    return {"agenda": a, "wrapup": w,
            "saved": [_save(cfg, "%s-agenda" % slug, agenda), _save(cfg, "%s-wrapup" % slug, wrap)]}
