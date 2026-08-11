# Configuration

## Where the server declaration goes

An MCP client reads a server declaration, launches the server, and injects `env` into that
process. The declaration has the same shape everywhere; only the file differs.

| Client | File |
|---|---|
| Claude Desktop (macOS) | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Claude Code, this project | `<project>/.mcp.json` |
| Claude Code, everywhere | `~/.claude.json` |
| VS Code | `.vscode/mcp.json` |
| Cursor | `~/.cursor/mcp.json` |
| Zed | `~/.config/zed/settings.json` |

## The declaration

```json
{
  "mcpServers": {
    "canvas-teacher": {
      "command": "uvx",
      "args": ["canvas-teacher-mcp"],
      "env": { "CANVAS_LMS_ROOT": "/Users/you/Teaching" }
    }
  }
}
```

| Field | Meaning |
|---|---|
| name | what you call this server |
| `command` | what to run |
| `args` | its arguments |
| `env` | environment variables for that process |

Before the package is on PyPI, run it from git:

```json
"args": ["--from", "git+https://github.com/Canvas-LMS-MCP/canvas-teacher-mcp", "canvas-teacher-mcp"]
```

## First run

`uvx canvas-teacher-mcp` prints nothing and waits — it speaks the MCP protocol over stdio and is
started by your client, not by you. So setup happens in conversation:

> **you:** set up Canvas
> **assistant:** where should your teaching tree live?
> **you:** ~/Teaching
> **assistant:** which school, and what is your Canvas URL?
> …

The `setup` tool creates the directories, writes the credential file, tests the connection, and
adds your first course. Ask for it in whatever words you like.

## The root

| Source | Precedence |
|---|---|
| `CANVAS_LMS_ROOT` in the `env` block | **wins** |
| whatever `setup` recorded in `~/.canvas-teacher-mcp/root` | used when the env var is absent |

Setting `env` is the clearer of the two — the path is visible in the same file as the rest of the
declaration, and switching between two trees is one edit. Leave it out and `setup` will ask.

| Variable | Required | Holds |
|---|---|---|
| `CANVAS_LMS_ROOT` | no, but preferred | the tree root. Every other path is relative to it |
| `<SCHOOL>_CANVAS_TOKEN` | no | a Canvas API token, if you prefer the environment to a file |

The server reads `os.environ`. Where a value comes from — the `env` block, a shell export, a `.env`
file — is your choice, and the server neither knows nor cares.

## What lives under the root

```
<ROOT>/
├─ .claude/
│  └─ Canvas-Auth/
│     ├─ <school>.json                 {"base_url": "...", "token": "..."}
│     └─ storageState/<school>/        cookie schools: browser profile + cookies.json
├─ <SCHOOL>/<ORG>/<COURSE>/
│  └─ .claude/
│     ├─ course-config/<slug>.json     the course's coordinates
│     ├─ input/                        material you bring in
│     └─ output/<kind>/                everything the server writes
└─ Sqlite/<Course>-<Term>.db
```

`setup` creates this. No path is compiled into the server, and one school means one school folder —
the shape does not change.

`chmod 600` every file under `Canvas-Auth/`, and keep that directory out of git.
