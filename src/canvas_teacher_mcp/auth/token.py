"""canvas_token_auth.token — token-based Canvas authentication (REST surface).

The TOKEN side of Canvas access, mirroring canvas_auth (the cookie/credential
foundation) on the token side. This package is the SOLE owner of token login;
the common REST client (canvas_rest, built next) imports get_token from here.

Token serves the official REST API (/api/v1) ONLY. The web-app surface
(gradebook CSV export, Roll Call) is cookie-only — see canvas_auth / canvas_core.
"""
import json
import os
import sys
import urllib.request
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ..canvas_root import auth_dir  # noqa: E402  — the tree root comes from the environment


def get_token(env_var, base_url=None):
    """Resolve a Canvas API token. Lookup order (first hit wins):

    1. Environment variable `env_var` (e.g. <SCHOOL>_CANVAS_TOKEN).
    2. The per-school config in Canvas-Auth whose `base_url` domain matches
       `base_url`: `Canvas-Auth/<school>.json` -> {"base_url", "token", "courses"}.
       Matched on the domain INSIDE the file, never on the filename — the filename is a
       human label. Adding a school is adding a file, never a code change.

    Raises RuntimeError if neither yields a token.
    """
    token = os.environ.get(env_var)
    if token:
        return token
    _AUTH_DIR = auth_dir()
    if base_url and _AUTH_DIR.is_dir():
        domain = urlparse(base_url).netloc          # https://<host>/api/v1 -> <host>
        for p in sorted(_AUTH_DIR.glob("*.json")):  # top-level configs only
            try:
                with open(p) as f:
                    cfg = json.load(f)
            except Exception:  # noqa: BLE001
                continue
            if domain and urlparse(cfg.get("base_url", "")).netloc == domain:
                tok = cfg.get("token")
                if tok:
                    return tok
    raise RuntimeError(
        f"Canvas token not found. Set env {env_var!r} OR add a per-school config "
        f"with matching base_url + token under {str(_AUTH_DIR)!r}"
    )


def whoami(base_url, token, timeout=30):
    """Verify a token by calling GET /users/self.

    Returns the authenticated identity dict ({id, name, ...}) or raises. This is
    the login PROOF — self-contained (a single urllib Bearer GET) so the token
    package is testable on its own. The full REST client lives in canvas_rest.
    """
    url = f"{base_url}/users/self"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())
