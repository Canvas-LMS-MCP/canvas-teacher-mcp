# Attachments

Read every student attachment through the engine. Shapes and arguments: `code/grade_engine/MANUAL.md`.

```python
from grade_engine.lib.attachments import read, AttachmentReadError
result = read(submission, download_dir=..., github_org="<org>")
```

- Fetch nothing yourself. `urllib`, `requests`, `http.client`, `pdftotext`, `tesseract`, `ocrmac`
  and `gws drive|docs|slides` are forbidden anywhere outside `lib/attachments.py`; `engine.selftest`
  greps for them and refuses to grade when it finds one.
- Treat `status == "stop"` or `AttachmentReadError` as 🚨 NOT GRADED — flag the student and skip
  them. Never turn a read failure into a 0.
- Read `item["view_path"]` for an image. It is the same picture, downscaled, so §0Z still holds and
  the vision cost is a fraction. Escalate to `item["path"]` only when the view is too coarse.
- Grade a batch through `read_many`, never a hand-rolled loop.

**Separate the two failure kinds.**

| Kind | Example | Action |
|---|---|---|
| Engine-side | URL form unhandled, magic byte unrecognized, regex too narrow | STOP, fix the code first |
| Student-quality | private GDoc, encrypted PDF, dead link, handwriting OCR fails | 0 on that item, comment with the resubmit fix |

**Never return `status: ok` with empty content.** Collect every resource reference, download it,
let MAGIC BYTES decide the type, deep-read per real type. Anything unknown is FLAGGED, never a
silent 0.

The rule exists because graders that fetched attachments themselves lost real grades: an
image-only submission scored 3/10 because OCR never ran, and a PDF link with `wrap=1` returned the
HTML viewer instead of the file. One library, one contract, no discretion.
