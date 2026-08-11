"""canvas_rest.client — Canvas REST transport (login-free).

Pure HTTP over the official Canvas REST API (/api/v1): paginated GET, raw byte
download, JSON PUT. Every function takes (base_url, auth, ...) — it NEVER
acquires a credential (token resolve lives in canvas_token_auth, cookie/session in
canvas_auth) and hardcodes nothing course/grading-specific. This is the generic
Canvas client, distilled later into the canvas-lms MCP's resource transport.

`auth` is EITHER:
  - a token string            -> Authorization: Bearer <token>
  - a canvas_auth.CanvasSession -> it decides token vs cookie (+CSRF) itself
Canvas accepts either credential on the SAME REST call; the choice is made in ONE
place (`CanvasSession.headers`), never here. Passing a token string keeps every
pre-existing caller working unchanged.
"""
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request


def _auth_headers(auth, write=False):
    """Auth headers for one request. token str -> Bearer; CanvasSession -> its own
    choice (Bearer, or Cookie + X-CSRF-Token when `write`)."""
    if isinstance(auth, str):
        return {"Authorization": f"Bearer {auth}"}
    return auth.headers(csrf=write)


class CanvasHTTPError(RuntimeError):
    """A Canvas request failed. RAISED, never returned as an empty result.

    Every URL here is assembled by US from course_config (base_url + course_id + slug),
    so ANY failure means our address or our session is wrong — including 404, which says
    the page/assignment we asked for is not there. There is no failure this code can
    meaningfully continue past, and a silent None would surface later as a bogus
    "no assignments / no submissions" (a grading hazard). So: fail loud, at the cause.
    """

    def __init__(self, status, url, body=""):
        self.status, self.url, self.body = status, url, body
        super().__init__(f"Canvas HTTP {status} for {url}" + (f" — {body[:300]}" if body else ""))


def _http(url, headers, timeout=30, retries=3, raw=False):
    """GET `url` and return (data, content_type, link_header). Raises CanvasHTTPError
    on any failure (429/502/503 are retried first). Success shape is unchanged."""
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read()
                link = r.headers.get("Link", "") or ""
                ct = r.headers.get("Content-Type", "") or ""
                if raw:
                    return body, ct, link
                return json.loads(body), ct, link
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code in (502, 503, 429):
                time.sleep(2 * (attempt + 1))
                continue
            raise CanvasHTTPError(e.code, url, e.read().decode("utf-8", "replace")) from e
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(1)
    status = getattr(last_err, "code", None)
    raise CanvasHTTPError(status, url, str(last_err)) from last_err


def get(base_url, token, path, params=None, paginate=True):
    """GET with pagination. Returns list (or single object if endpoint isn't a list)."""
    url = f"{base_url}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    items = []
    while url:
        data, _, link = _http(url, _auth_headers(token))
        if data is None:
            return None
        if isinstance(data, list):
            items.extend(data)
        else:
            return data
        if not paginate:
            break
        m = re.search(r'<([^>]+)>;\s*rel="next"', link)
        url = m.group(1) if m else None
    return items


def get_raw(url, token, retries=3):
    """Download a URL as raw bytes. Used for verifier-URL Canvas attachments."""
    body, ct, _ = _http(url, _auth_headers(token), retries=retries, raw=True)
    return body, ct


def put(base_url, token, path, payload):
    """PUT JSON. Returns (status_int, response_dict_or_text)."""
    url = f"{base_url}{path}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="PUT",
        headers={**_auth_headers(token, write=True),
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            try:
                return r.status, json.loads(r.read())
            except Exception:  # noqa: BLE001
                return r.status, ""
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:500]


def post(base_url, token, path, payload):
    """POST JSON (create a resource). Returns (status_int, response_dict_or_text)."""
    url = f"{base_url}{path}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={**_auth_headers(token, write=True),
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            try:
                return r.status, json.loads(r.read())
            except Exception:  # noqa: BLE001
                return r.status, ""
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:500]


def delete(base_url, token, path):
    """DELETE a resource. Returns (status_int, response_dict_or_text)."""
    url = f"{base_url}{path}"
    req = urllib.request.Request(
        url,
        method="DELETE",
        headers=_auth_headers(token, write=True),
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            try:
                return r.status, json.loads(r.read())
            except Exception:  # noqa: BLE001
                return r.status, ""
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:500]
