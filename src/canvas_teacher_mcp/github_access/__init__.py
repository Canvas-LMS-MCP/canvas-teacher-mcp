"""github_access — general, login-free GitHub REST access (common code layer).

The GitHub-side common code, mirroring canvas_rest on the Canvas side. Built on
github_auth (token login). Generic — (token, repo, ...), no grading hardcode —
so it distills cleanly into a publishable GitHub resource layer / MCP later.

  client  — transport: get  (+ internal _http)
  actions — repo reads: list_runs / get_run_log / list_commits / get_commit

Token: obtain it from github_auth.get_token() and pass it in. Autograder-result
parsing + student-commit filtering are grading-specific and live in the grade
engine. Old GitHub Classroom API calls are intentionally absent (replaced by the
org-hub classroom).
"""
from .client import get
from .actions import list_runs, list_commits, get_commit, get_run_log

__all__ = ["get", "list_runs", "list_commits", "get_commit", "get_run_log"]
