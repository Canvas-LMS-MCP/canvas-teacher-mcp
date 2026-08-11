# BrowserFetcher

The engine downloads attachments over plain HTTP and `gws`. That covers 99% of submissions.

- Import no browser library in engine code. `selftest` greps `grade_engine/` for
  `playwright|selenium|pyppeteer` and refuses to grade on a hit.
- Inject a project fetcher when a URL genuinely needs a real browser session — an expired Canvas
  `verifier`, a Doc shared only with the instructor account, a dynamic render.

```python
def fetcher(url: str, out_path: str) -> bool: ...
```

- Return `True` once `out_path` holds the body, `False` on any routine failure. Never raise on a
  404, an auth failure or a timeout.
- Own the browser session, the locking and the cleanup inside the fetcher. It receives a URL and a
  path and returns a bool — nothing else.
- Run headless, and never share one Chrome profile between concurrently-running projects.

The engine calls it only after its own HTTP path failed (401/403/404, or HTML where binary was
expected), always with an absolute writable path, never twice in parallel for the same URL.

`selftest` exercises a registered fetcher against a known-good URL and refuses to grade unless it
returns a bool, writes a non-empty file, and does not raise.

With no fetcher registered the affected item lands in Section 0 — "could not fetch over HTTP and
no browser fetcher provided". The engine never scores it 0 silently.

Credentials are a different concern and need no injection: `core._credential` resolves the
school's token or `CanvasSession`, and `canvas_rest` accepts either.
