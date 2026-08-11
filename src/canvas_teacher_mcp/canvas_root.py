"""The tree root — the one thing not derivable from anything else.

Every other path in this codebase is relative to it: credentials at
`.claude/Canvas-Auth/<school>.json`, course coordinates at
`<SCHOOL>/<ORG>/<COURSE>/.claude/course-config/<slug>.json`, artifacts under a course's
`output/<kind>/`, databases in `Sqlite/`.

It comes from the environment, never from a module's own file location. A module resolving the
root by walking up from `__file__` only works while the code sits inside the tree; installed as a
package it sits in the installer's cache and the walk lands somewhere unrelated.

Set it once, wherever the process gets its environment:

    .claude/settings.json      "env": {"CANVAS_LMS_ROOT": "~/…/Course_Globals"}
    an MCP client              the server declaration's "env" block
    a shell                    export CANVAS_LMS_ROOT=~/…

Write `~`, not an absolute home — this tree is mounted on more than one machine
(CourseGlobalWorkflow/Local/Paths.md). `root()` expands it.

Rule: CourseGlobalWorkflow/Where/CourseConfig.md.
"""
import os
from pathlib import Path

_FALLBACK_POINTER = Path.home() / ".canvas-teacher-mcp" / "root"


class RootNotSet(RuntimeError):
    """CANVAS_LMS_ROOT is absent and no setup has recorded one."""


def _root_above(start: Path):
    """The tree root found by walking up from `start`, or None.

    A root is a directory holding `.claude/Canvas-Auth`. Structural, not a name — so it works
    whatever the tree is called. Only ever true when the code is running from INSIDE a tree; an
    installed package sits in the installer's cache and this finds nothing.
    """
    for d in [start, *start.parents]:
        if (d / ".claude" / "Canvas-Auth").is_dir():
            return d
    return None


def root() -> Path:
    """The tree root. Environment wins, then a recorded pointer, then the tree this file sits in.

    Raises RootNotSet rather than guessing — a wrong root silently reads the wrong course's
    credentials, and there is no safe default.
    """
    env = os.environ.get("CANVAS_LMS_ROOT")
    if env:
        return Path(env).expanduser()
    if _FALLBACK_POINTER.exists():
        recorded = _FALLBACK_POINTER.read_text().strip()
        if recorded:
            return Path(recorded).expanduser()
    here = _root_above(Path(__file__).resolve().parent)
    if here:
        return here
    raise RootNotSet(
        "CANVAS_LMS_ROOT is not set. Put it in the env block of .claude/settings.json "
        "(or your MCP client's server declaration), or run setup."
    )


def auth_dir() -> Path:
    """Per-school Canvas credentials. One file per school: <school>.json = {base_url, token}.

    Cookies are not here — canvas_auth owns them, under storageState/<school>/.
    """
    return root() / ".claude" / "Canvas-Auth"


def record_root(path) -> Path:
    """Remember a root chosen interactively, for a process started without the env var."""
    p = Path(path).expanduser()
    _FALLBACK_POINTER.parent.mkdir(parents=True, exist_ok=True)
    _FALLBACK_POINTER.write_text(str(path))
    return p
