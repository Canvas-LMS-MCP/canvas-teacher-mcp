"""Grading tools.

Read the `grade` skill before calling any of this — the ORDER is the subject of that document,
and these tools are only its steps.

Posting is its own step, never the tail of grading: a run ends at save and report, the instructor
reads it, and only then is a post asked for. `post_grades` defaults to a dry run and refuses a
Stage-A file outright; its view-gate blocks a post whose surfaced evidence was never read.
"""

from __future__ import annotations

import contextlib
import io
import os

from ..grading import core

# `grade` is the SKILL's name — the methodology document. The tool that runs the engine is named
# apart from it, so a client sees both: the procedure to follow, and the step that executes it.
TOOLS = ("read_assignment_instructions", "propose_rubric", "run_stage_a", "post_grades")


def read_assignment_instructions(course: str, code: str) -> dict:
    """The assignment as the STUDENT saw it — description, rubric, due date, attachments.

    Grading is against what the student read, so this comes before any scoring.
    """
    return core.fetch_instructions(course, code)


def propose_rubric(course: str, code: str, grader: str | None = None) -> dict:
    """The rubric the engine reads for this assignment, for the instructor to approve.

    Priority is the instruction sheet first, then the Canvas rubric object, then the default —
    a proposal, never an applied decision.
    """
    return core.propose_rubric(course, code, grader_override=grader)


def run_stage_a(course: str, code: str, rubric: dict | None = None) -> dict:
    """Run Stage A: collect every submission, score what a machine can, and save the artifacts.

    Returns the engine's result — per-student scores and the evidence it surfaced. It posts
    nothing and it writes no comment; the wording is Stage B's, done in conversation, and the
    post is a separate authorised step.
    """
    return core.grade(course, code, rubric=rubric)


def post_grades(grades_json: str, dry_run: bool = True, fix: bool = False) -> str:
    """Write the rendered grades and comments to Canvas. Its own step, asked for on its own.

    `grades_json` is the POST-READY file the report render produced — a Stage-A file is refused.
    The default is a dry run that reports what would be written; pass `dry_run=false` to write.
    `fix` is for correcting an earlier mis-grade: it is the only mode that deletes a comment, and
    only the one this poster recorded for the current attempt.

    A post aborts when any evidence the engine surfaced was never read.
    """
    from .. import post_grades as poster

    blocked = _view_gate_unavailable()
    if blocked and not dry_run:
        return blocked

    argv = [grades_json]
    if not dry_run:
        argv.append("--post")
    if fix:
        argv.append("--fix")

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = poster.main(argv)
    report = (out.getvalue() + err.getvalue()).strip()
    header = "DRY RUN — nothing was written.\n" if dry_run else ""
    return f"{header}exit {code}\n{report}"


def _view_gate_unavailable() -> str | None:
    """Why a post cannot go ahead here, said BEFORE it is attempted.

    The view gate proves the evidence was read by finding this session's Claude Code transcript
    under ~/.claude/projects. A client that keeps no such transcript — Claude Desktop, Codex —
    cannot satisfy it, so the gate fails closed and reports a missing transcript. That reads as a
    bug the instructor could fix, and it is not: on that client there is nothing to find. Name the
    condition instead, while a dry run still works and still shows what would be written.
    """
    if os.path.isdir(os.path.expanduser("~/.claude/projects")):
        return None
    return (
        "This client keeps no session transcript, so the view gate cannot confirm the evidence "
        "was read, and a post that skipped it would be a grade written from something nobody "
        "looked at.\n\n"
        "Posting grades runs in Claude Code, where the transcript exists. Everything up to the "
        "post works here: run_stage_a, the report, and post_grades with dry_run (the default), "
        "which shows exactly what would be written."
    )


def register(server) -> None:
    for fn in (read_assignment_instructions, propose_rubric, run_stage_a, post_grades):
        server.add_tool(fn)
