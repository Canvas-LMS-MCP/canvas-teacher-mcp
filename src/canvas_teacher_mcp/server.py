"""The MCP server. It registers and holds no logic.

Each module in `servers/` wraps exactly one code package and declares what it registered in
`TOOLS`. `skills.register` runs last so it can check every skill's declared tools against what
actually exists.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from . import skills
from .canvas_root import ROOT_MISSING, RootNotSet, root
from .servers import (announcements, assignments, builders, courses, github, grading, modules,
                      pages, quizzes, submissions, system)

INSTRUCTIONS = """\
Canvas authoring and grading for instructors.

Call the skill tools for methodology — they return the procedure to follow — then the execution
tools to carry it out. Pages and assignments are always created unpublished; the instructor
publishes.

When no tool covers the endpoint you need, `canvas_api_request` calls Canvas directly. Nothing
here deletes.

Run `setup` first on a new install: it reports what is configured and what is still missing.
"""


def _instructions() -> str:
    """The connect-time text, assembled from what this install actually has.

    The root notice goes FIRST and only when there is no root: an assistant reads this before it
    has called anything, and a list of tools cannot say that none of them can work yet.
    """
    try:
        root()
    except RootNotSet:
        return ROOT_MISSING + "\n\n" + INSTRUCTIONS
    return INSTRUCTIONS

_MODULES = (system, courses, pages, modules, assignments, quizzes, announcements, submissions,
            builders, github, grading)


def _version() -> str:
    """The installed package's version, so a client can report what it is talking to."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("canvas-teacher-mcp")
    except PackageNotFoundError:      # running from a source checkout
        return "0+source"


def build_server() -> MCPServer:
    server = MCPServer(name="canvas-teacher", version=_version(), instructions=_instructions())

    execution_tools: set[str] = set()
    for module in _MODULES:
        module.register(server)
        execution_tools.update(module.TOOLS)

    skills.register(server, execution_tools)
    return server
