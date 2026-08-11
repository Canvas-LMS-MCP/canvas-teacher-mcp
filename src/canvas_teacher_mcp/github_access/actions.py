"""github_access.actions — general GitHub repo reads (Actions runs, commits).

Login-free wrappers over github_access.client for any repo: Actions runs, the
autograder run-log zip, commits, one commit's detail. (token, repo, ...) — no
grading coupling. Autograder-result PARSING + student-commit filtering are
grading-specific and live in the grade engine, not here.
"""
import os
import urllib.request

from .client import get

# Absurd hard ceiling on the run-log zip DOWNLOAD (compressed bytes). It exists only
# to refuse a pathological runaway; no legit autograder log is anywhere near this, so
# normal grading always downloads in full. The MONITOR threshold (a much smaller size
# that raises a report alert but does NOT block) lives in the grade engine, not here.
LOG_HARD_CAP_BYTES = 500 * 1024 * 1024  # 500 MB


def list_runs(token, repo, branch=None):
    """Recent GitHub Actions runs for a repo (optionally a branch)."""
    if branch:
        return get(token, f"/repos/{repo}/actions/runs?branch={branch}&per_page=10")
    return get(token, f"/repos/{repo}/actions/runs?per_page=10")


def list_commits(token, repo):
    """All commits for a repo."""
    return get(token, f"/repos/{repo}/commits?per_page=100")


def get_commit(token, repo, sha):
    """One commit's detail — includes `stats` (additions/deletions) and `files`."""
    return get(token, f"/repos/{repo}/commits/{sha}", paginate=False)


def get_run_log(token, repo, run_id, cache_path):
    """Download the Actions run-log zip for a run. Returns local path or None.

    Caches to `cache_path` if given (returns it directly if already present).
    """
    if cache_path and os.path.exists(cache_path) and os.path.getsize(cache_path) > 0:
        return cache_path
    url = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/logs"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }
    # Check the (redirect-followed) Content-Length BEFORE reading the body, so an
    # absurdly large zip is never transferred. Compressed size only — the engine's
    # uncompressed MONITOR check catches repetitive floods that compress small.
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=60) as r:
            clen = r.headers.get("Content-Length")
            if clen and int(clen) > LOG_HARD_CAP_BYTES:
                return None  # > 500 MB zip — refuse (pathological; never a legit log)
            body = r.read()
    except Exception:  # noqa: BLE001
        return None
    if not body:
        return None
    if cache_path:
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "wb") as f:
            f.write(body)
    return cache_path
