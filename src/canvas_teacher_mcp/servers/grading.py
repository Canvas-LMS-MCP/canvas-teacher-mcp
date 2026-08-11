"""Grading tools — Stage A only. Nothing here posts a grade.

Grading stops at save and report; posting is a separate step the instructor authorises, and on a
client with no hooks there is nothing to enforce that. So `post_grades` is deliberately NOT a
tool: a run ends with a report to read, and the instructor posts from a terminal.

Read the `grade` skill before calling any of this — the order is the subject of that document,
and these tools are only its Stage A half.
"""

from __future__ import annotations

from ..grading import core

# `grade` is the SKILL's name — the methodology document. The tool that runs the engine is named
# apart from it, so a client sees both: the procedure to follow, and the step that executes it.
TOOLS = ("read_assignment_instructions", "propose_rubric", "run_stage_a")


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


def register(server) -> None:
    for fn in (read_assignment_instructions, propose_rubric, run_stage_a):
        server.add_tool(fn)
