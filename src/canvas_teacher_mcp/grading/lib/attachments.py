"""Attachment reader — the ONLY place in the engine that talks to PDFs / GDocs / images.

Public API:
    from grade_engine.lib.attachments import read, AttachmentReadError
    result = read(submission, canvas_token=..., download_dir=...)

3-phase contract (DO NOT SKIP):
    Phase 1 — Inventory: enumerate every readable item (body + each link/img/file).
    Phase 2 — TODO: dispatch each item to its reader; track per-item success/failure.
    Phase 3 — Count check: read_n must equal expected_n; otherwise raise.

The function NEVER returns a silent 0. If anything cannot be read due to engine fault,
it raises AttachmentReadError. The caller decides whether the failure is engine-side
(STOP + 🚨) or student-quality-side (item score 0 + comment).

Forbidden in graders / any other module:
    urllib.request.urlopen, requests.get, http.client,
    subprocess pdftotext / tesseract / ocrmac,
    gws drive|docs|slides export|get
The engine selftest greps these patterns and refuses to grade if any are found
outside this file.
"""
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.parse as _urlparse
import zipfile

from .html_strip import strip as html_strip


class AttachmentReadError(Exception):
    """Raised when phase-3 count check fails (engine-side fault).

    The caller MUST honor — do not score the student, flag for instructor.
    """

    def __init__(self, message, details):
        super().__init__(message)
        self.details = details  # dict with item-level diagnostics


# ---------------------------------------------------------------------------
# Magic-byte type detection (the ONLY authoritative type detector).
# URL/extension is hint only.
# ---------------------------------------------------------------------------
def _sniff(blob):
    if not blob:
        return "empty"
    head = blob[:8]
    if head.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(b"\x89PNG"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head.startswith(b"GIF8"):
        return "gif"
    if head.startswith(b"PK\x03\x04"):
        return "zip"  # docx/xlsx/pptx = Office Open XML zip
    # HTML
    lower = blob[:200].lower()
    if lower.startswith(b"<!doctype") or lower.startswith(b"<html") or b"<html" in lower:
        return "html"
    # Plain text — try utf-8 decode of first 200 bytes
    try:
        head_str = blob[:200].decode("utf-8")
        if all(ord(c) >= 9 and (ord(c) < 127 or ord(c) >= 160) for c in head_str):
            return "text"
    except Exception:  # noqa: BLE001
        pass
    return "unknown"


# ---------------------------------------------------------------------------
# HTTP — only used by THIS module (per the rule).
# ---------------------------------------------------------------------------
def _http_get_bytes(url, headers=None, timeout=30):
    headers = headers or {}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(), r.headers.get("Content-Type", "") or ""
    except Exception as e:  # noqa: BLE001
        return None, f"http_error:{e}"


# ---------------------------------------------------------------------------
# Phase 1 — Inventory
# ---------------------------------------------------------------------------
_RE_CANVAS_FILE_LINK = re.compile(
    r'<a[^>]*href="(?P<url>https?://[^"]*?/users/\d+/files/(?P<fid>\d+)[^"]*)"[^>]*>'
    r'(?P<name>[^<]+)</a>',
    re.I,
)
_RE_CANVAS_IMG = re.compile(
    r'<img[^>]*src="(?P<url>https?://[^"]*?/users/\d+/files/(?P<fid>\d+)[^"]*)"'
    r'[^>]*?(?:alt="(?P<alt>[^"]*)")?',
    re.I,
)
_RE_GDOC = re.compile(
    r'(?P<url>https?://docs\.google\.com/document/d/(?:e/)?(?P<id>[A-Za-z0-9_\-]{10,}))',
    re.I,
)
_RE_GSLIDES = re.compile(
    r'(?P<url>https?://docs\.google\.com/presentation/d/(?:e/)?(?P<id>[A-Za-z0-9_\-]{10,}))',
    re.I,
)
_RE_DRAWIO_INLINE = re.compile(
    r'(?P<url>https?://(?:viewer\.diagrams\.net|app\.diagrams\.net)/[^"\s<]*?#R(?P<encoded>%[A-Za-z0-9_%.]+))',
    re.I,
)
_RE_DRAWIO_LINK = re.compile(
    r'(?P<url>https?://(?:app\.diagrams\.net|viewer\.diagrams\.net|[^"\s<]*?\.drawio\.[a-z]+)/[^"\s<]*)',
    re.I,
)
_RE_EXTERNAL_PDF = re.compile(
    r'(?P<url>https?://[^"\s<]+?\.pdf(?:\?[^"\s<]*)?)',
    re.I,
)
_RE_EXTERNAL_IMG = re.compile(
    r'(?P<url>https?://[^"\s<]+?\.(?:png|jpe?g|gif|webp)(?:\?[^"\s<]*)?)',
    re.I,
)
_RE_IMGUR = re.compile(
    r'(?P<url>https?://(?:i\.)?imgur\.com/[^"\s<]+)',
    re.I,
)
_RE_IFRAME_SRC = re.compile(
    r'<iframe[^>]+src="(?P<url>[^"]+)"',
    re.I,
)


def _is_canvas_url(url):
    return ".instructure.com" in url


def inventory(submission):
    """Inventory a Canvas submission dict (body + attachments[]).
    Thin wrapper over inventory_content."""
    return inventory_content(submission.get("body") or "",
                             submission.get("attachments") or [])


def inventory_content(body, attachments=None):
    """Return list of items WITHOUT reading them. Each item has kind+source+meta.

    Decoupled from the submission shape: takes raw `body` (HTML string) and an
    `attachments` list ([{url, id, display_name}, ...]) directly — so any caller
    with raw content (a quiz answer's HTML + resolved attachment URLs) inventories
    the same way an assignment submission does."""
    body = body or ""
    items = []
    seen_urls = set()

    # 1. Body always counts as one item.
    items.append({"kind": "body", "source": "body", "meta": {"html": body}})

    # 2. Canvas-internal img embeds.
    for m in _RE_CANVAS_IMG.finditer(body):
        url = m.group("url").replace("&amp;", "&")
        if url in seen_urls:
            continue
        seen_urls.add(url)
        items.append(
            {
                "kind": "canvas_img",
                "source": url,
                "meta": {"fid": m.group("fid"), "alt": m.group("alt") or ""},
            }
        )

    # 3. Canvas-internal file links.
    for m in _RE_CANVAS_FILE_LINK.finditer(body):
        url = m.group("url").replace("&amp;", "&")
        if url in seen_urls:
            continue
        seen_urls.add(url)
        items.append(
            {
                "kind": "canvas_file",
                "source": url,
                "meta": {"fid": m.group("fid"), "name": (m.group("name") or "").strip()},
            }
        )

    # 3b. Catch-all: ANY /files/{id} link (COURSE-scoped, bare download, etc.) that the
    #     class-specific regex above missed. Principle — collect every file ref, let the
    #     magic-byte reader decide the type (don't trust the URL form). Fixes the
    #     course-scoped /files/{id} gap (Cristian A22: a jpg linked as /files/{id}).
    for m in re.finditer(r'(?:href|src)="([^"]*?/files/(\d+)[^"]*)"', body):
        url = m.group(1).replace("&amp;", "&")
        if url in seen_urls or "/api/v1/" in url:
            continue
        seen_urls.add(url)
        items.append({"kind": "canvas_file", "source": url,
                      "meta": {"fid": m.group(2), "name": "file", "catch_all": True}})

    # 4. Drawio inline (must be checked before generic gdoc/external regex).
    for m in _RE_DRAWIO_INLINE.finditer(body):
        url = m.group("url")
        if url in seen_urls:
            continue
        seen_urls.add(url)
        items.append(
            {
                "kind": "drawio_inline",
                "source": url,
                "meta": {"encoded": m.group("encoded")},
            }
        )

    # 5. Drawio link (non-inline).
    for m in _RE_DRAWIO_LINK.finditer(body):
        url = m.group("url")
        if url in seen_urls:
            continue
        if "#R" in url:
            continue  # already captured as inline
        seen_urls.add(url)
        items.append({"kind": "drawio_link", "source": url, "meta": {}})

    # 6. Google Docs.
    for m in _RE_GDOC.finditer(body):
        url = m.group("url")
        if url in seen_urls:
            continue
        seen_urls.add(url)
        is_published = "/d/e/" in url
        items.append({"kind": "gdoc", "source": url,
                      "meta": {"id": m.group("id"), "is_published": is_published}})

    # 7. Google Slides.
    for m in _RE_GSLIDES.finditer(body):
        url = m.group("url")
        if url in seen_urls:
            continue
        seen_urls.add(url)
        # Published Slides URL pattern: /d/e/2PACX-... (anonymous public view)
        # Auth Slides URL pattern: /d/{doc_id} (requires gws OAuth)
        is_published = "/d/e/" in url
        items.append({"kind": "gslides", "source": url,
                      "meta": {"id": m.group("id"), "is_published": is_published}})

    # 8. External PDF (non-Canvas).
    for m in _RE_EXTERNAL_PDF.finditer(body):
        url = m.group("url")
        if url in seen_urls or _is_canvas_url(url):
            continue
        seen_urls.add(url)
        items.append({"kind": "external_pdf", "source": url, "meta": {}})

    # 9. External image (imgur, etc.) — non-Canvas.
    for m in _RE_EXTERNAL_IMG.finditer(body):
        url = m.group("url")
        if url in seen_urls or _is_canvas_url(url):
            continue
        seen_urls.add(url)
        items.append({"kind": "external_image", "source": url, "meta": {}})
    for m in _RE_IMGUR.finditer(body):
        url = m.group("url")
        if url in seen_urls:
            continue
        seen_urls.add(url)
        items.append({"kind": "external_image", "source": url, "meta": {}})

    # 10. Canvas attachments[] array.
    for att in (attachments or []):
        url = att.get("url")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        items.append(
            {
                "kind": "canvas_file",
                "source": url,
                "meta": {
                    "fid": str(att.get("id", "x")),
                    "name": att.get("display_name", "attachment"),
                    "from_attachments_array": True,
                },
            }
        )

    # 11. iframe src — extract embedded URLs and classify into existing kinds.
    #     Canvas.md: "Always fetch <iframe src=...> content before grading."
    #     Unknown src → "iframe_unknown" (no reader registered → read() reports
    #     status=failed → surfaces to instructor in errors[]).
    for m in _RE_IFRAME_SRC.finditer(body):
        src = m.group("url").replace("&amp;", "&")
        if src in seen_urls:
            continue
        seen_urls.add(src)
        if "/users/" in src and "/files/" in src:
            fid_m = re.search(r"/files/(\d+)", src)
            items.append({
                "kind": "canvas_file",
                "source": src,
                "meta": {"fid": fid_m.group(1) if fid_m else "x",
                         "name": "iframe_embedded_file",
                         "from_iframe": True},
            })
        elif "docs.google.com/document" in src:
            id_m = re.search(r"/document/d/(?:e/)?([A-Za-z0-9_\-]{10,})", src)
            is_published = "/d/e/" in src
            items.append({
                "kind": "gdoc",
                "source": src,
                "meta": {"id": id_m.group(1) if id_m else "",
                         "is_published": is_published,
                         "from_iframe": True},
            })
        elif "docs.google.com/presentation" in src:
            id_m = re.search(r"/presentation/d/(?:e/)?([A-Za-z0-9_\-]{10,})", src)
            is_published = "/d/e/" in src
            items.append({
                "kind": "gslides",
                "source": src,
                "meta": {"id": id_m.group(1) if id_m else "",
                         "is_published": is_published,
                         "from_iframe": True},
            })
        elif src.lower().split("?", 1)[0].endswith(".pdf"):
            items.append({
                "kind": "external_pdf",
                "source": src,
                "meta": {"from_iframe": True},
            })
        elif re.search(r"\.(png|jpe?g|gif|webp)(?:\?|$)", src, re.I):
            items.append({
                "kind": "external_image",
                "source": src,
                "meta": {"from_iframe": True},
            })
        else:
            # Unknown iframe target — no reader. Surfaces as status=failed in read().
            items.append({
                "kind": "iframe_unknown",
                "source": src,
                "meta": {"from_iframe": True},
            })

    return items


# ---------------------------------------------------------------------------
# Phase 2 — Readers
# ---------------------------------------------------------------------------
def _safe_name(s, n=40):
    return re.sub(r"[^A-Za-z0-9_.\-]", "_", s or "x")[:n]


def _cache_path(download_dir, uid, fid_or_id, kind, label):
    base = f"{kind}_{uid}_{fid_or_id}_{_safe_name(label)}"
    return os.path.join(download_dir, base)


def _read_pdf_bytes_to_text(pdf_path):
    """pdftotext layout. Empty stdout → return None for caller to try OCR fallback."""
    try:
        r = subprocess.run(
            ["pdftotext", "-layout", pdf_path, "-"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if r.returncode != 0:
            return None
        return r.stdout if r.stdout.strip() else None
    except Exception:  # noqa: BLE001
        return None


def _pdf_extract_images(pdf_path, out_dir=None, max_images=12):
    """Extract a PDF's embedded images to disk. Returns [paths]; [] when there are none.

    DETECTION WAS NOT ENOUGH (2026-08-08). This used to be `_pdf_has_images`, which ran
    `pdfimages -list` and returned a bare True/False. The PDF item then carried
    `is_visual: True` and no path, so the drawing inside it never became a viewable
    artifact and never entered the view-manifest — the file looked, to a grader reading
    the manifest, exactly like a submission with no drawing at all. On <course>'s three
    flowchart labs the same student submitted a PDF each time and the chart had to be
    opened by hand all three times; trusting the manifest would have scored a correct,
    complete flowchart 0 out of 8, three times over, for 24 points.

    `.docx/.pptx` already extract their pictures and surface each as its own item
    (`_office_read` → `image_paths`); this makes a PDF behave the same way, and the
    caller's existing `image_paths` loop picks them up with no further change.

    `max_images` caps a pathological file (a scanned 40-page submission would otherwise
    produce 40 page rasters); the cap is reported by the caller rather than hidden.
    """
    out_dir = out_dir or os.path.dirname(pdf_path)
    prefix = os.path.join(out_dir, os.path.splitext(os.path.basename(pdf_path))[0] + "_img")
    try:
        r = subprocess.run(
            ["pdfimages", "-png", "-l", str(max_images), pdf_path, prefix],
            capture_output=True, text=True, timeout=120,
        )
        if r.returncode != 0:
            return []
    except Exception:  # noqa: BLE001
        return []
    try:
        d = os.path.dirname(prefix) or "."
        base = os.path.basename(prefix)
        return sorted(
            os.path.join(d, n) for n in os.listdir(d)
            if n.startswith(base) and n.lower().endswith(".png")
        )[:max_images]
    except Exception:  # noqa: BLE001
        return []


def _save_blob(blob, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(blob)


def _docx_text(path):
    """Extract text from a .docx (Office Open XML = zip containing word/document.xml).
    Returns text, or None if not a readable Word doc. stdlib only."""
    try:
        with zipfile.ZipFile(path) as z:
            if "word/document.xml" not in z.namelist():
                return None
            xml = z.read("word/document.xml").decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return None
    xml = re.sub(r"</w:p>", "\n", xml)          # paragraph breaks
    xml = re.sub(r"<w:tab[^>]*/>", " ", xml)
    runs = re.findall(r"<w:t[^>]*>([^<]*)</w:t>", xml)
    text = "".join(runs)
    for a, b in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                 ("&#39;", "'"), ("&quot;", '"')):
        text = text.replace(a, b)
    return text.strip() or None


def _office_read(path, download_dir, uid, fid):
    """DEEP-READ an Office Open XML file (docx / pptx / xlsx = a zip).

    Returns {"text": str, "images": [paths], "kind": "docx"|"pptx"|"xlsx"|"zip"}.
    Extracts BOTH the text AND every embedded picture to disk, so the AI grader can VIEW
    the screenshots that live INSIDE the document — the gap that silently dropped in-docx
    screenshots (Steven A22) and returned text-only.
    stdlib zipfile only; never raises (returns {} on a non-OOXML zip).

    MEDIA PATH (fixed 2026-07-28): Word/PowerPoint/Excel write pictures under
    `word/media/`, `ppt/media/`, `xl/media/` — but a docx EXPORTED FROM GOOGLE DOCS puts
    them at a bare `media/image1.png`, with no app prefix. The old anchored
    `(word|ppt|xl)/media/` match therefore returned ZERO images for every Google-Docs
    submission (real case: <course> A31 uid 119834 — 10 screenshots in `media/`, all missed,
    so the student read as "text only"). Match any `…/media/<file>` OR a top-level
    `media/<file>` instead: prefix-agnostic, so a new producer is covered without an edit.
    """
    try:
        z = zipfile.ZipFile(path)
        names = z.namelist()
    except Exception:  # noqa: BLE001
        return {}
    if "word/document.xml" in names:
        kind, text = "docx", (_docx_text(path) or "")
    elif any(n.startswith("ppt/slides/slide") for n in names):
        kind = "pptx"
        parts = []
        for n in sorted(n for n in names if re.match(r"ppt/slides/slide\d+\.xml$", n)):
            xml = z.read(n).decode("utf-8", "replace")
            parts.append(" ".join(re.findall(r"<a:t>([^<]*)</a:t>", xml)))
        text = "\n".join(p for p in parts if p.strip())
    elif "xl/workbook.xml" in names:
        kind = "xlsx"
        text = ""
        if "xl/sharedStrings.xml" in names:
            xml = z.read("xl/sharedStrings.xml").decode("utf-8", "replace")
            text = " ".join(re.findall(r"<t[^>]*>([^<]*)</t>", xml))
    else:
        return {}  # a zip, but not a recognizable Office file
    # embedded media (screenshots) → extract to cache so they can be VIEWED
    images = []
    for n in names:
        if re.search(r"(?:^|/)media/[^/]+$", n) and re.search(r"\.(png|jpe?g|gif)$", n, re.I):
            blob = z.read(n)
            if _sniff(blob) not in ("png", "jpeg", "gif"):
                continue
            ext = os.path.splitext(n)[1] or ".png"
            ip = _cache_path(download_dir, uid, f"{fid}_{os.path.basename(n)}", "docimg", "media") + ext
            _save_blob(blob, ip)
            images.append(ip)
    return {"text": text.strip(), "images": images, "kind": kind}


def _read_canvas_img(item, ctx):
    """Download Canvas-internal image → magic-byte → OCR."""
    url = item["source"]
    fid = item["meta"]["fid"]
    label = item["meta"].get("alt", "image") or "image"
    path = _cache_path(ctx["download_dir"], ctx["uid"], fid, "canvas_img", label)
    if not (os.path.exists(path) and os.path.getsize(path) > 0):
        blob, ct = _http_get_bytes(url)
        if blob is None:
            return {"status": "failed", "reason": f"download error: {ct}"}
        _save_blob(blob, path)
    with open(path, "rb") as f:
        blob = f.read()
    kind = _sniff(blob)
    if kind in ("png", "jpeg", "gif"):
        # Raw file downloaded → surface the PATH so the AI grader VIEWS the actual image (§0Z). NO OCR:
        # AI vision reads the image (text + diagrams, e.g. a revision-history screenshot or a Venn
        # diagram) far more accurately than OCR, at the same cost we'd pay anyway to grade it.
        return {
            "status": "ok",
            "text": "",
            "is_visual": True,
            "magic": kind,
            "path": path,
        }
    return {"status": "failed", "reason": f"unexpected magic: {kind}", "magic": kind}


def _convert_canvas_file_url(url):
    """Try the most-reliable raw-bytes URL form for a Canvas user file.

    Strategy: prefer /files/{id}/download?verifier=... over wrap=1.
    """
    candidates = []
    # If wrap=1 → swap to /download
    m = re.match(r"(https?://[^/]+)/users/(\d+)/files/(\d+)\?(.+)$", url)
    if m:
        host, uid, fid, qs = m.groups()
        # Pull verifier
        verifier_m = re.search(r"verifier=([^&]+)", qs)
        verifier = verifier_m.group(1) if verifier_m else None
        if verifier:
            candidates.append(f"{host}/users/{uid}/files/{fid}/download?verifier={verifier}")
        candidates.append(f"{host}/users/{uid}/files/{fid}?wrap=0&" + qs.replace("wrap=1&", "").replace("wrap=1", ""))
    candidates.append(url)
    # Unique, preserve order
    seen, out = set(), []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _read_canvas_file(item, ctx):
    """Canvas file link → try /download?verifier first → magic-byte → branch.

    On HTTP failure (HTML page returned, 401/403/404, or all forms failed) and
    when a browser_fetcher is registered, fall back to the project's
    Playwright/browser fetcher. The engine itself never imports a browser lib.
    """
    url = item["source"]
    fid = item["meta"]["fid"]
    name = item["meta"].get("name", "file")
    path = _cache_path(ctx["download_dir"], ctx["uid"], fid, "canvas_file", name)
    blob = None
    last_magic = None
    last_url = None
    if os.path.exists(path) and os.path.getsize(path) > 0:
        with open(path, "rb") as f:
            blob = f.read()
        last_magic = _sniff(blob)
        last_url = path
    if blob is None or last_magic == "html":
        for candidate in _convert_canvas_file_url(url):
            b, ct = _http_get_bytes(candidate)
            if b is None:
                continue
            magic = _sniff(b)
            last_magic = magic
            last_url = candidate
            if magic in ("pdf", "png", "jpeg", "gif", "text", "zip"):
                blob = b
                _save_blob(blob, path)
                break
    # Browser-fetcher fallback (project-injected; engine doesn't import it).
    if (blob is None or last_magic == "html") and ctx.get("browser_fetcher"):
        try:
            ok = ctx["browser_fetcher"](url, path)
        except Exception:  # noqa: BLE001
            ok = False
        if ok and os.path.exists(path) and os.path.getsize(path) > 0:
            with open(path, "rb") as f:
                blob = f.read()
            last_magic = _sniff(blob)
    if blob is None:
        return {"status": "failed", "reason": "could not download (HTTP forms + browser fetcher all failed)"}
    kind = _sniff(blob)
    if kind == "pdf":
        text = _read_pdf_bytes_to_text(path)
        # Pull the embedded pictures out so each becomes its own viewable item (the caller's
        # `image_paths` loop). A flowchart or diagram delivered inside a PDF is otherwise
        # invisible to the view-manifest — see `_pdf_extract_images`.
        imgs = _pdf_extract_images(path, os.path.dirname(path))
        if not text:
            return {
                "status": "ok",
                "text": "",
                "is_visual": True,
                "magic": "pdf",
                "path": path,
                "image_paths": imgs,
                "reason": "pdftotext returned no text — likely scanned/image PDF",
            }
        return {"status": "ok", "text": text, "is_visual": bool(imgs), "magic": "pdf",
                "path": path, "image_paths": imgs}
    if kind in ("png", "jpeg", "gif"):
        return {
            "status": "ok",
            "text": "",  # images carry no extracted text; the AI grader views them directly
            "is_visual": True,
            "magic": kind,
            "path": path,   # surface the path so an image FILE link is actually viewable
        }
    if kind == "text":
        try:
            return {"status": "ok", "text": blob.decode("utf-8", "replace"), "is_visual": False, "magic": "text"}
        except Exception:  # noqa: BLE001
            return {"status": "failed", "reason": "could not decode text"}
    if kind == "zip":
        office = _office_read(path, ctx["download_dir"], ctx["uid"], fid)
        if office:
            imgs = office.get("images") or []
            txt = office.get("text") or ""
            if not txt and not imgs:  # OOXML but nothing readable → surface, never silent-ok
                return {"status": "failed", "reason": f"{office['kind']} had no text and no images"}
            return {"status": "ok", "text": txt, "is_visual": bool(imgs),
                    "magic": office["kind"], "path": path, "image_paths": imgs}
        return {"status": "failed", "reason": "zip is not a readable Office file (docx/pptx/xlsx)"}
    if kind == "html":
        return {"status": "failed", "reason": "Canvas returned HTML viewer (wrap bug)"}
    return {"status": "failed", "reason": f"unknown magic: {kind}"}


_RE_JS_ESCAPE = re.compile(r'\\x([0-9A-Fa-f]{2})')


def _decode_js_escapes(s):
    """Decode JavaScript-style \\xNN escapes and common HTML entities used in
    Google Docs/Slides published HTML aria-labels and JS payloads."""
    if not s:
        return s
    s = _RE_JS_ESCAPE.sub(lambda m: chr(int(m.group(1), 16)), s)
    # Common entities inside JS-escaped payloads
    s = s.replace("&#xa;", "\n").replace("&#10;", "\n")
    s = s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    s = s.replace("&quot;", '"').replace("&#39;", "'").replace("&apos;", "'")
    return s


def _fetch_published_gdoc_or_slides(url_or_id, kind, ctx):
    """Fetch a published Google Doc or Slides /pub HTML (anonymous, no auth).

    kind: "document" or "presentation"
    url_or_id: either the published id (2PACX-...) or a URL containing /d/e/{id}/...
    Returns (html_str, path) or (None, reason).
    """
    # Extract id if a URL was passed
    m = re.search(r'/d/e/([A-Za-z0-9_\-]{10,})', url_or_id or "")
    pub_id = m.group(1) if m else url_or_id
    if not pub_id:
        return None, "no published id"
    pub_url = f"https://docs.google.com/{kind}/d/e/{pub_id}/pub"
    safe = _safe_name(pub_id, 60)
    cache_path = os.path.join(ctx["download_dir"], f"{kind}_pub_{ctx['uid']}_{safe}.html")
    if os.path.exists(cache_path) and os.path.getsize(cache_path) > 0:
        try:
            with open(cache_path, "r", errors="replace") as f:
                return f.read(), cache_path
        except Exception:  # noqa: BLE001
            pass
    blob, ct = _http_get_bytes(pub_url, headers={"User-Agent": "Mozilla/5.0"})
    if blob is None:
        return None, f"http_error: {ct}"
    try:
        html_str = blob.decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return None, "decode failed"
    try:
        _save_blob(blob, cache_path)
    except Exception:  # noqa: BLE001
        pass
    return html_str, cache_path


def _extract_published_slides_text(html_str):
    """Pull text from a published Slides /pub HTML.

    Strategy:
      1. Decode JS-escaped strings (the JSON-ish payload that DocsList ships).
      2. Collect every aria-label="..." value (slide text + image alt text).
      3. Fall back to html_strip(body) if aria-label yields nothing.
      4. Also append every external href= URL — students often paste a
         Colab/Drive link as a clickable anchor whose visible text gets
         line-wrapped (and thus broken across runs) but whose href= attribute
         holds the intact URL. Without this step, link-only slides return
         text without the URL and the grader cannot find the notebook.
    """
    if not html_str:
        return "", False
    decoded = _decode_js_escapes(html_str)
    parts = re.findall(r'aria-label="([^"]+)"', decoded)
    has_imgs = "<img" in decoded
    text = "\n".join(p.strip() for p in parts if p.strip())
    if not text:
        # Slides /pub sometimes embeds text in <text> SVG nodes or <span>
        spans = re.findall(r'<(?:text|span)[^>]*>([^<]+)</(?:text|span)>', decoded)
        text = "\n".join(s.strip() for s in spans if s.strip())
    if not text:
        text = html_strip(decoded)
    # Append href values (Slides anchor URLs) — student links live here when
    # the visible text wraps. Filter out Google chrome/static/font URLs.
    # Slides /pub JSON-escapes hrefs as `\/`; normalize before regex so the
    # student's wrapped Colab/Drive URL is matchable.
    normalized = decoded.replace("\\/", "/")
    _SKIP = ("gstatic.com", "fonts.googleapis", "fonts.gstatic",
             "chrome.google.com/webstore", "/static/",
             "schema.org", "google.com/intl", "support.google.com",
             "policies.google.com", "accounts.google.com")
    hrefs = re.findall(r'href="(https?://[^"]+)"', normalized)
    # Also catch URLs inside Google redirect wrappers (google.com/url?q=...)
    # and inside JSON-quoted values that didn't have href= but did appear as
    # bare URLs (rare; cheap to include).
    redirected = re.findall(r'https?://www\.google\.com/url\?q=(https?://[^"&\s]+)', normalized)
    hrefs.extend(redirected)
    bare = re.findall(r'(https?://colab\.research\.google\.com/drive/[\w-]{20,}[^\s"<>]*)', normalized)
    hrefs.extend(bare)
    hrefs = [h for h in hrefs if not any(s in h for s in _SKIP)]
    # de-dup, keep order
    seen = set(); uniq = []
    for h in hrefs:
        if h not in seen:
            seen.add(h); uniq.append(h)
    if uniq:
        text = (text + "\n" if text else "") + "\n".join(uniq)
    return text, has_imgs


def _read_gdoc(item, ctx):
    """gws text → if empty, html → strip + img count.

    Published Google Docs (/d/e/{pub_id}/...) cannot be exported via gws (no auth);
    fetch the /pub HTML directly and html_strip it.
    """
    doc_id = item["meta"]["id"]
    if item["meta"].get("is_published"):
        html_str, info = _fetch_published_gdoc_or_slides(
            item.get("source") or doc_id, "document", ctx
        )
        if html_str is None:
            return {"status": "failed", "reason": f"published gdoc fetch failed: {info}"}
        has_imgs = "<img" in html_str
        text = html_strip(html_str).strip()
        if text or has_imgs:
            return {
                "status": "ok",
                "text": text,
                "is_visual": has_imgs,
                "magic": "gdoc_pub",
            }
        return {"status": "failed", "reason": "published gdoc has no text or images"}
    txt_path = os.path.join(ctx["download_dir"], f"gdoc_{ctx['uid']}_{doc_id}.txt")
    html_path = os.path.join(ctx["download_dir"], f"gdoc_{ctx['uid']}_{doc_id}.html")
    text = None
    has_imgs = False
    # Text export
    if not os.path.exists(txt_path):
        try:
            r = subprocess.run(
                [
                    "gws",
                    "drive",
                    "files",
                    "export",
                    "--params",
                    json.dumps({"fileId": doc_id, "mimeType": "text/plain"}),
                ],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=ctx["download_dir"],
            )
            tmp = os.path.join(ctx["download_dir"], "download.txt")
            if r.returncode == 0 and os.path.exists(tmp):
                os.rename(tmp, txt_path)
        except Exception:  # noqa: BLE001
            pass
    if os.path.exists(txt_path):
        try:
            text = open(txt_path, "r", errors="replace").read().lstrip("﻿").strip()
        except Exception:  # noqa: BLE001
            text = None
    # HTML fallback (always try — needed for image detection and as text fallback)
    if not os.path.exists(html_path):
        try:
            r = subprocess.run(
                [
                    "gws",
                    "drive",
                    "files",
                    "export",
                    "--params",
                    json.dumps({"fileId": doc_id, "mimeType": "text/html"}),
                ],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=ctx["download_dir"],
            )
            tmp = os.path.join(ctx["download_dir"], "download.html")
            if r.returncode == 0 and os.path.exists(tmp):
                os.rename(tmp, html_path)
        except Exception:  # noqa: BLE001
            pass
    if os.path.exists(html_path):
        try:
            html_str = open(html_path, "r", errors="replace").read()
            has_imgs = "<img" in html_str
            if not text or len(text) < 30:
                stripped = html_strip(html_str)
                if stripped and len(stripped) > (len(text) if text else 0):
                    text = stripped
        except Exception:  # noqa: BLE001
            pass
    if text is not None and len(text) >= 1:
        return {
            "status": "ok",
            "text": text,
            "is_visual": has_imgs,
            "magic": "gdoc",
        }
    if has_imgs:
        return {
            "status": "ok",
            "text": "",
            "is_visual": True,
            "magic": "gdoc",
            "reason": "GDoc has images but no extractable text",
        }
    return {"status": "failed", "reason": "GDoc export returned empty (private or no content)"}


def _read_gslides(item, ctx):
    """Auth Slides: gws slides → per-slide text concat.
    Published Slides (/d/e/{pub_id}/pub or /pubembed): fetch /pub HTML directly.
    """
    pres_id = item["meta"]["id"]
    if item["meta"].get("is_published"):
        html_str, info = _fetch_published_gdoc_or_slides(
            item.get("source") or pres_id, "presentation", ctx
        )
        if html_str is None:
            return {"status": "failed", "reason": f"published slides fetch failed: {info}"}
        text, has_imgs = _extract_published_slides_text(html_str)
        if text or has_imgs:
            return {
                "status": "ok",
                "text": text,
                "is_visual": True,
                "magic": "gslides_pub",
            }
        return {"status": "failed", "reason": "published slides yielded no text"}
    try:
        r = subprocess.run(
            [
                "gws",
                "slides",
                "presentations",
                "get",
                "--params",
                json.dumps({"presentationId": pres_id}),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if r.returncode != 0:
            return {"status": "failed", "reason": "gws slides get failed"}
        pres = json.loads(r.stdout)
    except Exception as e:  # noqa: BLE001
        return {"status": "failed", "reason": f"gws error: {e}"}
    parts = []
    for slide in pres.get("slides") or []:
        for el in slide.get("pageElements") or []:
            shape = el.get("shape") or {}
            tx = (shape.get("text") or {}).get("textElements") or []
            for t in tx:
                tr = t.get("textRun")
                if tr:
                    parts.append(tr.get("content", ""))
    text = "".join(parts).strip()
    return {
        "status": "ok",
        "text": text,
        "is_visual": True,
        "magic": "gslides",
    }


def _read_drawio_inline(item, ctx):
    """Decode #R URL fragment to mxfile XML and extract cell text."""
    encoded = item["meta"].get("encoded", "")
    try:
        # First-pass: percent-decode
        decoded = _urlparse.unquote(encoded)
        # cell texts are in <mxCell value="..."> attributes
        texts = re.findall(r'value="([^"]*)"', decoded)
        text = " ".join(t for t in texts if t.strip())
    except Exception:  # noqa: BLE001
        text = ""
    return {
        "status": "ok",
        "text": text,
        "is_visual": True,
        "magic": "drawio_inline",
    }


def _read_drawio_link(item, ctx):
    return {"status": "ok", "text": "", "is_visual": True, "magic": "drawio_link"}


def _read_external_image(item, ctx):
    url = item["source"]
    name = url.rsplit("/", 1)[-1].split("?", 1)[0] or "ext_image"
    path = _cache_path(ctx["download_dir"], ctx["uid"], "ext", "external_image", name)
    if not (os.path.exists(path) and os.path.getsize(path) > 0):
        blob, ct = _http_get_bytes(url)
        if blob is None:
            return {"status": "failed", "reason": f"download error: {ct}"}
        _save_blob(blob, path)
    with open(path, "rb") as f:
        blob = f.read()
    kind = _sniff(blob)
    if kind in ("png", "jpeg", "gif"):
        return {
            "status": "ok",
            "text": "",            # images carry no text; the AI grader VIEWS the path
            "is_visual": True,
            "magic": kind,
            "path": path,          # surface the path so it is actually viewable
        }
    return {"status": "failed", "reason": f"unexpected magic for external image: {kind}"}


def _read_external_pdf(item, ctx):
    url = item["source"]
    name = url.rsplit("/", 1)[-1].split("?", 1)[0] or "ext_pdf"
    path = _cache_path(ctx["download_dir"], ctx["uid"], "ext", "external_pdf", name)
    if not (os.path.exists(path) and os.path.getsize(path) > 0):
        blob, ct = _http_get_bytes(url)
        if blob is None:
            return {"status": "failed", "reason": f"download error: {ct}"}
        _save_blob(blob, path)
    with open(path, "rb") as f:
        blob = f.read()
    kind = _sniff(blob)
    if kind != "pdf":
        return {"status": "failed", "reason": f"unexpected magic for external pdf: {kind}"}
    text = _read_pdf_bytes_to_text(path)
    has_images = _pdf_has_images(path)
    if not text:
        return {
            "status": "ok",
            "text": "",
            "is_visual": True,
            "magic": "pdf",
            "reason": "pdftotext empty — likely scanned",
        }
    return {"status": "ok", "text": text, "is_visual": has_images, "magic": "pdf"}


def _read_body(item, ctx):
    text = html_strip(item["meta"]["html"])
    return {"status": "ok", "text": text, "is_visual": False, "magic": "body"}


def _read_iframe_unknown(item, ctx):
    """Stub reader: iframe target type unrecognized.
    Returns status=failed with a 'no extractable' reason so allow_quality_failures
    counts it as read (engine doesn't STOP) but it surfaces in errors[] and
    quality_failures[] for instructor review."""
    src = item.get("source", "")
    return {
        "status": "failed",
        "text": "",
        "is_visual": False,
        "reason": f"no extractable content — iframe target type not recognized: {src[:120]}",
        "magic": "iframe_unknown",
    }


_READERS = {
    "body": _read_body,
    "canvas_img": _read_canvas_img,
    "canvas_file": _read_canvas_file,
    "gdoc": _read_gdoc,
    "gslides": _read_gslides,
    "drawio_inline": _read_drawio_inline,
    "drawio_link": _read_drawio_link,
    "iframe_unknown": _read_iframe_unknown,
    "external_image": _read_external_image,
    "external_pdf": _read_external_pdf,
}


# ---------------------------------------------------------------------------
# Colab / Drive NOTEBOOK fetch (cells + PINNED revisions)
# Centralized here per the attachments contract — graders NEVER call gws/HTTP.
# Returns the parsed ipynb cells + each keepForever-pinned revision's content, so
# an NB grader can deep-read cells (`nb_inspect.deep_read`) and analyze the revision
# progression (`nb_inspect.revision_progression`). GRADING.md Part C §1/§3/§4.
# ---------------------------------------------------------------------------
_COLAB_RE = re.compile(r'colab\.research\.google\.com/drive/([\w-]{20,})')
# A Drive FILE link (NOT a Colab notebook): drive.google.com/file/d/… , open?id= , uc?id=. Submitting
# this instead of a Colab share link = WRONG format → Link 0 + resubmit guidance (see _read_colab_notebook).
_DRIVE_FILE_RE = re.compile(r'drive\.google\.com/(?:file/d/|open\?id=|uc\?id=)([\w-]{20,})')


def _gws_json(args):
    try:
        r = subprocess.run(["gws"] + args, capture_output=True, text=True, timeout=60)
        i = r.stdout.find("{")
        return json.loads(r.stdout[i:]) if i >= 0 else None
    except Exception:  # noqa: BLE001
        return None


def _gws_media_nb(file_id, out_path, revision_id=None):
    """Download a Drive file (or a specific revision) as media → parse ipynb. None on failure.

    gws (0.18.x) REFUSES `-o` to any path OUTSIDE its working directory, so run gws IN the target
    dir (`cwd=`) with a RELATIVE basename — the output is then "inside the current directory" and
    lands regardless of where `download_dir` (e.g. /tmp/…) is vs. the caller's own cwd."""
    out_dir = os.path.dirname(out_path) or "."
    base = os.path.basename(out_path)
    os.makedirs(out_dir, exist_ok=True)
    if revision_id:
        args = ["drive", "revisions", "get", "--params",
                json.dumps({"fileId": file_id, "revisionId": revision_id, "alt": "media"}), "-o", base]
    else:
        args = ["drive", "files", "get", "--params",
                json.dumps({"fileId": file_id, "alt": "media"}), "-o", base]
    try:
        r = subprocess.run(["gws"] + args, capture_output=True, text=True, timeout=60, cwd=out_dir)
        # OUTPUT-based, not mimeType-based: gws saves the media to `-o` for native-Colab
        # (application/vnd.google.colaboratory) and x-ipynb+json files, but for a plain
        # `application/json` upload it DUMPS the raw ipynb to STDOUT instead of the file.
        # Read the file if it landed; else recover the notebook JSON from stdout; else None
        # (→ the NB grader raises a visible STOP, never a silent 0). Divyam Ch5 json, 2026-07-22.
        if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            with open(out_path) as f:
                nb = json.load(f)
        else:
            i = r.stdout.find('{"cells"')
            if i < 0:
                i = r.stdout.find("{")
            nb = json.loads(r.stdout[i:]) if i >= 0 else None
        return nb if isinstance(nb, dict) and "cells" in nb else None
    except Exception:  # noqa: BLE001
        return None


# NB fetch cache — the Drive/gws media pull (ipynb + each pinned revision) is the NB gather
# bottleneck (~10s/student), and it re-ran on EVERY grade of the same submission (e.g. a rubric
# fix re-grade minutes later = a full re-fetch of the whole class). Cache the parsed result by
# Drive file id so a re-grade reuses it. TTL-bounded so a genuine resubmission (same fid, new
# content, next day) still re-fetches; `NB_CACHE_BUST=1` forces a fresh pull.
_NB_CACHE_TTL = 6 * 3600   # seconds a fetched notebook is reused (covers same-session re-grades)


def _nb_cache_dir():
    d = os.path.join(os.path.expanduser("~"), ".cache", "grade_engine", "nb")
    os.makedirs(d, exist_ok=True)
    return d


def _read_colab_notebook(body, ctx):
    """If the submission body has a Colab/Drive notebook link, fetch the latest ipynb
    cells + every PINNED (keepForever) revision's content. Returns
    {drive_id, cells, revisions:[{modifiedTime, keepForever, nb}]} or None (no link /
    inaccessible). Auto-save revisions are excluded (only keepForever pins are fetched).

    Cached by Drive file id (TTL {_NB_CACHE_TTL}s) so a re-grade of the same submission — the
    common case when only the rubric changed — reuses the fetch instead of re-pulling from gws."""
    m = _COLAB_RE.search(body or "")
    if not m:
        # Not a Colab notebook link. If they instead submitted a Drive FILE link (file/d/, open?id=,
        # uc?id=) → WRONG format: a static file, not a live shared Colab, so execution / revisions /
        # Editor can't be verified. Flag it → grader gives Link 0 + a resubmit-as-Colab guidance comment.
        if _DRIVE_FILE_RE.search(body or ""):
            return {"drive_id": None, "cells": [], "revisions": [], "accessible": False,
                    "editor": False, "wrong_format": True}
        return None
    fid = m.group(1)
    dd, uid = ctx["download_dir"], ctx["uid"]
    # cache hit → reuse the parsed fetch (skips every gws media/revision call for this student)
    cache_f = os.path.join(_nb_cache_dir(), f"{fid}.json")
    if not os.environ.get("NB_CACHE_BUST") and os.path.exists(cache_f):
        try:
            if (time.time() - os.path.getmtime(cache_f)) <= _NB_CACHE_TTL:
                with open(cache_f) as f:
                    return json.load(f)
        except Exception:  # noqa: BLE001 — a bad cache entry just falls through to a fresh fetch
            pass
    nb = _gws_media_nb(fid, os.path.join(dd, f"nb_{uid}_{fid}.ipynb"))
    if nb is None:
        return {"drive_id": fid, "cells": [], "revisions": [], "accessible": False, "editor": False}
    # Editor vs Viewer share: `capabilities.canEdit` is true only when the link grants EDIT (shared as
    # Editor). The lab REQUIRES Editor so the revision history is verifiable; Viewer → the Link item = 0.
    cap = _gws_json(["drive", "files", "get", "--params",
                     json.dumps({"fileId": fid, "fields": "capabilities/canEdit"})])
    editor = bool(((cap or {}).get("capabilities") or {}).get("canEdit"))
    revs = _gws_json(["drive", "revisions", "list", "--params",
                      json.dumps({"fileId": fid, "fields": "revisions(id,modifiedTime,keepForever)"})])
    pinned = []
    all_revs = []   # EVERY revision's timestamp (no content fetch — cheap). The time signal
                    # MUST come from here, not cell executionInfo: a final "Run all cells"
                    # overwrites every cell's last-run timestamp to one instant (collapsing
                    # active_min to ~0), but Drive revisions are append-only save records that
                    # a Run-all cannot touch — they preserve the true development span.
    for r in sorted((revs or {}).get("revisions", []), key=lambda x: x.get("modifiedTime", "")):
        all_revs.append({"modifiedTime": r.get("modifiedTime"), "keepForever": bool(r.get("keepForever"))})
        if not r.get("keepForever"):
            continue
        rnb = _gws_media_nb(fid, os.path.join(dd, f"rev_{uid}_{fid}_{r['id']}.ipynb"), revision_id=r["id"])
        pinned.append({"modifiedTime": r.get("modifiedTime"), "keepForever": True,
                       "nb": rnb if rnb is not None else {"cells": []}})
    result = {"drive_id": fid, "cells": nb.get("cells", []), "revisions": pinned,
              "all_revisions": all_revs, "accessible": True, "editor": editor}
    try:                                   # cache the successful fetch only (never cache a failure)
        with open(os.path.join(_nb_cache_dir(), f"{fid}.json"), "w") as f:
            json.dump(result, f)
    except Exception:  # noqa: BLE001 — caching is best-effort, never block grading
        pass
    return result


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------
def read(submission, canvas_token=None, download_dir=None, allow_quality_failures=True,
         browser_fetcher=None, github_org=None, make_view_copies=True, view_max_side=1400,
         fetch_visual=True):
    """Read a Canvas submission dict (body + attachments[]). Thin wrapper over
    `read_content` — decouples the reader from the submission shape so a caller
    holding raw content (e.g. a quiz answer's HTML + resolved attachment URLs)
    calls `read_content` directly instead of faking a `{"body": ...}` submission.

    fetch_visual=False → do NOT download body images (canvas_img / external / imgur); they are
    inventoried but not fetched. Use for FILE-FIRST graders (NB): the notebook + actual revision
    pins are the grade, a submitted revision-history screenshot is formality only (grade-nb §B)."""
    user = submission.get("user") or {}
    return read_content(
        submission.get("body") or "", submission.get("attachments") or [],
        download_dir=download_dir, uid=user.get("id", "x"),
        canvas_token=canvas_token, allow_quality_failures=allow_quality_failures,
        browser_fetcher=browser_fetcher, github_org=github_org,
        make_view_copies=make_view_copies, view_max_side=view_max_side, fetch_visual=fetch_visual)


def read_content(body, attachments=None, download_dir=None, uid="x",
                 canvas_token=None, allow_quality_failures=True, browser_fetcher=None,
                 github_org=None, make_view_copies=True, view_max_side=1400, fetch_visual=True):
    """Read every readable item in raw content (HTML `body` + `attachments` list).
    Honors the 3-phase contract. Decoupled from any submission shape.

    Parameters
    ----------
    body : str
        HTML content to scan for embeds / file links / iframes.
    attachments : list[dict] | None
        Uploaded files as [{url, id, display_name}, ...] (assignment
        submission["attachments"], or quiz file_upload ids resolved to URLs).
    download_dir : str
        Directory for cached downloads. Required. Caller controls cleanup.
    uid : any
        Used only for cache filenames.
    allow_quality_failures : bool
        If True (default), a student-side quality failure (private GDoc,
        encrypted PDF, etc.) counts as 'read' (empty text) so the engine does
        NOT STOP. If False, any item failure raises AttachmentReadError.

    Returns
    -------
    dict: body_text, items, expected_n, read_n, all_text, has_visual, errors,
    quality_failures, status. Raises AttachmentReadError when read_n < expected_n.
    """
    if not download_dir:
        raise ValueError("download_dir is required")
    os.makedirs(download_dir, exist_ok=True)

    ctx = {
        "uid": uid,
        "download_dir": download_dir,
        "canvas_token": canvas_token,
        "browser_fetcher": browser_fetcher,
    }

    # Phase 1
    items = inventory_content(body, attachments)
    expected_n = len(items)

    # Phase 2
    results = []
    body_text = ""
    all_text_parts = []
    has_visual = False
    errors = []
    read_n = 0
    quality_failures = []
    _VISUAL_KINDS = {"canvas_img", "external_image", "imgur"}
    for it in items:
        kind = it["kind"]
        # FILE-FIRST graders (NB, fetch_visual=False): do NOT download body images. The notebook cells
        # + the ACTUAL revision pins are the grade; a revision-history SCREENSHOT is formality only
        # (grade-nb §B). Downloading them all (98 for a 17-student lab) was the gather bottleneck.
        # They stay INVENTORIED (so we know one exists); a diagram-type ANSWER image, when a lab
        # actually needs one, is fetched on demand (fetch_visual=True).
        if not fetch_visual and kind in _VISUAL_KINDS:
            results.append({**it, "status": "skipped", "reason": "visual not fetched (file-first)",
                            "text": "", "is_visual": True, "not_fetched": True})
            read_n += 1          # present + counted (not a STOP) — just not downloaded
            has_visual = True
            continue
        reader = _READERS.get(kind)
        if reader is None:
            results.append({**it, "status": "failed", "reason": f"no reader for {kind}", "text": "", "is_visual": False})
            errors.append(f"{kind}:{it.get('source','?')[:50]} → no reader")
            continue
        try:
            out = reader(it, ctx)
        except Exception as e:  # noqa: BLE001
            results.append({**it, "status": "failed", "reason": f"reader exception: {e}", "text": "", "is_visual": False})
            errors.append(f"{kind}:{it.get('source','?')[:50]} → exception: {e}")
            continue
        merged = {**it, **out}
        results.append(merged)
        if out.get("status") == "ok":
            read_n += 1
            txt = out.get("text", "") or ""
            if kind == "body":
                body_text = txt
            if txt:
                all_text_parts.append(txt)
            if out.get("is_visual"):
                has_visual = True
            # Deep-read: surface each embedded picture as its OWN viewable image item
            # (magic png/jpeg + path) so read_many/view_copy and the grader see the
            # screenshots and drawings that lived INSIDE the document — not just the
            # extracted text. Feeds `.docx/.pptx/.xlsx` and, since 2026-08-08, `.pdf`.
            for ip in (out.get("image_paths") or []):
                ext = os.path.splitext(ip)[1].lower()
                magic = "jpeg" if ext in (".jpg", ".jpeg") else ("gif" if ext == ".gif" else "png")
                _from = merged.get("magic")
                results.append({"kind": "pdf_image" if _from == "pdf" else "office_image",
                                "source": ip,
                                "status": "ok", "text": "", "is_visual": True,
                                "magic": magic, "path": ip,
                                "meta": {"from_document": _from}})
                has_visual = True
        else:
            reason = out.get("reason", "")
            quality_keywords = (
                "private", "no extractable", "scanned", "image PDF",
                "could not decode", "viewer (wrap bug)",
                "not a readable",   # zip-not-office etc. — unreadable file → that item 0, no STOP
            )
            is_quality = any(k.lower() in reason.lower() for k in quality_keywords)
            if allow_quality_failures and is_quality:
                read_n += 1  # count toward expected_n; grader will give 0 for the item
                quality_failures.append({**merged})
            errors.append(f"{kind}:{it.get('source','?')[:50]} → {reason}")

    all_text = "\n\n".join(all_text_parts)
    status = "ok" if read_n >= expected_n else "stop"

    # DEFAULT downscaled VIEW for every image item — the general grading download route.
    # The AI reads item["view_path"] (Lanczos ≤ view_max_side px, cheap vision; §0Z holds —
    # same image, just smaller, always a .png) instead of the full-res original at
    # item["path"], which is kept untouched for the rare "need finer detail" case.
    # (jul-7-2026 view_copy, now wired into read() so ANY grader gets it by default —
    # previously only read_many(make_view_copies=True) produced it, and graders call read().)
    if make_view_copies:
        for _it in results:
            if (_it.get("status") == "ok" and _it.get("path")
                    and _it.get("magic") in ("png", "jpeg", "gif")):
                _it["view_path"] = view_copy(_it["path"], max_side=view_max_side)

    result = {
        "body_text": body_text,
        "items": results,
        "expected_n": expected_n,
        "read_n": read_n,
        "all_text": all_text,
        # RAW input HTML preserved (NOT tag-stripped) — Stage B reads this for
        # paste/format artifacts (inline code-token color-font spans = pasted from a
        # rendered-markdown source; base rate <1% on direct Canvas typing). Same field
        # for body (assignment) and submission_data (quiz) callers, so no source-shape gap.
        "raw": body or "",
        "has_visual": has_visual,
        "errors": errors,
        "quality_failures": quality_failures,
        "status": status,
    }

    # repo_link: the student's GitHub repo {org}/{repo}, extracted ONCE here from
    # body+all_text so repo_resolve + every caller reuse it instead of re-parsing
    # (jun-24-2026.md item 1). None when no github_org given or no link present.
    result["repo_link"] = None
    if github_org:
        try:
            from .repo_resolve import extract_repo_from_body
        except ImportError:
            from repo_resolve import extract_repo_from_body
        # use RAW body (href attrs hold the URL; tag-stripped body_text loses them) + all_text
        result["repo_link"] = extract_repo_from_body(
            "\n".join([body or "", all_text]), github_org)

    # NB / Colab: fetch the notebook cells + pinned revisions (None if no Colab link).
    # Centralized here (graders never call gws). Best-effort — never blocks the gate.
    try:
        result["notebook"] = _read_colab_notebook(body, ctx)
    except Exception:  # noqa: BLE001
        result["notebook"] = None

    # Write manifest.json so the grader (and instructor) can audit the
    # count check externally — the gate is mechanical and visible.
    try:
        manifest_path = os.path.join(download_dir, f"manifest_{uid}.json")
        manifest = {
            "uid": uid,
            "status": status,
            "expected_n": expected_n,
            "read_n": read_n,
            "items": [
                {
                    "kind": r.get("kind"),
                    "source": r.get("source"),
                    "status": r.get("status"),
                    "magic": r.get("magic"),
                    "reason": r.get("reason"),
                }
                for r in results
            ],
            "errors": errors,
        }
        with open(manifest_path, "w") as mf:
            json.dump(manifest, mf, indent=2, default=str)
    except Exception:  # noqa: BLE001
        pass  # manifest write failure must not block grading decisions

    if status == "stop":
        raise AttachmentReadError(
            f"read_n={read_n} < expected_n={expected_n} — engine fault, do not score this student",
            details=result,
        )
    return result


# ---------------------------------------------------------------------------
# Batch + view-copy helpers (download speed + cheap AI viewing)
# ---------------------------------------------------------------------------
# Diagnosis (2026-07-06, <course> LM1/CA1): a 42-submission screenshot batch took
# >10 min NOT because of image SIZE or bandwidth (~tens of MB total) and NOT
# because of OCR (`_read_canvas_img` does NO OCR — it downloads + magic-sniffs
# only). The cost was many SEQUENTIAL HTTP round-trips to Canvas (one read() per
# submission). Fix = overlap the waits (read_many) + shrink what the AI views
# (view_copy). Images are NEVER OCR'd; the AI vision-reads them (§0Z).

def view_copy(path, max_side=1400, out_path=None):
    """Write a DOWNSCALED copy of an image for cheap AI viewing; keep the original.

    Vision cost scales with pixel AREA, so a screenshot shrunk to a longest side of
    `max_side` px (UI text stays legible) costs a fraction to VIEW while §0Z still
    holds — the AI sees the SAME image, just smaller. Downscale = Lanczos resampling
    (sharpest text) via Pillow; `sips -Z` fallback (macOS built-in). ALWAYS returns a
    `.png` view path (downscaled when the longest side exceeds `max_side`, otherwise a
    same-size PNG re-encode) so extension-keyed viewers can open it; the ORIGINAL at
    `path` is never touched (used only when finer detail is needed). NEVER raises — a
    missing tool falls back to the original path so it can't block grading.
    """
    if not path or not os.path.exists(path):
        return path
    dst = out_path or (path + ".view.png")
    try:                                    # Pillow (Lanczos) — best text legibility
        from PIL import Image               # lazy import: engine has NO hard Pillow dep
        _EXT = {"JPEG": ".jpg", "PNG": ".png", "GIF": ".gif"}
        with Image.open(path) as im:
            fmt = (im.format or "PNG").upper()
            if max(im.size) > max_side:     # big → downscale (Lanczos) and emit PNG
                d = out_path or (path + ".view.png")
                small = im.convert("RGB")
                small.thumbnail((max_side, max_side), Image.LANCZOS)
                small.save(d, "PNG")
            else:                           # already small → nothing to downscale.
                # Copy the ORIGINAL BYTES to an extensioned name — never re-encode (a
                # re-save can BLOAT a well-compressed small file); just give it a proper
                # extension so extension-keyed viewers can open it. Pixel area (= vision
                # cost) is unchanged, so there is nothing to gain from re-encoding.
                import shutil
                ext = _EXT.get(fmt, ".png")
                d = out_path or (path + ".view" + ext)
                shutil.copy2(path, d)
        return d if (os.path.exists(d) and os.path.getsize(d) > 0) else path
    except Exception:                       # noqa: BLE001
        pass
    try:                                    # sips fallback (not in the OCR-forbidden set)
        subprocess.run(["sips", "-Z", str(max_side), path, "-o", dst],
                       capture_output=True, timeout=30)
        return dst if (os.path.exists(dst) and os.path.getsize(dst) > 0) else path
    except Exception:                       # noqa: BLE001
        return path


def read_many(submissions, canvas_token=None, download_dir=None, max_workers=8,
              allow_quality_failures=True, browser_fetcher=None, github_org=None,
              make_view_copies=True, view_max_side=1400):
    """CONCURRENT `read()` over many submissions — PURE PARALLELISM, nothing else.

    The download is latency-bound (one sequential HTTP GET per submission); a thread
    pool overlaps the waits (read() is I/O-bound — the GIL releases during the network
    fetch), turning a ~10-min sequential crawl into ~1 min. Order is PRESERVED
    (result[i] ⇄ submissions[i]). A submission whose read() raises does NOT abort the
    batch: an AttachmentReadError lands as {"status": "stop", ...} (caller treats as 🚨
    STOP, never a 0) and any other error as {"status": "error", ...}.

    This wrapper carries ZERO per-image logic. Downscaled views are produced by the
    per-item layer (`read()` → `read_content`); `make_view_copies` / `view_max_side` are
    simply FORWARDED to `read()`. So every image item still carries `item["view_path"]`
    (Lanczos ≤ view_max_side px; the original stays at item["path"]) and the AI reads
    view_path — but the downscale decision lives in exactly ONE place (read_content),
    not here. (Layering fix 2026-07-07: the old post-read view_copy loop is removed.)
    """
    from concurrent.futures import ThreadPoolExecutor
    subs = list(submissions)
    results = [None] * len(subs)

    def _one(idx, sub):
        try:
            res = read(sub, canvas_token=canvas_token, download_dir=download_dir,
                       allow_quality_failures=allow_quality_failures,
                       browser_fetcher=browser_fetcher, github_org=github_org,
                       make_view_copies=make_view_copies, view_max_side=view_max_side)
        except AttachmentReadError as e:
            return idx, {"status": "stop", "error": str(e), "details": e.details}
        except Exception as e:              # noqa: BLE001
            return idx, {"status": "error", "error": repr(e)}
        return idx, res

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for idx, res in ex.map(lambda p: _one(*p), list(enumerate(subs))):
            results[idx] = res
    return results
