"""System tools — the workflow documents, and what the install still needs.

`get_doc` exists because a skill references `GRADING.md` and the page formats, and a client
with no filesystem has no other way in.
"""

from __future__ import annotations

import json
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


def setup(canvas_url: str | None = None, token: str | None = None) -> str:
    """Set this install up, one step per call. Relay the answer to the instructor.

    Call with no arguments to see where things stand. Pass `canvas_url` to register a school —
    that writes the config with an empty token and reports the file to paste one into. Pass
    `token` as well only if the instructor prefers that; the token then goes through this
    conversation and stays in its record.
    """
    from ..auth import token as token_auth

    try:
        tree = root()
    except Exception as exc:  # noqa: BLE001 — the message is the answer
        return (
            "No course root yet. Skills and the workflow still work — they are read from the "
            "copy inside this package — but nothing can reach Canvas without a root. Set "
            "CANVAS_LMS_ROOT in this client's env block to the folder holding your courses, "
            f"then call setup again. ({exc})"
        )

    if canvas_url:
        return _register(token_auth, canvas_url, token)

    lines = [f"course root: {tree}"]
    for label, path in (
        ("skills", tree / ".claude" / "skills"),
        ("workflow", tree / ".claude" / "CourseGlobalWorkflow"),
    ):
        lines.append(f"{label}: {'in the course root' if path.is_dir() else 'read from this package'}")

    auth = tree / ".claude" / "Canvas-Auth"
    schools = sorted(p.stem for p in auth.glob("*.json")) if auth.is_dir() else []
    if not schools:
        lines += [
            "schools: none registered",
            "",
            "Next: ask the instructor for their Canvas address — the one they log in at, e.g. "
            "https://myschool.instructure.com — and call setup again with canvas_url set.",
        ]
        return "\n".join(lines)

    lines.append("schools: " + ", ".join(schools))
    for path in sorted(auth.glob("*.json")):
        # The file's own base_url, never a domain rebuilt from the filename — the filename is a
        # label, and a school on its own domain would not survive the round trip.
        try:
            cfg = json.loads(path.read_text())
            if not cfg.get("token"):
                lines.append(f"  {path.stem}: waiting for a token in {path}")
                continue
            identity = token_auth.whoami(cfg["base_url"], cfg["token"])
            lines.append(f"  {path.stem}: signed in as {identity.get('name')}")
        except Exception as exc:  # noqa: BLE001 — per-school status, not a failure of setup
            lines.append(f"  {path.stem}: not usable yet — {exc}")

    lines += [
        "",
        "Skills and the workflow work whether or not they are copied into the course root. "
        "Copy them only to CHANGE them: the packaged copy is replaced on every version update, "
        "so an edit there is lost, while an edit in the course root survives.",
    ]
    return "\n".join(lines)


def _register(token_auth, canvas_url: str, token: str | None) -> str:
    """One school, registered the way the instructor chose."""
    try:
        result = token_auth.register_school(canvas_url, token)
    except Exception as exc:  # noqa: BLE001 — a rejected token is the answer, not a crash
        return (
            f"That token was refused by {canvas_url}: {exc}\n"
            "Nothing was stored. Check it was copied whole, and that it has not expired."
        )

    path, status = result["path"], result["status"]

    if status == "registered":
        note = ""
        if token:
            note = ("\n\nNote: the token passed through this conversation, so it is in the "
                    "record. Revoke and re-issue it in Canvas if that matters.")
        return (
            f"Registered {result['base_url']} as {result.get('identity')}.\n"
            f"Stored in {path}.{note}\n\n"
            "Next: add a course. Give me the course's Canvas URL."
        )

    if status == "already_registered":
        return (
            f"{result['base_url']} is already registered in {path}.\n"
            "Nothing was changed. To replace the stored token, edit that file directly."
        )

    return (
        f"Created {path}.\n\n"
        "Two ways to finish, and the first keeps the token out of this conversation:\n"
        f"  1. Open that file and paste the token into its empty \"token\" field, then call "
        "setup again — I will verify it.\n"
        "  2. Tell me the token and I will store it. It will then live in this conversation's "
        "record as well as the file.\n\n"
        "The token comes from Canvas: Account -> Settings -> + New Access Token.\n"
        "If the environment already defines <SCHOOL>_CANVAS_TOKEN, that wins over this file."
    )


def register(server) -> None:
    server.add_tool(get_doc)
    server.add_tool(setup)
