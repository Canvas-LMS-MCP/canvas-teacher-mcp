# canvas-teacher-mcp

An MCP server for Canvas LMS, from the instructor's side. Ask your assistant to read a course,
build an assignment page or a quiz, post an announcement, or run a grading pass — it calls Canvas
for you.

**v0.1.0.** Everything is created **unpublished** and nothing is ever deleted.

## Install

Point your MCP client at it. Nothing to install by hand — `uvx` fetches it on first run.

```json
{
  "mcpServers": {
    "canvas-teacher": {
      "command": "uvx",
      "args": [
        "--from", "git+https://github.com/Canvas-LMS-MCP/canvas-teacher-mcp",
        "canvas-teacher-mcp"
      ],
      "env": { "CANVAS_LMS_ROOT": "/absolute/path/to/your/teaching/folder" }
    }
  }
}
```

**Claude Desktop** — Settings → Developer → Edit Config opens the file. Add the entry inside the
existing `mcpServers` object rather than replacing it, then quit and reopen the app. A GUI app does
not inherit your shell `PATH`, so if the server does not appear, give the full path to `uvx`
(`which uvx` will tell you).

**Claude Code** — the same JSON in `.mcp.json` at your project root. Servers attach when a session
starts, so open a new one.

`CANVAS_LMS_ROOT` is the one thing you choose: the folder your courses live in. It is **required**
— the server keeps no root of its own, so this declaration is the only place it is written, and
you can always see what it is. Leave it out and the server says so on connect, telling your
assistant which file to add it to.

The folder need not exist yet; setup creates what it needs. An environment already exporting
`CANVAS_LMS_ROOT` works too — the server just reads the environment, and does not care how a
value got there.

## First run

Say **"set up Canvas"**. Setup answers one step at a time; you relay what it asks for.

```
you     set up Canvas
setup   course root: /Users/you/Teaching
        skills: read from this package
        workflow: read from this package
        schools: none registered

        Next: what is your Canvas address? e.g. https://myschool.instructure.com

you     https://myschool.instructure.com
setup   Created /Users/you/Teaching/.claude/Canvas-Auth/myschool.json

        Two ways to finish, and the first keeps the token out of this conversation:
          1. Open that file and paste the token into its empty "token" field,
             then ask me to run setup again — I will verify it.
          2. Tell me the token and I will store it. It will then live in this
             conversation's record as well as the file.

        The token comes from Canvas: Account -> Settings -> + New Access Token.
```

The file it made:

```json
{
  "base_url": "https://myschool.instructure.com/api/v1",
  "token": ""
}
```

Paste your token between those quotes, save, and say **"run setup again"**:

```
setup   schools: myschool
          myschool: signed in as Your Name
```

A token that Canvas rejects is never stored, and a token already stored is never overwritten.

**No token at your school?** Some run SSO only. Say so — the server opens a browser once, you log
in as usual, and the session is saved and refreshed from then on.

## Add a course

Give the assistant the course's Canvas URL.

```
you     add this course: https://myschool.instructure.com/courses/12345
setup   Registered Intro to Programming as slug 'cs101'.
        Config: /Users/you/Teaching/CS101/.claude/course-config/cs101.json
        School: myschool (guessed from the domain — say so if it is wrong)

        Tools now take course='cs101'.
```

It read the course's own name and code from Canvas; the slug and the folder are proposals. To put
it somewhere else, say so: *"add it under Fall2026/CS101"*.

The config is two lines, because the rest is derived:

```json
{
  "canvas_url": "https://myschool.instructure.com/courses/12345",
  "school": "myschool"
}
```

`course_id`, `base_url`, `domain` and the token variable all come from that URL. Add more only
when a feature needs it: `github_org` for GitHub assignments, `db_path` for grading records,
`drive_folder` for Google Docs, `output_dir` to write somewhere other than the default.

Registering is for convenience — it is what lets tools take `course='cs101'` instead of an id.
Authentication is per SCHOOL, so any course on that domain is reachable by id without registering.

## Where things end up

```
<ROOT>/
├─ .claude/
│  ├─ Canvas-Auth/<school>.json     your credentials — never leaves this machine
│  ├─ skills/                       (optional) the methods, if you copy them to edit
│  └─ CourseGlobalWorkflow/         (optional) the working rules, same
└─ CS101/
   └─ .claude/
      ├─ course-config/cs101.json   the course's coordinates
      ├─ input/                     material you bring in
      └─ output/<kind>/             everything the server writes
```

`chmod 600` your `Canvas-Auth/*.json`, and keep that folder out of git.

**Skills and the working rules need no copying.** They are read from inside the package and work as
they are. Copy them into your tree only when you want to CHANGE them — grading policy, late grace,
rubric splits, the tone of a comment. The packaged copies are replaced on every upgrade, so an edit
there is lost; an edit in your tree survives.

## What it does

**Read** — courses, modules and their items, assignments, quizzes and questions, pages,
submissions with their attachments fetched and read (PDF, images, Office files, notebooks),
students, and every link or embed inside a page, module or quiz.

**Write** — pages, modules, assignments, quizzes and their questions, due dates, module items.
An announcement is previewed first and sent only when you say so.

**Build** — a coding assignment page from a spec, a notebook assignment page, a weekly agenda, a
module overview, a formatted Google Doc, a quiz from a plain-text question bank, and a student
starter repository from a solved assignment.

**Grade** — read the assignment as the student saw it, propose the rubric, run the machine pass,
and post the result when you ask for that separately. A grading run stops at a report; posting is
its own step, defaults to a dry run, and refuses to post evidence that was never read.

**Anything else** — `canvas_api_request` calls any Canvas endpoint the tools above do not cover.

## What it will not do

- **Delete.** No tool removes a page, an assignment, a submission or a course, and the direct
  API call refuses DELETE.
- **Publish.** Everything is created unpublished. Publishing stays yours.
- **Run arbitrary code.** There is no shell here, and no `run_python`.

## Notes that will save you a morning

The Canvas API answers 200 to several calls that change nothing. This server sends the forms Canvas
actually accepts:

- a grade must be form-encoded; as JSON it returns 200 and sets nothing
- a quiz-question update needs the FULL payload, or it applies nothing
- `question_count` stays cached until the quiz is touched again
- `seconds_late_override` is ignored when sent with `late_policy_status`
- submission comments render HTML in SpeedGrader, but the API returns them flattened — the API
  response is not proof of what the student sees

## Requirements

Python 3.10+, which `uvx` provides. A school without API tokens also needs Playwright's Chrome,
installed on the first browser login. GitHub assignment tools need `git` and `gh`; Google Docs
need the `gws` CLI.

## License

MIT.
