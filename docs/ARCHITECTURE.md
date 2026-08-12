# Architecture

One install works at any Canvas-hosted institution, whether or not it issues API tokens. The
instructor talks to an assistant; the assistant calls these tools; the tools handle Canvas and
authentication.

It runs **locally**. `uvx` downloads the package and starts it as a process on your machine, so
your token never leaves it and a browser login opens on your own screen.

## Layers

```
assistant → server.py        MCP protocol: mounts the sub-servers below
              ↓
            servers/         one module per code package
              ↓
            core/            pages · modules · module_items · assignments ·
                             assignment_groups · announcements · links
              ↓
            rest/            one REST client: get/put/post, resources,
                             submissions, files. Knows no credential.
              ↓
            auth/            token, else cookie. The one place that decides.
              ↓
            Canvas /api/v1
```

Each layer knows only the one below it.

- `core/` shapes Canvas objects and knows nothing about credentials.
- `rest/` accepts **either** a token string or a session object, so no caller ever branches on
  which school this is.
- `auth/` picks one. A token in `Canvas-Auth/<school>.json` or `$<SCHOOL>_CANVAS_TOKEN` means token
  mode; otherwise cookie mode.
- `config.py` answers where a course is — see `configuration.md`.

## Server layout

`server.py` registers and holds no logic.

```
server.py          registration only
├─ servers/        pages · modules · assignments · quizzes · announcements ·
│                  submissions · grading · system
└─ skills.py       scans the skill documents, registers one tool per skill
cli.py             stdio entry point
```

Each `servers/` module exposes `register(server)` and names what it registered in `TOOLS`.
The SDK has no sub-server mounting, so composition is those calls; the file boundary and the
one-package-per-module rule are unchanged. `skills.register` runs last, because it checks
skills against the tool names the other modules just registered.

A sub-server wraps exactly one code package, so a tool's prefix names the module behind it —
`quizzes_build` is `quiz/quiz_builder.py`. Grouping by verb was rejected: `get_page`,
`create_page` and `build_agenda` all reach `core/pages`, and splitting them across a read file,
a write file and a build file cuts every package in three. Grouping by package also lets
`servers/grading.py` detach into its own repository without touching anything else.

Dependency runs one way. `skills.py` reads the tool names `servers/` registered; `servers/`
knows nothing about skills.

## Skills

A skill is a methodology document. Its tool returns the document body and executes nothing — a
skill that ran the work itself would bypass the model's judgement, the same line `run_python` is
refused for.

Skills are model-controlled tools rather than resources because only a tool's description reaches
the model automatically. A resource is application-controlled: nothing would tell the assistant
the methodology exists.

A skill binds to code by name. Each `SKILL.md` declares the tools its procedure calls:

```yaml
---
name: quiz-builder
description: GLOBAL methodology for building/updating a Canvas CLASSIC quiz …
tools: [quizzes_get, quizzes_create, quizzes_update_question, quizzes_build, quizzes_finalize]
---
```

At startup `skills.py` checks every declared name against the registered tools. **An unknown name
stops the server.** A skill still pointing at code that no longer exists is caught on the next
start instead of during a class.

Skill bodies name tools, never shell commands — a client without a shell cannot run `python3 x.py`.

## Where skills and the workflow live

They ship inside the wheel, under `_data/`, and are read from there unless the course root has
its own copy.

```
install dir   canvas_teacher_mcp/_data/{skills,workflow,hooks}     replaced on every update
course root   <ROOT>/.claude/{skills,CourseGlobalWorkflow}         survives, and wins when present
```

`_data/` is inside the package directory on purpose. Anything outside it needs a separate wheel
declaration and leaves the code choosing between a source-checkout path and an installed path —
two branches that drift. One path, computed from `__file__`, works in both.

**Copying is opt-in, not part of setup.** The documents work from `_data/` as they are, so an
instructor who does not want to change the grading policy never copies anything. Copying exists
to make them editable: `_data/` is replaced on every version update, so an edit there is lost,
while an edit in the course root survives. `setup` says this rather than doing it.

The reason the copy has to exist at all is that these are not library data. They are the
instructor's own teaching method — late grace, rubric splits, comment tone — and those differ
per person.

Credentials are the opposite case: `Canvas-Auth/` never ships in any form, so a school must be
registered in the course root before any Canvas call works.

`workflow/` is `CourseGlobalWorkflow/` minus `Local/`. `get_doc(path)` serves a workflow file to a
client that has no filesystem.

## The root

Every path this server touches is relative to one directory, and that directory is the only thing
not derivable from anything else. `canvas_root.root()` resolves it, in this order:

| | Source | When it answers |
|---|---|---|
| 1 | `CANVAS_LMS_ROOT` in the environment | always, if set — the client's `env` block puts it there |
| 2 | the tree this file sits in | only from a source checkout: walk up for a `.claude/Canvas-Auth` directory |
| — | `RootNotSet` | otherwise |

**There is deliberately no third source.** An earlier design had the server record a root of its
own in `~/.canvas-teacher-mcp/root`, so that setup could accept one in conversation. That was
dropped: the root would then live somewhere the instructor never sees, in a file that disagrees
with the client config they did write. One visible source beats two, even at the cost of a
restart.

Which config file holds the `env` block differs per client, and the server cannot know which
client started it — but the assistant talking to you does. So the requirement is DECLARED rather
than solved: `canvas_root.ROOT_MISSING` names the key, the per-client file paths, and the restart,
and `server.py` puts it at the front of the connect-time instructions whenever no root resolves.
`setup` returns the same text. This is the shape a Canvas token already uses — the server names
the file to put the secret in rather than asking for the secret.

Step 2 exists for development, where the code does sit inside a tree. It never fires for an
installed package, which lives in the installer's cache.

## Credentials

Token and cookie are two credentials on the **same REST API**, never two transports. There is no
second client and no `--cookie` flag.

| | |
|---|---|
| Token school | `Authorization: Bearer …` on every call |
| Cookie school | a browser login once, then the session cookie plus CSRF on every call |

The choice is DERIVED from whether a token is present. Nothing records "this school uses cookies" —
a written-down mode goes stale the moment a school starts issuing tokens.

A cookie session refreshes itself: any HTTP 401 triggers one login and one retry. There is no
heartbeat and nothing to run by hand.

## Why Python

`playwright-python` covers the browser login without a second language, and the audience already
runs Python.

## See also

- `configuration.md` — where things live and how to declare the server
- `conventions.md` — what the server refuses to do, and why
