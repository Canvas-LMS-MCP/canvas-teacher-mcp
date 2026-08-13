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

To run a change that is not released yet, point at the repository instead:

```json
"args": ["--from", "git+https://github.com/Canvas-LMS-MCP/canvas-teacher-mcp", "canvas-teacher-mcp"]
```

`uvx` caches the list of released versions as well as the packages themselves, so a new release
can go unnoticed — and `uv cache clean <package>` clears the download, not the list. Put
`--refresh-package canvas-teacher-mcp` in front of the package name to have the check happen on
every start, or run it that way once when you want to update.

## First run

`uvx canvas-teacher-mcp` prints nothing and waits — it speaks the MCP protocol over stdio and is
started by your client, not by you. So setup happens in conversation:

> **you:** set up Canvas
> **assistant:** which school, and what is your Canvas URL?
> **you:** https://myschool.instructure.com
> …

The `setup` tool creates the directories, writes the credential file, tests the connection, and
adds your first course. Ask for it in whatever words you like.

The root is the one thing that has to be in place first — see below.

## The root

`CANVAS_LMS_ROOT` comes from the environment, and the `env` block above is how a client supplies
it. **There is no second place it can come from.** A server that recorded a root of its own would
hold state you cannot see in the file you wrote, and the two would drift; so it does not.

Connect without one and the server says so in its connect-time instructions, naming this file and
the key to add. Your assistant can often make the edit itself. Either way the environment is fixed
when the server process starts, so **restart the client afterwards** — in Claude Code, open a new
session.

Running from a source checkout is the one exception: code sitting inside a tree finds that tree by
walking up for a `.claude/Canvas-Auth` directory. An installed package sits in the installer's
cache and finds nothing, which is why the env block is the answer for everyone else.

| Variable | Required | Holds |
|---|---|---|
| `CANVAS_LMS_ROOT` | **yes** | the tree root. Every other path is relative to it |
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
├─ <SCHOOL>/<COURSE>/
│  └─ .claude/
│     ├─ course-config/<slug>.json     the course's coordinates
│     ├─ input/                        material you bring in
│     └─ output/<kind>/                everything the server writes
└─ Sqlite/<Course>-<Term>.db
```

`setup` creates this. No path is compiled into the server, and one school means one school folder —
the shape does not change.

`<SCHOOL>/<COURSE>` is what registration proposes. Levels between them are fine and nothing counts
them, so a school whose departments run separately can register with
`course_dir=<SCHOOL>/<DEPT>/<COURSE>` and keep it. The school belongs in the path either way: a
coordinate nobody can see is how work reaches the wrong course.

Credential files are written `0600`, and an existing world-readable one is corrected the next time
setup runs — you are not asked to do it. Keep `Canvas-Auth/` out of git: one token in a history is
a token to revoke.
