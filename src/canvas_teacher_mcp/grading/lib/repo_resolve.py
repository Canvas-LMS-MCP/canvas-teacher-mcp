"""Student repo resolution — org-hub model (GitHub Classroom removed 2026-06-25).

Two steps, both keyed off data the engine already has:

  Step 1 (PRIMARY) — the link the student pasted in the submission. The engine's
     central read (``attachments.read(..., github_org=...)``) extracts it ONCE and
     returns ``repo_link`` = "{org}/{repo}"; ``resolve()`` consumes that. A present
     link IS the student's repo (it carries the {slug}-{username} identity).
  Step 2 (FALLBACK) — no link → ``resolve_repo_from_log()``: find the repo in the
     org-hub REQUEST LOG (``<org>/classroom-admin/log/<repo>.json``) by the student's
     email or name. NON-CRITICAL (a missing link is the student's fault → 0 + flag);
     a courtesy lookup, never the primary path.

No roster / CSV / SQLite / accepted_assignments — the org-hub log is the live source.
Returns (repo_full_name | None, source). source ∈ {"body", "log", None}.
"""
import re


def extract_repo_from_body(text, github_org):
    """Parse a repo full_name from free text. Matches `github.com/org/repo` and the
    bare `org/repo` form. Trims a trailing path segment (e.g. `org/repo/main.py`)
    and a trailing `.git` (students often paste the CLONE url `…/org/repo.git`;
    the char class below includes `.`, so `.git` would otherwise be kept and every
    GitHub API call against `org/repo.git` 404s → tp=None / 0 commits / wrong 0)."""
    if not github_org or not text:
        return None
    m = re.search(rf"(?:github\.com/)?({re.escape(github_org)}/[A-Za-z0-9._\-]+)",
                  text, re.IGNORECASE)   # students paste `<org>/…` lower-cased; GitHub is case-insensitive
    if not m:
        return None
    repo = m.group(1)
    parts = repo.split("/")
    if len(parts) > 2:
        repo = "/".join(parts[:2])
    if repo.endswith(".git"):            # clone-url suffix — never part of the real repo name
        repo = repo[:-4]
    return repo


def _name_key(name):
    """Order/format-insensitive key for a person name: the set of alpha words,
    lower-cased. 'Last, First' == 'First Last' == 'first  last'."""
    return frozenset(re.findall(r"[a-z]+", (name or "").lower()))


def resolve_repo_from_log(name, email, *, org, repo_prefix, code, gh_get):
    """Step-2 fallback (NO submission link): find the student's repo from the org-hub
    REQUEST LOG. Reads ``<org>/classroom-admin/log/<repo>.json`` (one per provisioned
    repo; fields: name, email, assignment, semester, repo, username). Filters filenames
    to ``{repo_prefix}-{code}-*`` (term+assignment scope — no cross-term search), reads
    each, matches the student's **email** (primary, unique school email) OR **name**
    (word-set, fuzzy) → returns the entry's ``repo``.

      0 matches → ``None`` (never requested / email-name mismatch — caller: 0 + flag)
      2+ matches → ``None`` (multi-account same student — caller flags; never guess)

    ``gh_get(path)`` returns parsed GitHub Contents-API JSON. This REPLACES the old roster
    (no CSV / SQLite / cache — the org-hub log is the live source). Non-critical fallback:
    the submitted link (Step 1) is the primary path."""
    import json as _json
    import base64 as _b64
    want = f"{repo_prefix}-{code}-".lower()
    nkey = _name_key(name)
    em = (email or "").strip().lower()
    if not (nkey or em):
        return None
    listing = gh_get(f"/repos/{org}/classroom-admin/contents/log") or []
    hits = []
    for f in listing:
        fn = f.get("name") or ""
        if not fn.lower().startswith(want):
            continue
        try:
            entry = gh_get(f"/repos/{org}/classroom-admin/contents/log/{fn}")
            data = _json.loads(_b64.b64decode(entry.get("content", "")))
        except Exception:  # noqa: BLE001 — skip an unreadable log entry, never crash the run
            continue
        # email is the exact bridge; name is a FALLBACK. A student registers with a shorter
        # name than Canvas shows ("Daniel Munoz" vs Canvas "DANIEL MUNOZ BARRETO"), so exact
        # word-set equality mis-misses. Accept a SUBSET match (>=2 shared words) in either
        # direction; the caller still requires exactly ONE hit, so an ambiguous match resolves
        # to None rather than to the wrong student.
        lkey = _name_key(data.get("name"))
        name_hit = bool(nkey and lkey) and (
            lkey == nkey or (len(lkey & nkey) >= 2 and (lkey <= nkey or nkey <= lkey)))
        if (em and (data.get("email") or "").strip().lower() == em) or name_hit:
            if data.get("repo"):
                hits.append(f"{org}/{data['repo']}")
    return hits[0] if len(hits) == 1 else None


def is_assignment_repo(repo, repo_prefix, code):
    """True when `repo` ("{org}/{name}") is THIS assignment's student repo, i.e. its name
    part starts with `{repo_prefix}-{code}-`. Guards the Step-1 link: a student who pastes
    the org-hub issue URL (`github.com/<org>/classroom/issues/154`) yields the INFRA repo
    `<org>/classroom`, which then gets graded — no autograder, no student commits, so the
    engine reports None/0 and the student loses the whole assignment. Verified 2026-07-09
    (CSCI-19A A21, Enrique). This is a VALIDATION of a resolved name, not construction of
    one (GitHub.md "resolve, never construct")."""
    if not (repo and repo_prefix and code):
        return False
    name = repo.split("/")[-1].lower()
    return name.startswith(f"{repo_prefix}-{code}-".lower())


def resolve_reconciled(repo_link, name=None, email=None, *, org=None, repo_prefix=None,
                       code=None, gh_get=None):
    """GRADING.md Part B §0 step 3 — RECONCILE the submitted link against the canonical
    org-hub log entry, instead of trusting whichever one is present.

    Returns ``{"repo", "source", "flag"}``; ``flag`` is instructor-facing (Section 0) or
    None when the two agree. ``source`` ∈ {"body","log","mismatch","unregistered","bad-link"}.

    | submitted (B)        | canonical (A) | result                                    |
    |----------------------|---------------|-------------------------------------------|
    | absent               | repo          | grade A ("log")                           |
    | == A                 | repo          | grade A ("body")                          |
    | != A                 | repo          | grade A, **FLAG** ("mismatch")            |
    | not an asmt repo     | repo          | grade A, **FLAG** ("bad-link")            |
    | present, not in log  | ∅             | grade B, **FLAG unregistered**            |
    | absent               | ∅             | (None) → 0 + Section 0                     |
    """
    canonical = None
    if gh_get and org and repo_prefix and code:
        canonical = resolve_repo_from_log(name, email, org=org, repo_prefix=repo_prefix,
                                          code=code, gh_get=gh_get)
    link_ok = is_assignment_repo(repo_link, repo_prefix, code)

    if repo_link and not link_ok:
        if canonical:
            return {"repo": canonical, "source": "bad-link",
                    "flag": (f"submitted link `{repo_link}` is NOT this assignment's repo "
                             f"(expected `{repo_prefix}-{code}-*`) — graded the canonical "
                             f"org-hub repo `{canonical}` instead")}
        return {"repo": None, "source": None,
                "flag": (f"submitted link `{repo_link}` is not an assignment repo and no "
                         f"org-hub log entry was found")}
    if link_ok and canonical:
        if repo_link.lower() == canonical.lower():
            return {"repo": canonical, "source": "body", "flag": None}
        return {"repo": canonical, "source": "mismatch",
                "flag": (f"submitted repo `{repo_link}` ≠ canonical org-hub repo "
                         f"`{canonical}` — graded the canonical one; verify which is the "
                         f"student's real work before posting")}
    if link_ok:
        return {"repo": repo_link, "source": "unregistered",
                "flag": (f"repo `{repo_link}` was submitted but has no org-hub request-log "
                         f"entry (never registered/requested)")}
    if canonical:
        return {"repo": canonical, "source": "log", "flag": None}
    # Neither a link nor a log entry: the student simply never requested a repo. That is
    # already reported as "No repo resolved" (Section 0) — do NOT also raise a reconcile
    # flag, or every non-submitter is double-listed as a discrepancy.
    return {"repo": None, "source": None, "flag": None}


def resolve(repo_link, name=None, email=None, *, org=None, repo_prefix=None,
            code=None, gh_get=None):
    """Resolve the student's repo (org-hub).

      Step 1  ``repo_link`` present (from ``attachments.read``) → (repo_link, "body")
      Step 2  no link → request-log lookup by email/name        → ("{org}/{repo}", "log")
      else                                                       → (None, None)  [0 + flag]

    ``gh_get(path)`` (org-hub log reader) is INJECTED; without it (or without
    org/repo_prefix/code) Step 2 is skipped and a missing link → (None, None)."""
    if repo_link:
        return repo_link, "body"
    if gh_get and org and repo_prefix and code:
        r = resolve_repo_from_log(name, email, org=org, repo_prefix=repo_prefix,
                                  code=code, gh_get=gh_get)
        if r:
            return r, "log"
    return None, None
