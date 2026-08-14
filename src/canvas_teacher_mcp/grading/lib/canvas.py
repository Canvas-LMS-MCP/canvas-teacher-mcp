"""DEPRECATED shim — kept so the grade engine keeps importing
`grade_engine.lib.canvas` unchanged during the JS->Python / MCP refactor.

The GENERAL, login-free Canvas code moved to sibling packages:
  - token login  -> canvas_token_auth   (also fixes the old stale credentials
    path: tokens now resolve from the SHARED Course_Globals/.claude/Canvas-Auth,
    not ~/.claude/.credentials.json)
  - transport + resources (get / get_raw / put, fetch_*)  -> canvas_rest

What REMAINS here (grading-specific Canvas<->GitHub bridge): submission-body
parsing to recover a student's GitHub login / repo. !! These become OBSOLETE
when org-hub repo-resolution (Canvas student -> org-hub log -> repo) replaces
parsing the submission link. REMOVE them then. (See working log / playbook.)
"""
import re

# --- moved out: login-free general code (re-exported for back-compat) ---
from ...auth.token import get_token                                   # noqa: F401
from ...rest.client import get, get_raw, put                          # noqa: F401
from ...rest.resources import (                                       # noqa: F401
    fetch_submissions, fetch_assignment, fetch_users, fetch_rubric,
)


# ============================================================================
# grading-specific Canvas<->GitHub bridge (ORG-HUB-OBSOLETE; remove with
# repo-resolution rewire — the org-hub log replaces submission-link parsing)
# ============================================================================
_GH_LINK_RE = re.compile(r"github\.com/([\w-]+)/([\w-]+)")


def extract_github_login_from_body(body, github_org, repo_prefix=None):
    """From a Canvas submission body HTML, find the student's GitHub login.

    Looks for `github.com/{org}/{repo}` where `{repo}` is `{prefix}-{login}`
    (Classroom convention). Returns the login portion, or None.
    """
    if not body:
        return None
    for m in _GH_LINK_RE.finditer(body):
        org, repo = m.group(1), m.group(2)
        if org.lower() != github_org.lower():
            continue
        idx = repo.find("-")
        if idx < 0:
            continue
        login = repo[idx + 1:]
        if login:
            return login
    return None


def extract_repo_from_body(body, github_org):
    """From a Canvas submission body, return the repo full_name `{org}/{repo}`
    the student pasted, or None. Returns the first github.com/{org}/{repo} link
    whose org matches `github_org`."""
    if not body:
        return None
    for m in _GH_LINK_RE.finditer(body):
        org, repo = m.group(1), m.group(2)
        if org.lower() == github_org.lower():
            return f"{org}/{repo}"
    return None


def fetch_uid_to_login_map(base_url, token, course_id, asmt_id, github_org):
    """For one Hello-World-like asmt, return {canvas_uid: github_login} by reading
    each submission body. Submissions without a matching link are skipped."""
    subs = fetch_submissions(base_url, token, course_id, asmt_id) or []
    out = {}
    for s in subs:
        uid = s.get("user_id")
        body = s.get("body") or ""
        login = extract_github_login_from_body(body, github_org)
        if uid and login:
            out[uid] = login
    return out
