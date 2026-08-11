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


# A first domain segment that names no school, so the next one is the better label.
_GENERIC_HOST_LABELS = {"canvas", "www", "lms", "elearning"}


def school_slug(canvas_url):
    """The file label for a Canvas URL — the first domain segment.

    `https://4cd.instructure.com` -> `4cd`. The label is for humans only: `get_token` matches
    on the `base_url` INSIDE the file, so renaming the file changes nothing.
    """
    host = urlparse(canvas_url if "//" in canvas_url else "https://" + canvas_url).netloc
    parts = [p for p in host.split(".") if p]
    if not parts:
        raise ValueError(f"not a Canvas URL: {canvas_url!r}")
    if parts[0] in _GENERIC_HOST_LABELS and len(parts) > 1:
        return parts[1]
    return parts[0]


def config_path(canvas_url):
    """Where this school's config belongs: `Canvas-Auth/<label>.json`."""
    return auth_dir() / f"{school_slug(canvas_url)}.json"


def register_school(canvas_url, token=None, *, overwrite=False, timeout=30):
    """Create or complete a school's config, and never store a token that does not work.

    With no `token`, writes the config with an empty token field and reports where the
    instructor should paste one — that path keeps the secret out of the conversation.
    With a `token`, verifies it against the live API FIRST and writes only on success.

    Returns {"status", "path", "base_url", ...} where status is one of:
      created            the shell exists now, token still empty
      awaiting_token     the shell already existed, token still empty
      registered         a verified token was written
      already_registered a token is already stored (pass overwrite=True to replace it)
    """
    host = urlparse(canvas_url if "//" in canvas_url else "https://" + canvas_url).netloc
    if not host:
        raise ValueError(f"not a Canvas URL: {canvas_url!r}")
    base_url = f"https://{host}/api/v1"
    path = config_path(canvas_url)
    path.parent.mkdir(parents=True, exist_ok=True)

    cfg = {}
    if path.exists():
        try:
            cfg = json.loads(path.read_text())
        except Exception:  # noqa: BLE001 — a damaged file is replaced, not obeyed
            cfg = {}
    cfg.setdefault("base_url", base_url)

    if cfg.get("token") and not token and not overwrite:
        return {"status": "already_registered", "path": str(path), "base_url": base_url}

    if token:
        identity = whoami(base_url, token, timeout=timeout)   # raises => nothing is written
        cfg["token"] = token
        path.write_text(json.dumps(cfg, indent=2) + "\n")
        return {"status": "registered", "path": str(path), "base_url": base_url,
                "identity": identity.get("name"), "user_id": identity.get("id")}

    existed = path.exists()
    cfg.setdefault("token", "")
    path.write_text(json.dumps(cfg, indent=2) + "\n")
    return {"status": "awaiting_token" if existed else "created",
            "path": str(path), "base_url": base_url}


def verify_school(canvas_url, timeout=30):
    """Check the stored token for a school. Returns the identity, or raises with the reason."""
    path = config_path(canvas_url)
    if not path.exists():
        raise RuntimeError(f"no config at {path}")
    cfg = json.loads(path.read_text())
    if not cfg.get("token"):
        raise RuntimeError(f"the token field in {path} is still empty")
    return whoami(cfg["base_url"], cfg["token"], timeout=timeout)


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
