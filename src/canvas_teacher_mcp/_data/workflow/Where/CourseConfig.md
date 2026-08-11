# CourseConfig — where everything lives

Set the tree root once, in `CANVAS_LMS_ROOT`. Every path below is relative to it, and no code
derives the root from its own file location.

```json
// .claude/settings.json
"env": { "CANVAS_LMS_ROOT": "~/path/to/the/tree" }
```

Write `~`, never an absolute home (`Local/Paths.md`); the code expands it. A distributed install
sets the same variable in its MCP client's `env` block.

```
<ROOT>/
├─ .claude/
│   ├─ CourseGlobalWorkflow/          policy
│   ├─ code/                          canonical code
│   └─ Canvas-Auth/                   credentials
├─ <SCHOOL>/<ORG>/<COURSE>/
│   └─ .claude/
│       ├─ course-config/<slug>.json  coordinates
│       ├─ input/                     material from outside
│       └─ output/<kind>/             everything a session writes
└─ Sqlite/<Course>-<Term>.db
```

One school means one school folder. The shape does not change.

- Keep coordinates at `<school>/<org>/<COURSE>/.claude/course-config/<slug>.json`.
- Store five keys: `canvas_url` (required) · `school` · `db_path` · `github_org` · `drive_folder`.
- Read through `course_config`. No private `open()`, no hardcoded `base_url` / `course_id` / `school`.
- Store `school` — it picks the credential, and domain → school has no inverse: a district hosts
  several colleges on one Canvas domain, so the domain cannot say which one this is.
  `course_config` returns `token_env`, never a secret → `Access/CanvasAuth.md`.
- Store nothing computable. `course_id` · `base_url` · `domain` · `token_env` · `output_dir` derive.
- Store one Drive parent. Read children via `pages_folder(slug)` / `slides_folder(slug)`; `None`
  means ask the user where to save.
- Raise on an unknown slug.
- Keep a value only if it answers "where is this course". Two courses sharing it ⇒ not config.

## From a Canvas URL

The URL is the whole input. Derive the rest, confirm once, then write the file.

```
https://<domain>/courses/<id>
   <domain>'s first label   → school, the Canvas-Auth label
   <id>                     → course_id
   GET /courses/<id>        → name, course_code
   course_code, lowercased  → slug
   → <ROOT>/<COURSE_CODE>/.claude/course-config/<slug>.json
```

- Propose the slug and the directory; the instructor overrides either. Never overwrite a config
  that exists.
- **Registration serves the tools, which take a slug. It is not a precondition for reaching a
  course.** Authentication is per SCHOOL, so `CanvasSession(<school>)` reaches any course on that
  domain, registered or not. Register a course that will be worked on repeatedly; reach a one-off
  directly by id.

## Output

- Write every artifact under `output_dir`, in a subfolder named for its KIND: `grade_result/` ·
  `Canvas-Pages/` · `quiz_build/` · `QA_artifacts/` · `announcements/`.
- Name subfolders by kind, never by assignment — the file name carries that (`Canvas-Pages/FP.json`).
- **out → in → out.** A builder's source JSON is an output: same folder, same stem as what it
  renders (`Canvas-Pages/FP.json` → `Canvas-Pages/FP.html`).
- Put only outside material in `.claude/input/` — the college's roster, the instructor's `input.txt`.
  Anything a session authored is an output.
