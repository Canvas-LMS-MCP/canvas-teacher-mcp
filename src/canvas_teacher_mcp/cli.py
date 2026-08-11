"""The `canvas-teacher-mcp` entry point. It speaks MCP over stdio and is started by a client,
so running it by hand prints nothing and waits — that is correct."""

from __future__ import annotations

from .server import build_server


def main() -> None:
    build_server().run("stdio")


if __name__ == "__main__":
    main()
