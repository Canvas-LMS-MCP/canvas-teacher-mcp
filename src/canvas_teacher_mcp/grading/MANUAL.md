# grade_engine — MANUAL

Reference for the engine's library surface. The RULES that govern its use are policy and live in
`CourseGlobalWorkflow/` — `GRADING.md`, `GradingEngine/*`. This file is the shapes and arguments.

## `lib/attachments.read(submission, download_dir=..., github_org=None)`

Carried here 2026-08-10 from `GradingEngine/Attachments.md`, which keeps the rule.

```python
{
  "body_text":  str,
  "items":      [Item, ...],
  "expected_n": int,
  "read_n":     int,
  "all_text":   str,
  "has_visual": bool,
  "errors":     [str, ...],
  "status":     "ok" | "stop",
  "notebook":   {…} | None,   # Colab/Drive submissions
  "repo_link":  str | None,   # "{org}/{repo}" when github_org is passed
}
```

Raises `AttachmentReadError` when `read_n < expected_n`.

**`notebook`** — present when the body carries a Colab/Drive link. `read()` does all the gws
fetching, so graders never call gws themselves.

```python
{ "drive_id": str, "accessible": bool, "editor": bool, "wrong_format": bool,
  "cells":     [ipynb cell, ...],                     # latest revision
  "revisions": [{"modifiedTime": iso, "keepForever": True, "nb": {...}}, ...] }
```

`cells` feeds `nb_inspect.deep_read` / `resolve_tasks`; `revisions` (pinned only, oldest→newest)
feeds `revision_progression`.

**`repo_link`** — scans the RAW body (so a link living only in an `<a href>` still counts) plus
`all_text`, returns the first `github.com/{org}/{repo}`, trimming a trailing path segment or
`.git`. `None` when `github_org` was not passed or no link exists.

**Views.** Every image item carries `item["view_path"]` — Lanczos-downscaled to ≤1400 px, always a
proper-extension file. Read that; the full-res original stays at `item["path"]` for when you need
finer detail. `make_view_copies=False` turns it off.

## `lib/attachments.read_many(submissions, canvas_token=, download_dir=, max_workers=8, ...)`

Concurrent `read()`, order preserved. The download is latency-bound (one HTTP GET per submission,
no OCR), so a thread pool turns a ~10-minute crawl into ~1 minute. A submission that raises does
not abort the batch: `AttachmentReadError` ⇒ `{"status": "stop", …}`, anything else ⇒
`{"status": "error", …}`.

`view_copy(path, max_side=1400)` is the same downscale, standalone. Never raises — Pillow, then
`sips -Z`, then the original.

Canvas serves the ORIGINAL file for a submission verifier URL; there is no server-side resize
parameter. Downscaling is a viewing optimization, never a download one.

## Office files

`.docx/.pptx/.xlsx` are OOXML zips. `_office_read` extracts text (`word/document.xml`,
`ppt/slides/slideN.xml`, `xl/sharedStrings.xml`) AND every embedded image (`word|ppt|xl/media/*`),
surfacing each picture as its own viewable `office_image` item. An OOXML with neither text nor
images returns `status: failed`, never a silent ok.

The collector grabs ANY `/files/{id}` link, not only `/users/{uid}/files/…`; magic bytes then
decide the real type. The URL and the extension are hints only.

## `entry["attempts"]` (quiz)

`graders/quiz.py` returns one element per Canvas `submission_history` entry:
`{attempt, raw, needs_ai_essay, code_breakdown}`. Top-level fields mirror the latest attempt.
`core.py` copies this to `entry["attempts"]`; the poster writes each attempt's per-question scores.

## Known gaps

- `iframe_unknown` — a third-party `<iframe src>` has no reader and lands `failed`.
- `_RE_CANVAS_IMG` matches `users/{uid}/files/…` only; a `courses/{cid}/files/{id}/preview` embed
  would be missed. Student submissions use the `users/` form.

Both fail VISIBLY (Section 0 / `failed`), never silently.

## gws output is not uniform

`_gws_media_nb` downloads the `.ipynb` with `gws drive files get alt=media -o <base>`. Native Colab
(`application/vnd.google.colaboratory`) and `application/x-ipynb+json` SAVE to `-o`; a raw `.ipynb`
uploaded to Drive (`application/json`) DUMPS to stdout and creates no file. The fetch is therefore
OUTPUT-based, not mimeType-based: use the `-o` file if it landed, else parse stdout, else return
None so the NB grader raises a visible STOP.

`submission.body` is often EMPTY on a resubmission or a url submission — `core.grade` normalizes
the effective body to the latest attempt's body-or-url so the Colab/repo link is still found.
