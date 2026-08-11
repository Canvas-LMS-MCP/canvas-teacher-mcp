# canvas-teacher-mcp

An MCP server for Canvas LMS. Ask your assistant to read a course, build an assignment page, set
due dates or post an announcement — it calls the Canvas REST API for you.

**v0.1.0 — read and write course content. Grading is not in this release.**

## Install

Nothing to install. Point your MCP client at it and `uvx` fetches it on first run.

```json
{
  "mcpServers": {
    "canvas-teacher": {
      "command": "uvx",
      "args": ["canvas-teacher-mcp"],
      "env": { "CANVAS_LMS_ROOT": "/path/to/your/teaching/tree" }
    }
  }
}
```

Then say **"set up Canvas"**. `CANVAS_LMS_ROOT` is the one thing you choose — set it in `env` as
above, or leave it out and answer when setup asks.

## Setup — what the `setup` tool does

It runs in conversation: each call does one step and returns the next question. Nothing is
overwritten, so running it again is safe.

| Step | What happens |
|---|---|
| 1 | **Root.** Reads `CANVAS_LMS_ROOT`, or asks. Creates the tree and `Sqlite/`. |
| 2 | **Workflow.** Copies the working rules to `<ROOT>/.claude/CourseGlobalWorkflow/` — yours to edit. |
| 3 | **Skills.** Copies the page, quiz, announcement and notebook methods to `<ROOT>/.claude/skills/`. |
| 4 | **Post-gate.** Copies `post-gate.py` to `~/.claude/hooks/` (Claude Code), so no grade can be posted until you open the gate from a real terminal. |
| 5 | **School.** Writes `Canvas-Auth/<school>.json` from your Canvas URL, takes a token, or opens a browser login when your school issues none. Verifies the connection. |
| 6 | **Course.** Creates `<SCHOOL>/<ORG>/<COURSE>/` and its `course-config/<slug>.json` from the course URL. |

Steps 2 and 3 land in your tree, not in the package, so your edits survive an upgrade. Add another
school or course by asking again — only steps 5 and 6 repeat.

```
<ROOT>/
├─ .claude/
│  └─ Canvas-Auth/                    credentials
│     ├─ <school>.json                {base_url, token}
│     └─ storageState/<school>/       cookie schools only
└─ <SCHOOL>/<ORG>/<COURSE>/
   └─ .claude/
      ├─ course-config/<slug>.json    the course's coordinates
      ├─ input/                       material you bring in
      └─ output/<kind>/               everything the server writes
```

One school means one school folder. The shape does not change.

## Set up a course

Ask the assistant to add a course and give it the Canvas URL. It derives the rest, confirms once,
and caches five keys:

```json
{
  "canvas_url":   "https://school.instructure.com/courses/12345",
  "school":       "school",
  "db_path":      "$HOME/.../Sqlite/<COURSE>-<TERM>.db",
  "github_org":   "MY-ORG",
  "drive_folder": "1AbC..."
}
```

Only `canvas_url` is required. `course_id`, `base_url`, `domain` and the token env var are derived
from it, never stored.

## Authenticate

Two ways in, one REST API. The server picks whichever your school has.

| Your school | What you provide |
|---|---|
| issues API tokens | `<ROOT>/.claude/Canvas-Auth/<school>.json` = `{"base_url": "...", "token": "..."}`, or `$<SCHOOL>_CANVAS_TOKEN` |
| SSO only, no tokens | a one-time browser login; the session cookie is saved and refreshed automatically |

`chmod 600` the credential files, and keep `Canvas-Auth/` out of git.

## What it does

**Read**

- courses, modules and module items
- assignments, quizzes and their questions
- pages
- submissions, with attachments fetched and read (PDF, images, Office files, Colab notebooks)
- students, by Canvas uid
- every link and embed in a page, module, assignment or quiz

**Write**

- create and update assignments and pages
- add items to a module
- set due dates
- post an announcement — always previewed first, sent only when you say so

Everything is created **unpublished**. Publishing stays a manual instructor action.

## What it does not do

- **Post grades.** Grading needs safeguards this release does not ship. It is the next milestone.
- **Delete anything.** No endpoint in this server removes a course, an assignment or a submission.
- **Store your grades.** Canvas is the record.

## Notes it will save you

The Canvas API returns HTTP 200 for several calls that change nothing. This server sends the forms
Canvas actually accepts:

- a grade must be form-encoded; as JSON it returns 200 and sets nothing
- a quiz-question update needs the FULL payload, or it applies nothing
- `question_count` stays cached until the quiz is touched again
- `seconds_late_override` is ignored when sent with `late_policy_status`
- submission comments render HTML in SpeedGrader, but the API returns them flattened — the API
  response is not proof of what the student sees

## Requirements

Python 3.10+. `uvx` handles the rest. A cookie school also needs Playwright's Chrome, installed on
first login.

## License

MIT.
