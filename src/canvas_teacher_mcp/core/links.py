"""General HTML/Canvas link extractor — canvas_core foundation resource.

`extract_links(html) -> list[dict]`: EVERY link in an HTML string, classified,
WITHOUT truncation. Pure (no network), so it works on any HTML — a Canvas page /
assignment / quiz body, or anything else. Fetching Canvas content and looping a
module is a separate caller's job (keep this pure & reusable).

Why two layers (union) — so nothing is missed and the end of each URL is right:
  1. STRUCTURED (primary): parse the HTML and read URL-bearing attributes
     (href/src/srcset/data-*/poster/...). The closing quote IS the URL's end →
     boundary "exact". This is where ~all Canvas embeds/links live.
  2. TEXT backstop: scan raw text for bare scheme URLs (http/https/mailto/tel)
     not inside an attribute → boundary "heuristic".
Union + dedup by url (prefer the exact one). The whole URL is captured first;
any id is parsed AFTERWARDS from the complete URL — so the "truncate-the-id"
class of bug is structurally impossible.

Classification never says "unknown" for a normal URL: a plain web address is a
definite `web`/`webpage`. `other` is only for genuinely abnormal schemes.
`data:` URIs are inline CONTENT, not links → returned as a lightweight marker
(mime + approx length), never carrying the (possibly multi-MB) payload.

Policy home / registration: see CourseGlobalWorkflow. Intended consumers: content
tooling now; grade_engine attachment inventory later (separate verified change).
"""
import html as _html
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

# Attributes whose value is a URL.
_URL_ATTRS = {
    "href", "src", "data", "data-url", "data-api-endpoint", "data-download-url",
    "poster", "cite", "action", "formaction", "longdesc", "background",
}
_DATA_PREVIEW = 80  # chars of a data: URI to keep (never the full payload)


class _Collector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found = []  # (raw_url, attr, tag)

    def handle_starttag(self, tag, attrs):
        for name, val in attrs:
            if not val:
                continue
            n = name.lower()
            if n == "srcset":
                # "url1 1x, url2 2x" → take each url (first token of each part)
                for part in val.split(","):
                    part = part.strip()
                    if part:
                        self.found.append((part.split()[0], "srcset", tag))
            elif n in _URL_ATTRS:
                self.found.append((val, n, tag))

    handle_startendtag = handle_starttag


# Bare URLs written as plain text (not in an attribute). Scheme-anchored only.
_TEXT_URL = re.compile(r'(?:https?://|mailto:|tel:)[^\s"\'<>)\]}]+', re.I)
_CANVAS_HOST = re.compile(r'(?:^|\.)instructure\.com$', re.I)


def _classify(url):
    """Return classification dict for a complete URL (no truncation of url here)."""
    out = {"domain": None, "category": "web", "kind": "webpage",
           "id": None, "is_published": None}
    low = url.lower()

    if low.startswith("data:"):
        head = url[5:url.find(",")] if "," in url else url[5:]
        mime = head.split(";")[0]
        out.update({"category": "data", "kind": "data-uri", "mime": mime,
                    "approx_len": len(url)})
        return out
    if low.startswith("mailto:"):
        out.update({"category": "mail", "kind": "mailto",
                    "id": url[7:].split("?")[0] or None})
        return out
    if low.startswith("tel:"):
        out.update({"category": "tel", "kind": "tel", "id": url[4:] or None})
        return out

    sp = urlsplit(url)
    if not sp.scheme and not sp.netloc:
        out.update({"category": "relative",
                    "kind": "anchor" if url.startswith("#") else "relative"})
        return out

    host = (sp.netloc or "").lower()
    path = sp.path or ""
    out["domain"] = host

    if "docs.google.com" in host:
        out["category"] = "google"
        m = re.search(r"/(document|presentation|spreadsheets|forms)/d/(e/)?([A-Za-z0-9_\-]+)", url)
        if m:
            out["kind"] = {"document": "doc", "presentation": "slides",
                           "spreadsheets": "sheet", "forms": "form"}[m.group(1)]
            out["id"] = m.group(3)
            out["is_published"] = bool(m.group(2))
        else:
            out["kind"] = "google-other"
        return out
    if "drive.google.com" in host:
        out["category"] = "google"
        out["kind"] = "drive-file"
        m = re.search(r"/file/d/([A-Za-z0-9_\-]+)", url) or re.search(r"[?&]id=([A-Za-z0-9_\-]+)", url)
        if m:
            out["id"] = m.group(1)
        return out
    if "forms.gle" in host:
        out.update({"category": "google", "kind": "form"})
        return out
    if _CANVAS_HOST.search(host):
        out["category"] = "canvas"
        if "/files/" in path:
            out["kind"] = "canvas-file"
            m = re.search(r"/files/(\d+)", path)
            out["id"] = m.group(1) if m else None
        elif "/pages/" in path:
            out["kind"] = "canvas-page"
        elif "/assignments/" in path:
            out["kind"] = "canvas-assignment"
        elif "/quizzes/" in path:
            out["kind"] = "canvas-quiz"
        elif "/modules/" in path:
            out["kind"] = "canvas-module"
        else:
            out["kind"] = "canvas-other"
        return out
    if "youtube.com" in host or "youtu.be" in host:
        out.update({"category": "youtube", "kind": "video"})
        return out
    if "vimeo.com" in host:
        out.update({"category": "vimeo", "kind": "video"})
        return out
    if "linkedin.com" in host:
        out.update({"category": "linkedin", "kind": "webpage"})
        return out

    pl = path.lower()
    if pl.endswith(".pdf"):
        out["kind"] = "pdf"
    elif re.search(r"\.(png|jpe?g|gif|webp|svg|bmp)$", pl):
        out["kind"] = "image"
    return out


def extract_links(html_str):
    """Extract every link from an HTML string. Returns list[dict] (dedup by url).

    Each dict: url, domain, category, kind, id, is_published, attr, boundary
    (+ mime/approx_len for data: URIs). The receiver filters by any field.
    """
    html_str = html_str or ""
    raw = []  # (url, attr, boundary)

    # Layer 1 — structured (exact boundary = the attribute's closing quote).
    c = _Collector()
    try:
        c.feed(html_str)
    except Exception:
        pass
    for u, attr, _tag in c.found:
        raw.append((_html.unescape(u).strip(), attr, "exact"))

    # Layer 2 — text backstop (heuristic boundary).
    for m in _TEXT_URL.finditer(html_str):
        raw.append((_html.unescape(m.group(0)).strip(), "text", "heuristic"))

    by = {}
    for url, attr, boundary in raw:
        if not url:
            continue
        # data: URI → dedup + store only a short preview, never the payload.
        if url.lower().startswith("data:"):
            key = url[:_DATA_PREVIEW]
            disp = key + ("…(truncated)" if len(url) > _DATA_PREVIEW else "")
            if key in by:
                continue
            d = _classify(url)
            d.update({"url": disp, "attr": attr, "boundary": boundary})
            by[key] = d
            continue
        if url in by:
            if by[url]["boundary"] == "heuristic" and boundary == "exact":
                by[url]["attr"], by[url]["boundary"] = attr, boundary
            continue
        d = _classify(url)
        d.update({"url": url, "attr": attr, "boundary": boundary})
        by[url] = d
    return list(by.values())


if __name__ == "__main__":
    import json
    import sys
    src = open(sys.argv[1], encoding="utf-8").read() if len(sys.argv) > 1 else sys.stdin.read()
    for d in extract_links(src):
        print(json.dumps(d, ensure_ascii=False))
