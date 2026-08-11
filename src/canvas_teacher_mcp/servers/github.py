"""GitHub tools — starter repositories and what the autograder reported.

Writing here runs `git` and `gh` on this machine, so both must be installed; the failure says
so rather than half-building a repository.

Reads are how a coding assignment is graded: the autograder's run and its log are the evidence,
not the code as it stands now.
"""

from __future__ import annotations

import contextlib
import io
import sys

from ..github_access import actions
from ..github_auth import get_token
from . import _ctx

TOOLS = ("build_starter_repo", "list_autograder_runs", "get_autograder_log", "list_repo_commits")


def build_starter_repo(course: str, code: str, language: str, solution_dir: str,
                       strip: list[str] | None = None, omit: list[str] | None = None,
                       register: bool = False, verify_100: bool = False,
                       dry_run: bool = True) -> str:
    """Build a student starter repository from a solved assignment.

    `language` picks the template — python-pytest, cpp-catch2, cpp-stdout, java-junit — which
    carries the test runner and the autograder workflow. `solution_dir` holds the working
    solution; `strip` names the symbols whose bodies are emptied for the student, and `omit`
    the files left out entirely.

    `verify_100` runs the autograder against the solution and refuses to ship a starter whose
    own solution does not score 100. `register` records the assignment in the org hub, which is
    what lets a student request the repo. Default is a dry run that reports the plan.
    """
    from .. import git_starter_build

    argv = ["--course", course, "--code", code, "--lang", language]
    if solution_dir:
        argv += ["--solution-dir", solution_dir]
    for symbol in strip or []:
        argv += ["--strip", symbol]
    for path in omit or []:
        argv += ["--omit", path]
    if register:
        argv.append("--register")
    if verify_100:
        argv.append("--verify-100")
    if dry_run:
        argv.append("--dry-run")

    out, err = io.StringIO(), io.StringIO()
    saved, sys.argv = sys.argv, ["build_starter_repo"] + argv
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code_returned = git_starter_build.main()
    finally:
        sys.argv = saved
    header = "DRY RUN — nothing was pushed.\n" if dry_run else ""
    return f"{header}exit {code_returned}\n{(out.getvalue() + err.getvalue()).strip()}"


def _gh_token(course: str) -> str:
    org = _ctx.config(course).get("github_org")
    if not org:
        raise KeyError(f"the config for {course!r} has no github_org, so no repository can be "
                       "found for it")
    return get_token()


def list_autograder_runs(course: str, repo: str, branch: str | None = None) -> list[dict]:
    """The autograder runs on a student repository, newest first.

    `repo` is the full `owner/name`. A run's conclusion is the score's evidence — the code as it
    stands now is not, because the run is what the deadline saw.
    """
    return [
        {"id": r.get("id"), "conclusion": r.get("conclusion"), "status": r.get("status"),
         "created_at": r.get("created_at"), "head_sha": r.get("head_sha")}
        for r in actions.list_runs(_gh_token(course), repo, branch=branch) or []
    ]


def get_autograder_log(course: str, repo: str, run_id: int, cache_path: str) -> str:
    """The log of one autograder run — which tests passed, and what the failures said.

    `cache_path` is where the downloaded log is kept; logs are large and are read more than once.
    """
    return actions.get_run_log(_gh_token(course), repo, run_id, cache_path)


def list_repo_commits(course: str, repo: str) -> list[dict]:
    """A repository's commits: sha, author, date, message.

    The times are the SERVER's, which is why they can be graded against a deadline.
    """
    return [
        {"sha": (c.get("sha") or "")[:8],
         "author": ((c.get("commit") or {}).get("author") or {}).get("name"),
         "date": ((c.get("commit") or {}).get("author") or {}).get("date"),
         "message": ((c.get("commit") or {}).get("message") or "").splitlines()[:1]}
        for c in actions.list_commits(_gh_token(course), repo) or []
    ]


def register(server) -> None:
    for fn in (build_starter_repo, list_autograder_runs, get_autograder_log, list_repo_commits):
        server.add_tool(fn)
