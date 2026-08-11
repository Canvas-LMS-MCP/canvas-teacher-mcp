"""System tools — the workflow documents, and what the install still needs.

`get_doc` exists because a skill references `GRADING.md` and the page formats, and a client
with no filesystem has no other way in.
"""

from __future__ import annotations

from pathlib import Path

from ..canvas_root import root

TOOLS = ("get_doc", "setup")

# Shipped copy. Inside the package directory, so one path works from a source checkout and from
# an installed wheel alike.
_PACKAGE_WORKFLOW = Path(__file__).resolve().parent.parent / "_data" / "workflow"


def _workflow_dir() -> Path | None:
    try:
        tree = root() / ".claude" / "CourseGlobalWorkflow"
    except Exception:  # noqa: BLE001 — no root yet is a normal pre-setup state
        tree = None
    if tree is not None and tree.is_dir():
        return tree
    return _PACKAGE_WORKFLOW if _PACKAGE_WORKFLOW.is_dir() else None


def get_doc(path: str) -> str:
    """Read a workflow document, e.g. `GRADING.md` or `Access/Canvas.md`.

    `path` is relative to CourseGlobalWorkflow/.
    """
    base = _workflow_dir()
    if base is None:
        return "No workflow directory yet. Run `setup` first."
    target = (base / path).resolve()
    if not target.is_relative_to(base.resolve()):
        raise ValueError(f"{path} points outside the workflow directory")
    if not target.is_file():
        available = sorted(p.name for p in base.iterdir())
        return f"No such document: {path}. Top level holds: {', '.join(available)}"
    return target.read_text(encoding="utf-8")


def setup() -> str:
    """Report what this install has and what it still needs."""
    lines = []
    try:
        tree = root()
    except Exception as exc:  # noqa: BLE001 — the message is the answer
        return (
            "No course root yet. Skills and the workflow still work — they are read from the "
            "copy inside this package — but nothing can reach Canvas without a root. Set "
            "CANVAS_LMS_ROOT in this client's env block to the folder holding your courses, "
            f"then call setup again. ({exc})"
        )

    lines.append(f"course root: {tree}")
    for label, path in (
        ("skills", tree / ".claude" / "skills"),
        ("workflow", tree / ".claude" / "CourseGlobalWorkflow"),
        ("credentials", tree / ".claude" / "Canvas-Auth"),
    ):
        lines.append(f"{label}: {'in the course root' if path.is_dir() else 'not in the course root'}")

    lines.append("")
    lines.append(
        "Skills and the workflow are read from the course root when they are there, and from "
        "this package otherwise, so they work either way. Copy them into the course root only "
        "to CHANGE them — grading policy, late grace, rubric splits, comment tone. The packaged "
        "copy is replaced on every version update, so an edit made there is lost; an edit in the "
        "course root survives."
    )
    lines.append(
        "Credentials are different: Canvas-Auth/ never ships, so a school has to be registered "
        "in the course root before any Canvas call works."
    )
    return "\n".join(lines)


def register(server) -> None:
    server.add_tool(get_doc)
    server.add_tool(setup)
