#!/usr/bin/env python3
"""gws-richdoc build.py — the ONE deterministic richdoc generator.

Implements the gws-richdoc SKILL.md block catalog as code, so every doc gets the
SAME look. Architecture is the agreed HYBRID:

    AI (front)   : turns raw input -> block specs (judgement: which block, text).
    build.py     : owns the LOOK. block HTML (fixed palette/fonts/spacers) +
                   make() (create -> HTML import -> refine) + refine() batchUpdate
                   + deterministic code token coloring.  <-- final pixels live here
    AI (QA only) : after import, inspects/flags; never restyles.

Two entry points:
  make(blocks, name, folder_id)      -> create a NEW rich doc (import path).
  colorize_code_cell(doc_id, ...)    -> color code in an EXISTING doc IN-PLACE
                                        (no re-import; preserves images/edits).

Code coloring: shell via regex, Python via stdlib `tokenize` (no external dep).
Python supports two docstring modes:
  mode="correct"  -> a docstring is ONE string color (what a real editor shows).
  mode="pretty"   -> docstring inner text is re-tokenized as code and colored
                     (syntactically wrong, but reads like live highlighted code).
"""
from __future__ import annotations

import html as _html
import io
import json
import keyword
import subprocess
import tempfile
import tokenize as _tok

# ---------------------------------------------------------------------------
# Palette (matches SKILL.md + master template 1UzJhVARxgVB_49KcJg5BxyqIxeKPTiJnf1iRDBEVt6I)
# ---------------------------------------------------------------------------
NAVY        = "#1F3864"   # banner, step badge number, badge title text
BADGE_BAR   = "#ECEFF1"   # step badge title bar
INFO_BG     = "#E3F2FD"; INFO_FG = "#1565C0"   # overview / info (light blue)
TIP_BG      = "#E8F5E9"; TIP_FG  = "#2E7D32"   # tip (green)
WARN_BG     = "#FFF3E0"; WARN_FG = "#E65100"   # warning (orange)
CODE_BG     = "#263238"; CODE_FG = "#E0E0E0"   # code (dark)
BANNER_DESC = "#BBDEFB"  # banner descriptor (light blue, italic)
WHITE       = "#FFFFFF"

# Cell layout — uniform so boxes/badges/tables are not "fat". (2026-06-28)
PAD    = "4.32pt"        # = 0.06in, applied to EVERY table cell
VALIGN = "vertical-align:middle;"   # every cell centered vertically
NOSP   = "margin:0;"     # every paragraph: no space before/after

# section_box rotates color per BIG section (everything else is uniform navy).
SECTION_COLORS = {
    "green":  "#00695C",
    "purple": "#6A1B9A",
    "blue":   "#1565C0",
    "teal":   "#00838F",
    "indigo": "#283593",
    "navy":   NAVY,
}

BODY_FONT = "Lato"
HEAD_FONT = "Arial"
CODE_FONT = "Consolas"

# ---------------------------------------------------------------------------
# Code-color palettes
# ---------------------------------------------------------------------------
# Shell (per SKILL.md token rules, on CODE_BG)
SH = {
    "comment": "#9E9E9E",   # # ...
    "prompt":  "#A5D6A7",   # $ at line start
    "string":  "#80CBC4",   # '...' "..." and paths
    "cmd":     CODE_FG,     # command / flags / default
}
# Python (VS Code Dark+ on CODE_BG)
PY = {
    "keyword": "#569CD6",   # def return if for ...
    "func":    "#DCDCAA",   # name after def / a call name(
    "string":  "#CE9178",   # '...' "..." f"..." docstrings
    "comment": "#6A9955",   # # ...
    "number":  "#B5CEA8",
    "dunder":  "#9CDCFE",   # __name__ __main__-ish names
    "const":   "#569CD6",   # True False None
    "builtin": "#4EC9B0",   # print len range ...
    "default": CODE_FG,     # operators / punctuation / plain names
}
_PY_BUILTINS = {
    "print", "len", "range", "int", "str", "float", "bool", "list", "dict",
    "set", "tuple", "input", "open", "enumerate", "zip", "map", "filter",
    "sum", "min", "max", "abs", "sorted", "reversed", "type", "isinstance",
    "super", "object", "Exception",
}
_PY_CONSTS = {"True", "False", "None"}


# ---------------------------------------------------------------------------
# Code tokenizers  ->  list of (start_offset, end_offset, hexcolor)
# Offsets are 0-based character offsets into `code`. Whitespace/uncolored spans
# are simply omitted (they keep the cell default CODE_FG).
# ---------------------------------------------------------------------------
def _line_starts(code: str):
    """offs[n] = absolute char offset of the start of 1-based line n+1."""
    offs = [0]
    pos = 0
    for line in code.splitlines(keepends=True):
        pos += len(line)
        offs.append(pos)
    return offs


def color_shell(code: str):
    spans = []
    pos = 0
    for line in code.splitlines(keepends=True):
        body = line.rstrip("\n")
        base = pos
        stripped = body.lstrip()
        indent = len(body) - len(stripped)
        if stripped.startswith("#"):
            spans.append((base, base + len(body), SH["comment"]))
        else:
            if stripped.startswith("$"):
                spans.append((base + indent, base + indent + 1, SH["prompt"]))
            i = 0
            while i < len(body):
                c = body[i]
                if c in "'\"":
                    j = i + 1
                    while j < len(body) and body[j] != c:
                        j += 1
                    spans.append((base + i, base + min(j + 1, len(body)), SH["string"]))
                    i = j + 1
                else:
                    i += 1
        pos += len(line)
    return spans


def _py_token_color(toknum, tokval, prev_significant):
    name = _tok.tok_name.get(toknum, "")
    if name == "COMMENT":
        return PY["comment"]
    if name in ("STRING", "FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END"):
        return PY["string"]
    if name == "NUMBER":
        return PY["number"]
    if name == "NAME":
        if tokval in _PY_CONSTS:
            return PY["const"]
        if keyword.iskeyword(tokval):
            return PY["keyword"]
        if tokval.startswith("__") and tokval.endswith("__"):
            return PY["dunder"]
        if prev_significant in ("def", "class"):
            return PY["func"]
        if tokval in _PY_BUILTINS:
            return PY["builtin"]
        return PY["default"]
    return None


def color_python(code: str, mode: str = "correct"):
    """Color spans for Python `code`. Robust to incomplete code: collects tokens
    until the tokenizer raises, keeps the partial result."""
    offs = _line_starts(code)

    def abs_off(row, col):
        return offs[row - 1] + col

    spans = []
    prev_significant = None
    try:
        for tk in _tok.generate_tokens(io.StringIO(code).readline):
            toknum, tokval, (sr, sc), (er, ec), _ = tk
            name = _tok.tok_name.get(toknum, "")
            s = abs_off(sr, sc); e = abs_off(er, ec)
            if (mode == "pretty" and name == "STRING"
                    and (tokval[:3] in ('"""', "'''")) and "\n" in tokval):
                q = tokval[:3]
                inner = tokval[3:-3] if tokval.endswith(q) else tokval[3:]
                inner_off = s + 3
                spans.append((s, s + 3, PY["string"]))
                if tokval.endswith(q):
                    spans.append((e - 3, e, PY["string"]))
                for isp in color_python(inner, mode="correct"):
                    spans.append((inner_off + isp[0], inner_off + isp[1], isp[2]))
                prev_significant = None
                continue
            col = _py_token_color(toknum, tokval, prev_significant)
            if col is not None:
                spans.append((s, e, col))
            if name in ("NAME", "OP"):
                prev_significant = tokval
            elif name not in ("NEWLINE", "NL", "INDENT", "DEDENT", "COMMENT"):
                prev_significant = None
    except (_tok.TokenError, IndentationError, SyntaxError):
        pass
    return spans


def code_spans(code: str, lang: str, mode: str = "correct"):
    # nbsp indentation (from _esc_code) -> real spaces for the tokenizer; same length,
    # so every color offset still maps 1:1 to its document index.
    code = code.replace("\xa0", " ")
    if lang == "python":
        return color_python(code, mode=mode)
    if lang in ("shell", "bash", "sh"):
        return color_shell(code)
    return []


# ---------------------------------------------------------------------------
# gws helpers
# ---------------------------------------------------------------------------
def _gws(args, params=None, body=None):
    """Run a gws command. params -> --params (URL/query), body -> --json (request body)."""
    cmd = ["gws"] + args
    if params is not None:
        cmd += ["--params", json.dumps(params)]
    if body is not None:
        cmd += ["--json", json.dumps(body)]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"gws {' '.join(args)} failed:\n{out.stderr}\n{out.stdout}")
    txt = out.stdout
    i = txt.find("{")
    return json.loads(txt[i:]) if i >= 0 else {}


def doc_get(doc_id):
    return _gws(["docs", "documents", "get"], {"documentId": doc_id})


def doc_batch(doc_id, requests):
    if not requests:
        return {}
    return _gws(["docs", "documents", "batchUpdate"],
                params={"documentId": doc_id}, body={"requests": requests})


# ---------------------------------------------------------------------------
# IN-PLACE code coloring for an existing doc (preserves images/edits)
# ---------------------------------------------------------------------------
def _is_code_bg(rgb):
    """True only for a CODE cell bg (dark + near-gray, e.g. #263238 / #2B2B2B).
    Excludes navy boxes (#1F3864) and other colored boxes: those are dark-ish but
    have a large channel spread (blue >> red/green), so spread<0.12 rejects them."""
    if not rgb:
        return False
    r = rgb.get("red", 0); g = rgb.get("green", 0); b = rgb.get("blue", 0)
    avg = (r + g + b) / 3
    spread = max(r, g, b) - min(r, g, b)
    return avg < 0.30 and spread < 0.12


def _find_code_cells(doc):
    """Yield (cell_text, base_index) for every dark single-cell table."""
    for el in doc["body"]["content"]:
        if "table" not in el:
            continue
        cell = el["table"]["tableRows"][0]["tableCells"][0]
        bg = (cell.get("tableCellStyle", {}).get("backgroundColor", {})
              .get("color", {}).get("rgbColor", {}))
        if not _is_code_bg(bg):
            continue
        text = ""; base = None
        for para in cell["content"]:
            if "paragraph" not in para:
                continue
            for r in para["paragraph"].get("elements", []):
                tr = r.get("textRun")
                if not tr:
                    continue
                if base is None:
                    base = r["startIndex"]
                text += tr["content"]
        if base is not None:
            yield text, base


def _hex_to_rgb(h):
    h = h.lstrip("#")
    return {"red": int(h[0:2], 16) / 255,
            "green": int(h[2:4], 16) / 255,
            "blue": int(h[4:6], 16) / 255}


def _color_requests(text, base, spans):
    reqs = []
    for s, e, hexcol in spans:
        reqs.append({
            "updateTextStyle": {
                "range": {"startIndex": base + s, "endIndex": base + e},
                "textStyle": {"foregroundColor": {"color": {"rgbColor": _hex_to_rgb(hexcol)}}},
                "fields": "foregroundColor",
            }
        })
    return reqs


def colorize_code_cell(doc_id, lang="python", mode="correct", which=0, apply=True):
    """Color the `which`-th dark code cell of an existing doc, in place.
    Returns the batchUpdate requests (also applies them if apply=True)."""
    doc = doc_get(doc_id)
    cells = list(_find_code_cells(doc))
    if not cells:
        raise RuntimeError("no dark code cell found in doc")
    text, base = cells[which]
    reqs = _color_requests(text, base, code_spans(text, lang, mode=mode))
    if apply and reqs:
        doc_batch(doc_id, reqs)
    return reqs


# ---------------------------------------------------------------------------
# Block builders (HTML fragments). Inline styles only (Docs import keeps cell
# bg + fg colors). assemble() adds spacers around boxes.
# ---------------------------------------------------------------------------
def _esc(s):
    return _html.escape(s).replace("\n", "<br>")


# Inline code-font: every `backtick` span in body/bullet text becomes a monospace code span.
# Text with no backticks is unchanged (backward-compatible). font-family is a SINGLE name
# (no comma fallback list) — Google Docs HTML-import drops a comma-separated font list, same
# as the working code() block which uses CODE_FONT alone.
_IC_SPAN = ('<span style="font-family:{f};background-color:#f2f2f2;">{t}</span>'
            ).format(f=CODE_FONT, t="{t}")


def _ic(s):
    """Escape text; turn every `backtick` span into a monospace code span (keeps <br> on newlines)."""
    parts = str(s).split("`")
    return "".join(
        (_IC_SPAN.format(t=_html.escape(p)) if i % 2 else _html.escape(p).replace("\n", "<br>"))
        for i, p in enumerate(parts))


def _esc_code(s):
    """Like _esc but PRESERVES leading indentation — Google Docs HTML-import collapses
    leading spaces in a span, which destroys Python indentation. Convert each line's
    leading-space run to &nbsp; (kept on import); interior spaces stay (allow wrapping)."""
    out = []
    for line in s.split("\n"):
        stripped = line.lstrip(" ")
        indent = len(line) - len(stripped)
        out.append("&nbsp;" * indent + _html.escape(stripped))
    return "<br>".join(out)


def _cell(bg, inner, pad=PAD):
    return (f'<table style="width:100%;border-collapse:collapse;">'
            f'<tr><td style="background-color:{bg};padding:{pad};{VALIGN}">{inner}</td></tr></table>')


def banner(title, summary="", descriptor=""):
    # TITLE cell = left ORIGINAL (no 0.06 padding / no vertical-center / no para-space-removal).
    # Per instruction (2026-06-28): the layout pass must NOT touch the banner. refine() also skips it.
    inner = f'<p style="color:{WHITE};font-size:20pt;"><b>{_esc(title)}</b></p>'
    if summary:
        inner += f'<p style="color:{WHITE};font-size:11pt;">{_esc(summary)}</p>'
    if descriptor:
        inner += f'<p style="color:{BANNER_DESC};font-size:9pt;"><i>{_esc(descriptor)}</i></p>'
    bannerhtml = (f'<table style="width:100%;border-collapse:collapse;">'
                  f'<tr><td style="background-color:{NAVY};padding:9pt;">{inner}</td></tr></table>')
    return {"kind": "box", "html": bannerhtml}


def section_box(title, subtitle="", color=None):
    # UNIFORM color — section boxes no longer rotate (decided 2026-06-28). The `color` arg is kept
    # for backward-compat but is IGNORED. Soft, spreadsheet-style sky-blue background with dark navy
    # text (changed 2026-07-13): the old white-on-indigo header was too heavy when a section had
    # little content beneath it. Light bg + dark bold text reads clean whether the section is long or short.
    bg = "#E3F2FD"   # soft sky-blue (matches INFO_BG); barely-there section band
    inner = f'<p style="{NOSP}color:{NAVY};font-size:16pt;"><b>{_esc(title)}</b></p>'
    if subtitle:
        inner += f'<p style="{NOSP}color:{NAVY};font-size:11pt;"><i>{_esc(subtitle)}</i></p>'
    return {"kind": "box", "html": _cell(bg, inner)}


def step_badge(num, title):
    return {"kind": "box", "html":
        f'<table style="width:100%;border-collapse:collapse;">'
        f'<tr><td style="background-color:{NAVY};width:36pt;text-align:center;padding:{PAD};{VALIGN}">'
        f'<span style="color:{WHITE};font-size:14pt;"><b>{num}</b></span></td>'
        f'<td style="background-color:{BADGE_BAR};padding:{PAD};{VALIGN}">'
        f'<span style="color:{NAVY};font-size:14pt;"><b>&nbsp;{_esc(title)}</b></span></td></tr></table>'}


def _callout(bg, fg, glyph, lines):
    # RULE #1 (readability, 2026-07-13): outline form — each line is its OWN bullet, never a run-on wall.
    #   • bullets            (one item = one bullet, not <br>-joined text)
    #   • hanging indent     (wrapped lines align under the text, not under the bullet)
    #   • line breaks        (each item on its own paragraph)
    #   • breathing room     (6pt gap between items; box has padding)
    # `glyph` is kept for backward-compat but NOT rendered (the box color already signals the type;
    # dropping the emoji keeps it clean and honors the no-emoji rule).
    if isinstance(lines, str):
        lines = [lines]
    n = len(lines)
    items = "".join(
        '<p style="margin:0 0 %s 0;padding-left:1.5em;text-indent:-1.1em;color:%s;">'
        '&bull;&nbsp;&nbsp;%s</p>' % ("6pt" if i < n - 1 else "0", fg, _esc(x))
        for i, x in enumerate(lines))
    return {"kind": "box", "html": _cell(bg, items)}


def overview(lines):
    if isinstance(lines, str):
        lines = [lines]
    inner = f'<p style="{NOSP}color:{INFO_FG};font-size:14pt;"><b>Overview</b></p>'
    inner += '<br>'.join(f'<span style="color:{INFO_FG};">&bull; {_esc(x)}</span>' for x in lines)
    return {"kind": "box", "html": _cell(INFO_BG, inner)}


def info(lines):
    return _callout(INFO_BG, INFO_FG, "💬 ", lines)


def tip(lines):
    return _callout(TIP_BG, TIP_FG, "💡 ", lines)


def warning(lines):
    return _callout(WARN_BG, WARN_FG, "⚠ ", lines)


def code(text, lang="python"):
    return {"kind": "box",
            "html": _cell(CODE_BG, f'<span style="color:{CODE_FG};font-family:{CODE_FONT};">{_esc_code(text)}</span>'),
            "code": text, "lang": lang}


def body(text):
    return {"kind": "text", "html": f'<p style="{NOSP}font-size:11pt;">{_ic(text)}</p>'}


def _li(item):
    """One <li>. Nesting: an item can be (head, [subitems]) → head with an indented sub-list.
    Inline `backtick` spans render as code font."""
    if isinstance(item, (list, tuple)) and len(item) == 2 and isinstance(item[1], (list, tuple)):
        head, subs = item
        return f"<li>{_ic(head)}<ul>" + "".join(_li(s) for s in subs) + "</ul></li>"
    return f"<li>{_ic(item)}</li>"


def bullets(items):
    """Circle bullets. For hierarchy, an item may be a (head, [subitems]) tuple → indented sub-bullets.
    e.g. bullets([("Do", ["step a", "step b"]), ("Explain", ["q1", "q2"])])."""
    return {"kind": "text", "html": "<ul>" + "".join(_li(x) for x in items) + "</ul>"}


def numbered(items):
    return {"kind": "text", "html": "<ol>" + "".join(f"<li>{_esc(x)}</li>" for x in items) + "</ol>"}


def link(text, url):
    """A clickable hyperlink paragraph (survives Google Docs HTML import as a real link).
    Use this for links — `body(url)` only renders plain text, NOT a clickable link."""
    return {"kind": "text",
            "html": f'<p style="{NOSP}font-size:11pt;"><a href="{_html.escape(url, quote=True)}">{_esc(text)}</a></p>'}


def image(url, width=600):
    """A centered embedded image slot. `url` = a PUBLIC image URL (Drive anyone-with-link:
    `https://lh3.googleusercontent.com/d/<fileId>`). The <img> is part of the block HTML, so
    Google Docs HTML-import embeds it and it SURVIVES every make()/rebuild. Called by a driver
    only when it passes an image; omit it and nothing is added (like link()/body())."""
    return {"kind": "text",
            "html": f'<p style="text-align:center;"><img src="{_html.escape(url, quote=True)}" '
                    f'width="{int(width)}"/></p>'}


def table(headers, rows):
    """A simple bordered data table (e.g. a grading rubric). headers=list of str,
    rows=list of lists. Light header bar (never dark → not mistaken for a code cell)."""
    th = "".join(
        f'<th style="background-color:{BADGE_BAR};border:1px solid #bbb;padding:{PAD};{VALIGN}'
        f'text-align:left;color:{NAVY};">{_esc(str(h))}</th>' for h in headers)
    trs = "".join(
        "<tr>" + "".join(f'<td style="border:1px solid #ccc;padding:{PAD};{VALIGN}">{_esc(str(c))}</td>'
                         for c in r) + "</tr>" for r in rows)
    return {"kind": "box",
            "html": f'<table style="width:100%;border-collapse:collapse;"><tr>{th}</tr>{trs}</table>'}


def assemble(blocks):
    """Join blocks; blank spacer paragraph on BOTH sides of every box
    (Google Docs ignores paragraph spacing next to tables)."""
    SP = "<p>&nbsp;</p>"
    out = ["<html><body>"]
    prev_box = False
    for b in blocks:
        is_box = b["kind"] == "box"
        if is_box or prev_box:
            out.append(SP)
        out.append(b["html"])
        prev_box = is_box
    out.append(SP)
    out.append("</body></html>")
    return "".join(out)


# ---------------------------------------------------------------------------
# make() — create a NEW rich doc (import path) then refine().
# ---------------------------------------------------------------------------
def make(blocks, name, folder_id=None, code_mode="correct"):
    html_doc = assemble(blocks)
    meta = {"name": name, "mimeType": "application/vnd.google-apps.document"}
    if folder_id:
        meta["parents"] = [folder_id]
    created = _gws(["drive", "files", "create"], body=meta)
    doc_id = created["id"]
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as f:
        f.write(html_doc)
        html_path = f.name
    _gws(["drive", "files", "update", "--upload", html_path],
         params={"fileId": doc_id})
    refine(doc_id, blocks, code_mode=code_mode)
    # FORCED on every creation: share anyone-with-link (reader) — unconditional, so the
    # Canvas embed renders and students can open without a manual share step.
    _gws(["drive", "permissions", "create"],
         params={"fileId": doc_id},
         body={"role": "reader", "type": "anyone"})
    # FORCED on every creation: Publish-to-web (embed enabled) on the latest revision — so
    # /pub + /pubembed work and the iframe renders cleanly. publishAuto keeps it published as the
    # doc is edited. (Verified: revisions.update sets published/publishAuto/publishedOutsideDomain.)
    _revs = _gws(["drive", "revisions", "list"], params={"fileId": doc_id}).get("revisions", [])
    if _revs:
        _gws(["drive", "revisions", "update"],
             params={"fileId": doc_id, "revisionId": _revs[-1]["id"]},
             body={"published": True, "publishAuto": True, "publishedOutsideDomain": True})
    return doc_id


def rebuild(doc_id, blocks, code_mode="correct"):
    """Re-import block HTML into an EXISTING doc id (replaces content, KEEPS the same
    ID + sharing), then refine. Use ONLY when the doc has no images/edits to preserve
    (re-import wipes everything). For image docs use colorize_code_cell / in-place edits."""
    html_doc = assemble(blocks)
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as f:
        f.write(html_doc)
        html_path = f.name
    _gws(["drive", "files", "update", "--upload", html_path], params={"fileId": doc_id})
    refine(doc_id, blocks, code_mode=code_mode)
    return doc_id


PARA_SPACE_PT = 6   # breathing room BELOW each top-level paragraph / bullet (not inside boxes)


def _zero_space_requests(doc):
    """Paragraph spacing, per location (2026-07-17):
      - INSIDE a box (any table: banner/section_box/step_badge/code/callout/data table) -> 0/0,
        so boxes stay slim (a fat box was the reason spacing was zeroed in the first place).
      - a TOP-LEVEL paragraph / bullet (outside every box) -> spaceBelow = PARA_SPACE_PT,
        so the explanatory text and bullet lists BREATHE instead of packing tight.
    Was: zeroed EVERY paragraph in one range -> the whole doc packed. HTML margin does not survive
    Docs import, so this is set via the API after import.
    (Docs ignores paragraph spacing on a paragraph that directly touches a table - the builder
    already puts a blank spacer paragraph at those boundaries, so box edges are unaffected.)"""
    def para_ranges_in_tables(content):
        out = []
        for el in content:
            if "table" in el:
                for row in el["table"]["tableRows"]:
                    for c in row["tableCells"]:
                        for e in c["content"]:
                            if "paragraph" in e:
                                out.append((e["startIndex"], e["endIndex"]))
                        out += para_ranges_in_tables(c["content"])
        return out

    content = doc.get("body", {}).get("content", [])
    if not content:
        return []
    reqs = []
    # top-level paragraphs/bullets -> breathing room below
    for el in content:
        if "paragraph" in el and el["endIndex"] > el["startIndex"]:
            reqs.append({"updateParagraphStyle": {
                "range": {"startIndex": el["startIndex"], "endIndex": el["endIndex"]},
                "paragraphStyle": {"spaceAbove": {"magnitude": 0, "unit": "PT"},
                                   "spaceBelow": {"magnitude": PARA_SPACE_PT, "unit": "PT"}},
                "fields": "spaceAbove,spaceBelow"}})
    # inside every box/table -> zero, so boxes stay slim
    for s, e in para_ranges_in_tables(content):
        if e > s:
            reqs.append({"updateParagraphStyle": {
                "range": {"startIndex": s, "endIndex": e},
                "paragraphStyle": {"spaceAbove": {"magnitude": 0, "unit": "PT"},
                                   "spaceBelow": {"magnitude": 0, "unit": "PT"}},
                "fields": "spaceAbove,spaceBelow"}})
    return reqs


def _iter_runs(content):
    """Yield (startIndex, endIndex, textStyle, in_code_cell) for every textRun, descending into
    tables. in_code_cell = the run sits inside a dark code cell (single-cell dark table)."""
    for el in content:
        if "paragraph" in el:
            for e in el["paragraph"].get("elements", []):
                if "textRun" in e:
                    yield e["startIndex"], e["endIndex"], e["textRun"].get("textStyle", {}), False
        if "table" in el:
            cell0 = el["table"]["tableRows"][0]["tableCells"][0]
            bg = (cell0.get("tableCellStyle", {}).get("backgroundColor", {})
                  .get("color", {}).get("rgbColor", {}))
            code_cell = _is_code_bg(bg)
            for row in el["table"]["tableRows"]:
                for c in row["tableCells"]:
                    for s, e, ts, _ in _iter_runs(c["content"]):
                        yield s, e, ts, code_cell


def _is_inline_code_marker(ts):
    """True if a run carries the #f2f2f2 inline-code background that _ic emits and that DOES
    survive HTML import — used to re-apply the monospace font the import strips."""
    bg = ts.get("backgroundColor", {}).get("color", {}).get("rgbColor", {})
    if not bg:
        return False
    r = bg.get("red", 0); g = bg.get("green", 0); b = bg.get("blue", 0)
    return abs(r - 0.949) < 0.04 and abs(g - 0.949) < 0.04 and abs(b - 0.949) < 0.04


def _mono_font_requests(doc):
    """Set the monospace font on inline code spans (#f2f2f2 marker) AND dark code cells.
    Google Docs HTML-import DROPS font-family (inline + code blocks both land as Arial), so the
    code font must be applied via the API afterwards. Style-only (no index shift)."""
    reqs = []
    for s, e, ts, code_cell in _iter_runs(doc.get("body", {}).get("content", [])):
        if e <= s:
            continue
        if code_cell or _is_inline_code_marker(ts):
            reqs.append({"updateTextStyle": {
                "range": {"startIndex": s, "endIndex": e},
                "textStyle": {"weightedFontFamily": {"fontFamily": CODE_FONT}},
                "fields": "weightedFontFamily"}})
    return reqs


def refine(doc_id, blocks=None, code_mode="correct"):
    """Deterministic post-import fixups: (1) zero paragraph space before/after (banner excluded),
    (2) monospace font on code (inline #f2f2f2 spans + dark code cells; import strips font-family),
    (3) code token coloring. All style-only (no index shift) so they batch together."""
    doc = doc_get(doc_id)
    reqs = _zero_space_requests(doc)
    reqs += _mono_font_requests(doc)
    langs = [b.get("lang", "python") for b in (blocks or [])
             if b.get("kind") == "box" and "code" in b]
    for i, (text, base) in enumerate(_find_code_cells(doc)):
        lang = langs[i] if i < len(langs) else "python"
        reqs += _color_requests(text, base, code_spans(text, lang, mode=code_mode))
    doc_batch(doc_id, reqs)
    return reqs


if __name__ == "__main__":
    print("gws-richdoc build.py — import as a module. "
          "blocks: banner section_box step_badge overview info tip warning code bullets numbered body. "
          "make(blocks, name, folder_id) | colorize_code_cell(doc_id, lang, mode)")
