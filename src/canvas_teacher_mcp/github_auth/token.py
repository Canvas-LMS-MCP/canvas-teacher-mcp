"""github_auth.token — GitHub authentication (login + token-owner identity).

The GitHub-side login foundation, mirroring canvas_token_auth on the GitHub
side. Sole owner of GitHub token resolution + the token-owner identity check.
The general GitHub API client (github_access) builds on this. Self-contained
(a single urllib call for whoami) so the auth foundation depends on nothing above.
"""
import json
import os
import subprocess
import urllib.request


def get_token():
    """Resolve a GitHub token: env GITHUB_TOKEN, else `gh auth token`."""
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return token
    try:
        return subprocess.check_output(["gh", "auth", "token"], text=True).strip()
    except Exception as e:  # noqa: BLE001
        raise RuntimeError("Could not resolve GitHub token (no GITHUB_TOKEN, gh CLI failed)") from e


_TOKEN_OWNER = {}


def token_owner_login(token):
    """The login of the account that owns the token (GET /user), lower-cased.

    Self-contained whoami (the login PROOF) — a single Bearer GET, cached per
    token. Best-effort: returns '' on failure. The grading engine uses this as
    the guaranteed half of instructor identification (the grade runs under the
    instructor's token, so the owner IS the instructor).
    """
    if token in _TOKEN_OWNER:
        return _TOKEN_OWNER[token]
    login = ""
    try:
        req = urllib.request.Request(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {token}",
                     "Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            login = ((json.loads(r.read()) or {}).get("login") or "").lower()
    except Exception:  # noqa: BLE001 — best-effort
        pass
    _TOKEN_OWNER[token] = login
    return login
