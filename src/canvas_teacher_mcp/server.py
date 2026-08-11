"""The MCP server. It registers and holds no logic.

Each module in `servers/` wraps exactly one code package and declares what it registered in
`TOOLS`. `skills.register` runs last so it can check every skill's declared tools against what
actually exists.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from . import skills
from .servers import (announcements, assignments, builders, courses, github, grading, modules,
                      pages, quizzes, submissions, system)

INSTRUCTIONS = """\
Canvas authoring and grading for instructors.

Call the skill tools for methodology — they return the procedure to follow — then the execution
tools to carry it out. Pages and assignments are always created unpublished; the instructor
publishes.
"""

_MODULES = (system, courses, pages, modules, assignments, quizzes, announcements, submissions,
            builders, github, grading)


def build_server() -> MCPServer:
    server = MCPServer(name="canvas-teacher", instructions=INSTRUCTIONS)

    execution_tools: set[str] = set()
    for module in _MODULES:
        module.register(server)
        execution_tools.update(module.TOOLS)

    skills.register(server, execution_tools)
    return server
