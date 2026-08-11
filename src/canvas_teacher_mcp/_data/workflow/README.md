# CourseGlobalWorkflow — START HERE

Policy lives here, in four categories. Code lives in `code/`; read `code/README.md` for its map.

| Category | Answers |
|---|---|
| `Discipline/` | how the assistant works, and what counts as proof |
| `Where/` | where a thing lives |
| `Access/` | how an outside system is called |
| `GRADING.md` + `GradingEngine/` | how a submission is scored |
| `Local/` | this installation only — never generalize from it |

A code RECIPE is not policy and is not here. Each package carries its own `playbook/`
(`code/canvas_core/playbook/`, `code/netacad_via_playwright/playbook/`,
`code/grade_engine/playbook/`, cross-package `code/playbook/`).

## The three layers — never mix them

| Layer | Who | Job |
|---|---|---|
| **Conductor** (local, `<course>/.claude/skills/`) | `git-assignment`, `nb-assignment` | orchestrate ONE type's build, read the course config, call a builder |
| **Builder** (global, `.claude/skills/` + `code/canvas_core/`) | `git_page`, `nb_page`, `quiz_builder`, the page skeleton | make the artifact; course-agnostic |
| **Policy + config** (referenced) | this directory, `*-format.md`, `<slug>.json` | READ, never copied into code |

Anything git is conducted by `git-assignment`. `quiz-builder` is a delivery machine and a
native-question builder — never a conductor, and it holds no local information.

## A quiz question IS an assignment

One grader implementation; a quiz just iterates over it.

```
core.py            class-wide: student loop · pre-pass · late/waivers · report
                   grade(submission, asmt, course, **kw) → {raw, review_content, scores, [attempts]}
   ├─ ASSIGNMENT   type grader (gh · nb · general) scores one item          → 2 tiers
   └─ QUIZ         graders/quiz.py ITERATES attempt × question, scores
                   nothing, wraps each question as a one-off asmt with its
                   own published rubric, and calls the SAME graders          → 3 tiers
```

- Keep scoring logic OUT of `graders/quiz.py`. A question needing something a grader lacks means
  that grader gains it — never a private copy.
- Let a quiz question carry its own published rubric; the rubric the student saw outranks any
  grader default.
- DESIGNATE the type. No designation means `general`, said out loud in Section 0. Never sniff a
  description for keywords — that decides the type before anyone has seen the submission.
- Expose `prepare()` when a grader needs a class-wide pre-pass (`gh` resolves every repo in one
  batch). `core.py` calls it when present and names no grader type.

## Directory shape

```
<ROOT>/
├─ .claude/
│  ├─ CourseGlobalWorkflow/   policy (this dir)
│  ├─ code/                   canonical code — see code/README.md
│  ├─ skills/                 global builders + methods
│  └─ Canvas-Auth/            credentials
├─ <SCHOOL>/<ORG>/<COURSE>/
│  └─ .claude/  skills/ (local conductors) · course-config/<slug>.json · input/ · output/<kind>/
└─ Sqlite/<Course>-<Term>.db
```

Full layout and the root variable: `Where/CourseConfig.md`.

## Building a git homework

```
/git-assignment <CODE> <spec>
  1  read the course config → coordinates
  2  read the spec → the problem
  3  repo: A00Starter → solution → T1–T4 tests
  4  GATE A  compile / run / tests, classroom.yml commands verbatim
  5  push solution (private + template) → GATE B  autograder green for that sha
  6  strip → push the Starter
  7  register it in the org-hub config.json
  8  git_page(course_slug, asmt) → format → gws-richdoc gdoc → skeleton HTML
  9  homework ⇒ push to Canvas · quiz ⇒ quiz-builder wraps the HTML as an essay
```

Gate artifacts: `skills/git-asmt-repo/SKILL.md`. Page formats:
`assignment-page-builder/{program,nb}-assignment-format.md`.

## One credential path for every school

Token and cookie are two credentials on the SAME REST call, never two transports.

- `canvas_rest` takes a token string OR a `CanvasSession`; `CanvasSession.headers()` is the one
  place the choice is made.
- Add no per-credential module and no `--cookie` flag — a second one is a duplicate by construction.
- Hand-build no `Authorization` or `Cookie` header.
- Let Canvas failures RAISE, 404 included. We assemble every URL from `course_config`, so a 404
  means our address is wrong; a silent `None` once surfaced as a bogus "no submissions".

Rules: `Access/CanvasAuth.md`. Mechanics: `Access/Canvas.md`.
