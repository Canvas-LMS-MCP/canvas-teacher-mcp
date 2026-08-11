"""canvas_auth.session — Canvas auth/session FOUNDATION.

Everyone depends on this; it depends on nothing above it (imports no resource module).
Reads the school's session cookies from the storageState json that login() exports
(Canvas-Auth/storageState/<school>/cookies.json) into a ready-to-use authenticated HTTP
client, supplies the CSRF token, and refreshes the session via login() on 401.

This cookie-session client is used for a school whose Canvas token is absent (cookie HTTP only).
WHICH schools is derived from token presence — never stated here; see
CourseGlobalWorkflow/Access/CanvasAuth.md. Playwright is used ONLY to establish/refresh the
session (canvas_auth.login, playwright-python — NO node). After login, every data call is
plain HTTP. (grade_engine keeps its own auth for now and migrates onto this foundation later.)

Stdlib only (urllib) — zero external deps; runs on the system Python (anaconda hangs Playwright
subprocesses). Every path derives from CANVAS_LMS_ROOT — see canvas_root.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ..canvas_root import auth_dir  # noqa: E402  — the tree root comes from the environment


def _domain_from_config(school: str):
    """The school's Canvas host, from Canvas-Auth/<school>.json `base_url` — the SINGLE SOURCE OF
    TRUTH for which instance the school is on. A school name is NOT its subdomain, and one
    subdomain can serve several colleges, so this is never derived from the name. None if there is
    no json or no base_url."""
    p = auth_dir() / f"{school}.json"
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text())
        b = d.get("base_url") or (next(iter((d.get("schools") or {}).values()), {}) or {}).get("base_url")
        if b:
            from urllib.parse import urlparse
            return urlparse(b).netloc or None
    except Exception:
        return None
    return None


def _school_storage_dir(school: str) -> Path:
    """All cookie/session state for a school, under Canvas-Auth (Drive-synced).
    Layout: Canvas-Auth/README.md. Policy: CourseGlobalWorkflow/Access/CanvasAuth.md."""
    return auth_dir() / "storageState" / school


def canvas_profile_dir(school: str) -> Path:
    """Per-school Chrome profile (saved SSO password + live session), stored UNDER Canvas-Auth
    so the autofill credential is Drive-synced with the repo. login() launches THIS profile
    (autofill), then exports the session-scoped cookie to cookies_json_path().
    Layout: Canvas-Auth/README.md. Policy: CourseGlobalWorkflow/Access/CanvasAuth.md."""
    return _school_storage_dir(school) / "login-credential"


def cookies_json_path(school: str) -> Path:
    """storageState json (session cookies) exported by login(); readers load THIS.
    The Canvas auth cookie is session-scoped and does NOT persist in the Chrome profile
    folder, so it must be dumped here via ctx.storage_state()."""
    return _school_storage_dir(school) / "cookies.json"


def read_profile_cookies(school: str, domain: str):
    """Read cookies for `domain` from the exported storageState json (which carries the
    session cookie the Chrome profile folder drops). Returns ({name: value}, csrf|None);
    empty if no json yet (the first 401 → relogin() bootstraps it)."""
    import json
    p = cookies_json_path(school)
    if not p.exists():
        return {}, None
    data = json.loads(p.read_text())
    cookies = {c["name"]: c["value"] for c in data.get("cookies", []) if domain in c.get("domain", "")}
    csrf = urllib.parse.unquote(cookies.get("_csrf_token", "")) or None
    return cookies, csrf


class Resp:
    """Minimal response wrapper (requests-like surface over urllib)."""

    def __init__(self, status: int, headers, body: bytes):
        self.status_code = status
        self.headers = headers  # http.client.HTTPMessage — case-insensitive .get()
        self.content = body

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", "replace")

    def json(self):
        return json.loads(self.content)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code} for request: {self.text[:300]}")


class CanvasSession:
    """Authenticated Canvas HTTP client backed by the per-school Chrome profile (cookies read live).

    Use `.get()/.post()` (auto-refreshes once on 401). `xhr=True` adds the
    XMLHttpRequest/JSON headers; `csrf=True` adds the X-CSRF-Token header.
    """

    def __init__(self, school: str, domain: str | None = None):
        self.school = school
        # No default school: an omitted one would silently authenticate against someone else's
        # Canvas. The domain comes from the school's own config; the name is never a subdomain.
        self.domain = domain or _domain_from_config(school) or f"{school}.instructure.com"
        self.base = f"https://{self.domain}"
        self.token = self._resolve_token()   # token school → Bearer; token absent → cookie session
        self.cookies, self.csrf = {}, None
        if not self.token:
            self._load()

    def _resolve_token(self):
        """Bearer token if the school has one (env or Canvas-Auth/<school>.json), else None (cookie)."""
        import os
        env = os.environ.get(f"{self.school.upper()}_CANVAS_TOKEN")
        if env:
            return env
        p = auth_dir() / f"{self.school}.json"
        if p.exists():
            d = json.loads(p.read_text())
            if d.get("token"):
                return d["token"]
            schools = d.get("schools") or {}
            if schools:
                return next(iter(schools.values())).get("token")
        return None

    def _load(self) -> None:
        # cookies live in the per-school Chrome profile (no json copy) → read them live via a
        # headless launch. Empty if the profile isn't seeded yet — the first 401 triggers
        # relogin() → login() bootstraps it.
        self.cookies, self.csrf = read_profile_cookies(self.school, self.domain)

    # --- session refresh (login) ------------------------------------------------
    def relogin(self) -> None:
        """Refresh an expired/missing session via canvas_auth.login (playwright-python, NO node).

        Auto-logs in using the saved Chrome profile (autofill). If there is no saved credential,
        login() raises NeedsLogin → it propagates so the operator guides the one-time manual
        login (log in + Save password + remember device) and re-runs.
        """
        from .login import login  # deferred import (avoid circular)
        login(self.school)
        self._load()

    # --- HTTP -------------------------------------------------------------------
    def headers(self, extra=None, xhr=False, csrf=False) -> dict:
        """The auth headers for one request — PUBLIC (canvas_rest calls this).
        token school -> Authorization: Bearer; token-less -> Cookie (+ X-CSRF-Token when csrf).
        This is the ONE place the token/cookie choice is made."""
        if self.token:
            h = {"Authorization": f"Bearer {self.token}"}   # token school: no cookie, no CSRF
        else:
            h = {"Cookie": "; ".join(f"{k}={v}" for k, v in self.cookies.items())}
        if xhr:
            h["X-Requested-With"] = "XMLHttpRequest"
            h["Accept"] = "application/json"
        if csrf and not self.token:
            if not self.csrf:
                raise RuntimeError("no _csrf_token in session cookies (re-seed the session)")
            h["X-CSRF-Token"] = self.csrf
        if extra:
            h.update(extra)
        return h

    def _do(self, method, url, headers, data, timeout) -> Resp:
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return Resp(r.status, r.headers, r.read())
        except urllib.error.HTTPError as e:
            return Resp(e.code, e.headers, e.read())

    def _alive(self) -> bool:
        """True if the CURRENT cookies still authenticate. No retry, never relogins, no browser.

        Asked before paying for a relogin, because a 401 does not always mean the session died —
        one endpoint can reject a request the session is perfectly entitled to make.
        """
        r = self._do("GET", self.base + "/api/v1/users/self", self.headers(), None, 15)
        return r.status_code == 200

    def request(self, method, path, *, xhr=False, csrf=False, headers=None, data=None,
                json=None, params=None, allow_relogin=True, timeout=60) -> Resp:
        url = path if path.startswith("http") else self.base + path
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        if json is not None:
            import json as _json
            data = _json.dumps(json).encode()
            headers = {**(headers or {}), "Content-Type": "application/json"}
        elif isinstance(data, dict):
            # form dict → urlencoded body
            data = urllib.parse.urlencode(data).encode()
            headers = {**(headers or {}), "Content-Type": "application/x-www-form-urlencoded"}
        if method == "POST" and data is None:
            data = b""  # force a real POST body
        r = self._do(method, url, self.headers(headers, xhr=xhr, csrf=csrf), data, timeout)
        if r.status_code == 401 and allow_relogin and not self.token:
            # Confirm the session is REALLY dead before relogging in. A 401 from one endpoint is not
            # proof of expiry, and relogin is expensive + headed: a live session that hit an
            # endpoint-specific 401 used to be dragged through a full SSO round-trip (2026-07-28,
            # gradebook_csv → 60s navigation timeout). Alive ⇒ let the 401 stand so the caller sees
            # the real error instead of a phantom login problem.
            if self._alive():
                return r
            self.relogin()
            r = self._do(method, url, self.headers(headers, xhr=xhr, csrf=csrf), data, timeout)
        return r

    def get(self, path, **kw) -> Resp:
        return self.request("GET", path, **kw)

    def post(self, path, **kw) -> Resp:
        return self.request("POST", path, **kw)

    def put(self, path, **kw) -> Resp:
        return self.request("PUT", path, **kw)

    def delete(self, path, **kw) -> Resp:
        return self.request("DELETE", path, **kw)

    def verify(self) -> dict:
        """Smoke test: GET /api/v1/users/self → user dict (raises on failure)."""
        r = self.get("/api/v1/users/self")
        r.raise_for_status()
        return r.json()


# NOTE: rollcall session (LTI sessionless_launch → mint rollcall cookie) is added in the
# attendance phase — it needs a browser launch, so it lives alongside this foundation as a
# separate helper (rollcall_session) rather than bloating CanvasSession.
