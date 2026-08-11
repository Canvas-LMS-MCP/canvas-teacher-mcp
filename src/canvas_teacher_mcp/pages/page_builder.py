"""assignment_page_builder — SKELETON for building a Canvas ASSIGNMENT page (universal core).

Holds ONLY what EVERY assignment page needs; the type-specific content is supplied by a PLUGIN
(git-homework, jshell-lab, or any other course's sub-program) which builds `doc_blocks` +
`canvas_summary_html` and calls `make_page()`. There are NO type-specifics here.

Universal flow (make_page):
  1. IF the plugin supplies `doc_blocks`: make the instruction rich-doc (gws-richdoc) in place — rebuild
     if it exists (same id, stable Canvas URL), else create. Forced anyone-with-link + publish-to-web.
     If `doc_blocks` is None/empty this step is SKIPPED → a gdoc-less, summary-HTML-only page.
  2. assemble the Canvas page = the plugin's summary HTML + (only when a doc was made) a clean-view embed
     of it (📂 share link + [Document Link] /preview + iframe) + an optional slide embed.
  3. save the HTML to the given output path.
  4. optionally push to the Canvas assignment (canvas_rest; description + due_at + points). NEVER sets
     `published` (stays unpublished).

gdoc/slide are OPTIONAL (no `doc_blocks` => no gdoc; no slide url => no slide). Upload(=push here is the
only Canvas write) and GitHub repo work are NOT here.
Canvas access is canonical (canvas_rest) only. Index: code/playbook/canvas-github-access-layers.md
"""
import html as _html
import os
import re as _re
import sys

from ..richdoc import build  # gws-richdoc generator
from ..auth.token import get_token
from ..rest import resources
from ..rest.client import CanvasHTTPError

# The skeleton is CREDENTIAL-AGNOSTIC — it never defaults to a school. The caller (a builder /
# conductor) resolves the course's (base_url, token_env) via `course_config` and passes them in.
# A hardcoded real-school default here caused a wrong-school push (2026-07-26); never restore one.

# Rich-format palette (Canvas strips <style> blocks -> inline styles only).
# NAVY = gws-richdoc banner / "Heading 1" color; table headers + section headers use it.
NAVY = "#1F3864"

# Instruction-gDoc embed size — FIXED SPEC, do not "improve" it.
# WIDTH MUST BE `2048px`, WITH the unit. Google Docs `/preview` scales what it renders to the
# iframe width, so a WIDER iframe shows the document LARGER — this is why the value is a pixel
# count and not a percentage. `100%` was tried 2026-08-02 and is WRONG: it resolves to the
# container (~1200px) and the document renders SMALLER, in both an assignment page and a quiz
# question. Write the unit explicitly; a bare number is not the spec.
DOC_EMBED_W = "2048px"
DOC_EMBED_H = 2096
_CELL_BORDER = "#cfcfcf"

_CODESPAN = ("<span style=\"font-family:'Courier New',monospace;font-weight:bold;background-color:#f2f2f2;"
             "padding:1px 5px;border-radius:3px;border:1px solid #e0e0e0;\">%s</span>")

# callout kinds: (border, background, bold-body?) — the ONE box every builder uses.
_CALLOUT = {
    "warn": ("#e0c000", "#fff59d", True),    # yellow, bold — "do NOT do this" (forbidden functions, hard rules)
    "note": (NAVY, "#eef2f8", False),        # navy — "this is graded" / a deadline the student must not misread
}


# ---- inline text rendering (universal; EVERY item of text goes through this) ----
_RE_MDLINK = _re.compile(r'\[([^\]]+)\]\((\S+?)\)')
_RE_URL = _re.compile(r'(?<![("\'])\bhttps?://[^\s<>"\')\]]+')


def _anchor(url, text):
    return "<a href='%s'>%s</a>" % (_html.escape(str(url), quote=True), _html.escape(str(text)))


def ic(text):
    """Render ONE line of the project's inline notation into Canvas HTML. Escapes everything else.

    Notation — write plain text, never HTML:
        `code`          -> code-font span
        **bold**        -> bold
        [text](url)     -> a clickable link showing `text`
        https://…       -> a clickable link showing the URL

    EVERY helper here (rich_ul/rich_ol/rich_table/section/callout/page_title) runs its text through
    this, so a builder writes text and gets HTML. **Passing real HTML in is a MISTAKE** — it is
    escaped and the student sees the tags. That includes the output of `link()`: do NOT nest it in a
    list, just write the URL or [text](url) and this renders it.

    (History: until 2026-07-17 this lived privately inside git_page as `_ic`, so NB/jshell/flowchart
    pages could not render backticks at all and each builder grew its own renderer. One renderer,
    here. If a mark is missing, ADD IT HERE — do not write a private one in a builder.)
    """
    out = []
    for i, part in enumerate(str(text).split("`")):
        if i % 2:                                   # inside backticks — code, escaped verbatim
            out.append(_CODESPAN % _html.escape(part))
            continue
        # outside backticks: links first (they hold text), then bold, then escape the rest
        pos, buf = 0, []
        for m in _RE_MDLINK.finditer(part):
            buf.append((part[pos:m.start()], None))
            buf.append((None, _anchor(m.group(2), m.group(1))))
            pos = m.end()
        buf.append((part[pos:], None))
        for raw, done in buf:
            if done is not None:
                out.append(done)
                continue
            p, chunks = 0, []
            for m in _RE_URL.finditer(raw):
                chunks.append((raw[p:m.start()], None))
                chunks.append((None, _anchor(m.group(0), m.group(0))))
                p = m.end()
            chunks.append((raw[p:], None))
            for r2, d2 in chunks:
                if d2 is not None:
                    out.append(d2)
                else:
                    out.append("".join(("<b>%s</b>" % _html.escape(b)) if j % 2 else _html.escape(b)
                                       for j, b in enumerate(r2.split("**"))))
    return "".join(out)


def link(url, text=None):
    """A clickable anchor, for building a paragraph by hand. Inside a list/table/callout you do NOT
    need this — write the bare URL or `[text](url)` and ic() renders it."""
    return _anchor(url, text if text else url)


def pre(text):
    """A monospace block (expected output, sample I/O). Content is escaped verbatim — no backticks."""
    return ("<pre style=\"font-family:'Courier New',monospace;background-color:#f2f2f2;padding:10px 12px;"
            "border-radius:4px;border:1px solid #e0e0e0;line-height:1.4;overflow-x:auto;\">%s</pre>"
            % _html.escape(str(text)))


def code_block(text):
    """A DARK code block — for source the student writes or reads (a prototype, a worked snippet).

    Distinct from pre(): pre() is the light grey box for DATA (sample I/O, expected output), this is
    the dark editor-like box for CODE, so a page can show the two without them looking alike.
    """
    return ("<pre style='font-family:Menlo,Consolas,monospace;background:#263238;color:#e0e0e0;"
            "padding:12px 14px;border-radius:6px;overflow:auto;white-space:pre;line-height:1.5;'>%s</pre>"
            % _html.escape(str(text)))


def callout(items, kind="note", title=None):
    """A highlight box. ONE function for every emphasis box on any page type — pass `kind`.

    kind="warn" -> yellow + bold: restrictions / forbidden functions / "do not do this".
    kind="note" -> navy: "this is graded", a deadline, anything the student must not miss.
    `items` = a str (one paragraph) or a list (bullets). `title` = an optional bold lead line.
    """
    border, bg, bold = _CALLOUT[kind]
    weight = "font-weight:bold;" if bold else ""
    head = ("<p style='margin-top:0;'><b>%s</b></p>" % ic(title)) if title else ""
    body = rich_ul(items) if isinstance(items, (list, tuple)) else "<p style='margin:0;'>%s</p>" % ic(items)
    return ("<div style=\"border:2px solid %s;background-color:%s;border-radius:6px;padding:10px 14px;"
            "margin:12px 0;%s\">%s%s</div>" % (border, bg, weight, head, body))


# ---- rich-format HTML helpers (universal; plugins build canvas_summary_html with these) ----
def page_title(title):
    """The page's own title line — navy, one per page, above every section."""
    return "<h2 style='color:%s;'>%s</h2>" % (NAVY, ic(title))


def rich_h(title):
    """Section heading — navy, matches the gdoc Heading-1 color."""
    return "<h3 style='color:%s;margin:18px 0 6px;'>%s</h3>" % (NAVY, ic(title))


def indent(inner_html):
    """Indent a whole section body under its heading (outline style)."""
    return "<div style='margin-left:1.5em;'>%s</div>" % inner_html


def section(title, inner_html):
    """A heading + its fully-indented body."""
    return rich_h(title) + indent(inner_html)


def image(url, alt="", width=None, caption=None):
    """A screenshot inside the page body — a how-to step a picture explains faster than prose
    (where a menu item is, what the finished result looks like).

    `url` is used VERBATIM: a Canvas course-file URL carries a `?verifier=` token, and re-deriving
    or trimming it breaks the image for students. Reuse the URL an existing page already has.
    `width` is a pixel number (Canvas strips <style>, so it goes on the tag).
    """
    w = (" width=\"%s\"" % width) if width else ""
    cap = ("<div style='font-size:0.9em;color:#555;margin-top:2px;'>%s</div>" % ic(caption)) if caption else ""
    return ("<div style='margin:10px 0;'><img src=\"%s\" alt=\"%s\"%s "
            "style=\"max-width:100%%;height:auto;border:1px solid #cccccc;border-radius:4px;\" "
            "loading=\"lazy\">%s</div>" % (url, _html.escape(alt), w, cap))


def steps(items):
    """A labelled walk-through: navy label, body paragraph, optional code block — repeated.

    `items` = [{"label"?: str, "body"?: str, "example"?: str}, ...]. Use it for a step-by-step
    guide or for teaching one concept that needs room. Label and body run through ic(), so
    `backticks`/**bold**/links work; `example` is verbatim code (pre).

    Lives HERE because two different page parts need the same shape (a builder's step-by-step
    guide and its concept section) — a builder that renders it privately would be the copy the
    'skeleton renders, builders assemble' rule forbids.
    """
    out = []
    for st in items or []:
        if st.get("label"):
            out.append("<p style='margin:16px 0 4px;color:%s;'><b>%s</b></p>" % (NAVY, ic(st["label"])))
        if st.get("body"):
            out.append("<p style='margin:4px 0;line-height:1.7;'>%s</p>" % ic(st["body"]))
        if st.get("example"):
            out.append(code_block(st["example"]))
    return "".join(out)


def _li(item):
    """A list item; a (label, [sub...]) tuple becomes a bold label + nested list.

    Text runs through ic() -> `backticks` render as code font. (Before 2026-07-17 this escaped
    instead, so backticks died and every builder rolled its own list — that is exactly how
    git_page grew a private _ic/_ul copy. Render here; do not copy.)
    """
    if isinstance(item, (tuple, list)) and len(item) == 2 and isinstance(item[1], (list, tuple)):
        return "<li><b>%s</b>%s</li>" % (ic(item[0]), rich_ul(item[1]))
    return "<li>%s</li>" % ic(item)


def rich_ul(items):
    return ("<ul style='margin:4px 0 4px 1.2em;line-height:1.6;'>"
            + "".join(_li(x) for x in items) + "</ul>")


def rich_ol(items):
    return ("<ol style='margin:4px 0 4px 1.2em;line-height:1.6;'>"
            + "".join(_li(x) for x in items) + "</ol>")


def code_span(text):
    """Inline monospace code token (red on light bg) — for file names, commands, commit messages."""
    return ("<code style='font-family:Menlo,Consolas,monospace;color:#c7254e;background:#f9f2f4;"
            "padding:1px 5px;border-radius:3px;'>%s</code>" % _html.escape(text))


def rich_table(headers, rows):
    """Bordered table with a navy shaded header row (white text). rows = list of cell-string lists.

    Cells run through ic() -> `backticks` render as code font inside a table too.
    """
    th = "".join("<th style='background:%s;color:#fff;text-align:left;padding:6px 12px;"
                 "border:1px solid %s;'>%s</th>" % (NAVY, NAVY, ic(h)) for h in headers)
    body = "".join(
        "<tr>" + "".join("<td style='padding:6px 12px;border:1px solid %s;'>%s</td>"
                         % (_CELL_BORDER, ic(c)) for c in r) + "</tr>"
        for r in rows)
    return ("<table style='border-collapse:collapse;margin:8px 0;'>"
            "<tr>%s</tr>%s</table>" % (th, body))


# ---- shared helpers (universal) ----
def drive_short_path(file_id, depth=3):
    """REAL trimmed Drive location ('<ancestor>/.../<folder>/<name>') from the file's parent chain."""
    try:
        m = build._gws(["drive", "files", "get"], params={"fileId": file_id, "fields": "name,parents"})
        names = [m.get("name", "?")]
        pid = (m.get("parents") or [None])[0]
        for _ in range(depth):
            if not pid:
                break
            p = build._gws(["drive", "files", "get"], params={"fileId": pid, "fields": "name,parents"})
            names.append(p.get("name", "?"))
            pid = (p.get("parents") or [None])[0]
        return "/".join(reversed(names))
    except Exception:
        return ""


def embed_block(link_text, preview_url, edit_url, embed_url, file_id=None, height=900, width="100%"):
    """Clean-view embed line: a SMALL source marker (↗ → the /edit source, instructor-only maintenance
    pointer, real Drive path on hover) + [link] → /preview (no Docs header, clean view); then the iframe;
    then <hr>. The marker is deliberately tiny — students use [link]/preview; the ↗ is just to check where
    the embed points. NO emoji (Canvas rule)."""
    short = _html.escape(drive_short_path(file_id), quote=True) if file_id else ""
    title = (" title='%s'" % short) if short else ""
    folder = ("<a href='%s'%s>↗</a> " % (edit_url, title)) if edit_url else ""
    return ("<p>%s<a href='%s'%s>%s</a></p>"
            "<p><iframe src='%s' width='%s' height='%d' style='border:1px solid #cccccc;' loading='lazy'></iframe></p>"
            "<hr>" % (folder, preview_url, title, link_text, embed_url, width, height))


def _one_slide_embed(slide_embed_url):
    """The clean-view embed block for ONE slide URL (no header)."""
    sid = ""
    if "/presentation/d/" in slide_embed_url:
        seg = slide_embed_url.split("/presentation/d/", 1)[1].split("/", 1)[0]
        sid = "" if seg == "e" else seg
    sopen = ("https://docs.google.com/presentation/d/%s/preview" % sid) if sid else slide_embed_url
    sedit = ("https://docs.google.com/presentation/d/%s/edit" % sid) if sid else slide_embed_url
    return embed_block("[Slides Link]", sopen, sedit, slide_embed_url, sid, height=569)


def slide_embed(slide_embed_url):
    """Clean-view slide embed(s). Accepts a single URL (str) OR a LIST of URLs — e.g. a lab whose
    Lab-Activity spans several slides (8-1, 8-2, 8-3). One "Slides" header, then each slide. '' if none.

    PUBLIC: a builder that wants the deck somewhere other than make_page's default (appended last)
    calls this itself — e.g. git_page puts it at the TOP. Do not reach for the old `_slide_embed`.
    """
    if not slide_embed_url:
        return ""
    urls = slide_embed_url if isinstance(slide_embed_url, (list, tuple)) else [slide_embed_url]
    urls = [u for u in urls if u]
    if not urls:
        return ""
    return "<h3>Slides</h3>\n" + "\n".join(_one_slide_embed(u) for u in urls)


# ---- universal doc make (in place) ----
def _find_doc_id(name, folder_id):
    q = ("name = '%s' and '%s' in parents and trashed = false and "
         "mimeType = 'application/vnd.google-apps.document'" % (name.replace("'", "\\'"), folder_id))
    files = build._gws(["drive", "files", "list"], params={"q": q, "fields": "files(id,name)"}).get("files", [])
    return files[0]["id"] if files else None


def make_doc(name, doc_blocks, folder_id):
    """Create OR update-in-place the instruction doc (same id, stable URL) — never duplicates."""
    existing = _find_doc_id(name, folder_id)
    if existing:
        build.rebuild(existing, doc_blocks)
        return existing
    return build.make(doc_blocks, name=name, folder_id=folder_id)


# ---- universal Canvas push (canonical, never publishes) ----
def push(course_id, assignment_id, html, due_at=None, points=None, base=None, token_env=None):
    if not base or not token_env:
        raise ValueError(
            "push(): base and token_env are REQUIRED — the skeleton is credential-agnostic (no "
            "default school). Resolve them via course_config.canvas_coords(<slug|course_id>). "
            "See code/README ◆ Config.")
    token = get_token(token_env, base)
    try:
        cur = resources.fetch_assignment(base, token, course_id, assignment_id)
    except CanvasHTTPError as e:
        # 404 here = the id does not exist on THIS Canvas host — the wrong-school signature
        # (2026-07-26 incident). Keep the diagnosis; don't let a raw HTTP error bury it.
        raise ValueError("push(): assignment %s not found on %s (HTTP %s) — wrong base/token_env "
                         "for this course?" % (assignment_id, base, e.status)) from e
    if cur is None:
        raise ValueError("push(): assignment %s not found on %s — wrong base/token_env for this "
                         "course?" % (assignment_id, base))
    bak = "/tmp/asmt_%s_desc.backup.html" % assignment_id
    open(bak, "w").write(cur.get("description", "") or "")
    fields = {"description": html}
    if due_at is not None:
        fields["due_at"] = due_at
    if points is not None:
        fields["points_possible"] = points
    resources.update_assignment(base, token, course_id, assignment_id, fields)  # NEVER sets published
    return bak


# ---- the plugin hook ----
def make_page(course_id, assignment_id, name, doc_blocks, canvas_summary_html, *,
              pages_folder=None, output_path, slide_embed_url=None,
              push_canvas=False, due_at=None, points=None, base=None, token_env=None,
              doc_embed_width=DOC_EMBED_W, doc_embed_height=DOC_EMBED_H):
    """Universal builder. The PLUGIN supplies `canvas_summary_html` (the page's summary sections) and,
    OPTIONALLY, `doc_blocks` (gws-richdoc blocks for a detailed instruction doc). The skeleton builds the
    doc + embed ONLY when `doc_blocks` is given (then `pages_folder` is required); otherwise the page is
    summary-HTML-only (a gdoc-less Canvas page). An optional slide embed is appended either way. Saves,
    and (optionally) pushes. Returns a dict (`doc_id`/`doc_url` = None when no doc was made)."""
    parts = [canvas_summary_html]
    doc_id = doc_edit = None
    if doc_blocks:                       # gdoc is OPTIONAL — build it only when the plugin supplies blocks
        doc_id = make_doc(name, doc_blocks, pages_folder)
        doc_preview = "https://docs.google.com/document/d/%s/preview" % doc_id
        doc_edit = "https://docs.google.com/document/d/%s/edit" % doc_id
        parts += ["<h3>Full guide</h3>",
                  embed_block("[Document Link]", doc_preview, doc_edit, doc_preview, doc_id,
                              height=doc_embed_height, width=doc_embed_width)]
    parts.append(slide_embed(slide_embed_url))
    html = "\n".join(parts)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        f.write(html)
    out = {"doc_id": doc_id, "doc_url": doc_edit, "html": html, "html_path": output_path}
    if push_canvas:
        out["backup"] = push(course_id, assignment_id, html, due_at, points, base, token_env)
        out["pushed"] = True
    return out
