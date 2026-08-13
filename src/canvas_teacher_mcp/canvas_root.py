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


class RootNotSet(RuntimeError):
    """CANVAS_LMS_ROOT is absent, and the code is not running from inside a tree."""


# Said to the ASSISTANT, not to the user: which file to edit differs per client, and the assistant
# knows which client it is while this process does not. So the requirement is declared here and
# carried out there — the same shape as a Canvas token, which is named rather than asked for.
ROOT_MISSING = """\
NO ROOT IS CONFIGURED. Every Canvas tool here needs one, so this is the first thing to fix.

Add CANVAS_LMS_ROOT to THIS client's own declaration of the canvas-teacher server — the folder
the instructor's courses live in (ask them; `~/Teaching` is a reasonable suggestion):

    "env": { "CANVAS_LMS_ROOT": "~/Teaching" }

The file is the client's, not this server's:

    Claude Desktop   ~/Library/Application Support/Claude/claude_desktop_config.json
    Claude Code      .mcp.json in the project, or ~/.claude.json
    Codex            ~/.codex/config.toml
    VS Code          .vscode/mcp.json
    Cursor           ~/.cursor/mcp.json

Codex is TOML rather than JSON, and its environment is a table of its own — the one form that
does not follow from the JSON above:

    [mcp_servers.canvas-teacher.env]
    CANVAS_LMS_ROOT = "~/Teaching"

Add the one key inside the existing canvas-teacher entry. Do not rewrite the file — the other
servers declared in it belong to the instructor.

If you can edit files, do it and then tell the instructor to restart this client: the environment
is fixed when the server process starts, so the change takes effect on the next start and not
before. If you cannot edit files, give them the file path and the exact line to add.

The root is recorded nowhere else. This server keeps no root of its own, so the config the
instructor can see is the only answer."""


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
    """The tree root: the environment, else the tree this file sits in.

    Two sources, and the second only ever answers for code running from inside a tree. There is
    deliberately no third — a server that records a root of its own would hold state its user
    cannot see in the config they wrote, and the two would drift.

    Raises RootNotSet rather than guessing — a wrong root silently reads the wrong course's
    credentials, and there is no safe default.
    """
    env = os.environ.get("CANVAS_LMS_ROOT")
    if env:
        return Path(env).expanduser()
    here = _root_above(Path(__file__).resolve().parent)
    if here:
        return here
    raise RootNotSet(
        "CANVAS_LMS_ROOT is not set. Put it in the env block of .claude/settings.json, "
        "or of your MCP client's server declaration, and restart the client."
    )


def auth_dir() -> Path:
    """Per-school Canvas credentials. One file per school: <school>.json = {base_url, token}.

    Cookies are not here — canvas_auth owns them, under storageState/<school>/.
    """
    return root() / ".claude" / "Canvas-Auth"
