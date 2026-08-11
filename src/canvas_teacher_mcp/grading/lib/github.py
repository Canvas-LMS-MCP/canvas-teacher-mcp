"""DEPRECATED shim — kept so the grade engine keeps importing
`grade_engine.lib.github` unchanged during the JS->Python / MCP refactor.

The GENERAL, login-free GitHub code moved to sibling packages:
  - login + token-owner identity  -> github_auth
  - transport + repo reads (runs / commits / logs)  -> github_access

What REMAINS here (do not move yet):
  - grading-specific: parse_total_points_from_log_zip, filter_student_commits,
    instructor_logins (+ INFRA_BOT_LOGINS / PLACEHOLDER_LOGINS).
  (GitHub Classroom API removed 2026-06-25 — org-hub repo-resolution replaced it:
   Canvas student -> attachments repo_link / org-hub log -> repo. See repo_resolve.py.)
"""
import re
import zipfile

# --- moved out: login-free general code (re-exported for back-compat) ---
from ...github_auth import get_token, token_owner_login                  # noqa: F401
from ...github_access import get, list_runs, list_commits, get_commit, get_run_log  # noqa: F401


# ============================================================================
# grading-specific (stay in the engine)
# ============================================================================
# GitHub Classroom + CI platform bots — always infrastructure, never student work.
INFRA_BOT_LOGINS = {"github-classroom[bot]", "github-actions[bot]", "dependabot[bot]"}

# GitHub's marker(s) for a commit whose email it cannot link to ANY account
# (malformed / generic / unverified email, e.g. the git default you@example.com).
PLACEHOLDER_LOGINS = {"invalid-email-address"}

def instructor_logins(token):
    """The instructor login set to exclude from a student repo's commits (closed
    write-set: student commits = ALL − bots − instructor). In the org-hub model the
    ONLY non-bot, non-student committer is the grading token's OWNER (the instructor)
    — every student repo's setup commits are authored by them. So this is just
    ``{token_owner}`` (zero-config, from ``GET /user``); bots are excluded separately
    by ``INFRA_BOT_LOGINS`` in ``filter_student_commits``. Returns a set of
    lower-cased logins (empty if the owner can't be resolved)."""
    owner = (token_owner_login(token) or "").lower()
    return {owner} if owner else set()


def parse_total_points_from_log_zip(zip_path):
    """Return (totalPoints, maxPoints) from autograder reporter log, or (None, None)."""
    try:
        with zipfile.ZipFile(zip_path) as z:
            for name in z.namelist():
                try:
                    with z.open(name) as f:
                        text = f.read().decode("utf-8", "replace")
                except Exception:  # noqa: BLE001
                    continue
                m = re.search(r'\{"totalPoints":(\d+),"maxPoints":(\d+)\}', text)
                if m:
                    return int(m.group(1)), int(m.group(2))
    except Exception:  # noqa: BLE001
        pass
    return None, None


def filter_student_commits(commits, repo=None, student_login=None, instructor_logins=None):
    """Return ``(student_commits, flags)`` for a student's accepted Classroom repo.

    CLOSED WRITE-SET MODEL. Only two parties can push to an accepted repo: the
    instructor (= the grading token's owner, plus whoever authored the starter
    template) and the one student who accepted it. So every commit is one or the
    other, and the rule is simply::

        student commits  =  ALL commits  −  infra bots  −  instructor

    ``instructor_logins`` is the guaranteed set from :func:`instructor_logins`
    (token owner ∪ starter authors). ``author.login`` is used ONLY to phrase
    informational flags — never to keep/drop a commit.
    """
    repo_l = (repo or "").strip().lower()
    sl = (student_login or "").strip().lower()
    instr = {(x or "").strip().lower() for x in (instructor_logins or [])}
    out, flags = [], []
    for c in commits or []:
        author = (c.get("author") or {}) or {}
        login = author.get("login") or ""
        login_l = login.lower()
        atype = author.get("type")            # "User" | "Bot" | None (unattributed)
        sha = (c.get("sha") or "")[:8]
        if login_l in PLACEHOLDER_LOGINS:     # GitHub "can't link this email" → treat as null
            login, login_l, atype = "", "", None
        if login_l in INFRA_BOT_LOGINS:
            continue                          # platform infra → excluded, not student
        if login_l and login_l in instr:
            continue                          # instructor (token owner / starter) → excluded
        # closed write-set: everything left is the student's own commit → KEEP.
        out.append(c)
        # informational flags only — these do NOT change keep/drop:
        if atype == "Bot":
            flags.append(f"automation/bot commit by '{login}' — not a human author; "
                         f"check human-written [{sha}]")
        elif login_l:
            is_accept = (repo_l.endswith("-" + login_l) if repo_l
                         else (bool(sl) and login_l == sl))
            if not is_accept:
                flags.append(f"committed from another account '{login}' — the student's "
                             f"other GitHub account (closed write-set: only the instructor "
                             f"and this student can push) [{sha}]")
    return out, flags
