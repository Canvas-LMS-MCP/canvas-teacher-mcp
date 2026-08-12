---
name: readytogo
description: Generic session orientation. Loads account + course global rules and detects the active course from the current working directory. For project-specific orientation, run from inside a project dir — the per-course readytogo.md takes precedence over this one.
---

## ⛔ RULE #0 — act only after an explicit "go"

**While the instructor is talking, answer in words. Nothing else.**

- No tool call, no file edit, no code run, while a question is still open.
- An obvious error found mid-conversation is REPORTED, not fixed, until the "go" comes.
- The order is: finish the conversation → present the plan → receive an explicit "go" → act.
- This covers every action, not just writing files: editing a score, editing code, grading, posting.
- Same as `~/.claude/CLAUDE.md` Rule #0, and it outranks everything here too.

**Work under a one-line header saying what is being done right now.**

```
▶ 1  check it compiles, and whether report_generator's summary table has the same fault
▶ 2  report_generator §4 is already correct (max = header). Rewrite LabCh5P1 — pull the seven
     notebooks that lost completeness marks and extract which section was left unrun
```

## ⛔ RULE #0e — grading runs canonical code only

No inline script, no ad-hoc collect/score/render. Grading goes through `grade_skill.py`,
`report_generator`, `post_grades.py` and nothing else.

----------------------------------------------------------------------------------------------------

# Ready to Go — Generic Orientation

This is the **global** readytogo. Inside a course-project directory (`AVC/AVC-CS/CS120/`, `DVC/DVC-COMSC/COMSC140/`, …) there is also a per-course `<project>/.claude/skills/readytogo.md`.

⛔ **The per-course file EXTENDS this one — it does not replace it.** Run **this** file first (Step 0 + Step 1 below), then continue into the course file's local steps. A per-course readytogo must therefore start with a pointer here and **must NOT copy Step 0's list** — a copied list goes stale, and a session that reads only the course file skips the book entirely (that happened 2026-07-27: three READMEs unread → global knowledge re-invented locally).

If you're not in a project dir, this loads global rules + detects what course (if any) the cwd belongs to.

## Step 0 — ⛔ THE ROOT, before anything else

Every path in this book is relative to the tree root. Resolve it first — without it you cannot
even build the path of the next file you are told to read.

```
CANVAS_LMS_ROOT      the tree root
```

It is set in the `env` block of `.claude/settings.json`. Unset and undiscoverable ⇒ STOP and ask.
Never guess a root.

Layout under it: `CourseGlobalWorkflow/Where/CourseConfig.md`.

## Step 0b — ⛔ READ THE BOOK FIRST (mandatory, EVERY session)

Before anything else, read both entry-point READMEs — the map of the whole system.
**Skipping this is how a session hardcodes or duplicates what a canonical module already
provides** (e.g. a real wrong-school push because a builder re-invented config access).

```
$CANVAS_LMS_ROOT/.claude/CourseGlobalWorkflow/README.md   # START HERE — policy + system map + ◆ config source of truth
$CANVAS_LMS_ROOT/.claude/code/README.md                   # code layer map + ⛔ Rule #1: STUDY canonical modules before writing new code
```

Code RECIPES are no longer a separate book — each package carries its own
`playbook/` (`code/canvas_core/playbook/`, `code/netacad_via_playwright/playbook/`,
`code/grade_engine/playbook/`, cross-package `code/playbook/`). Check the relevant one before
implementing anything for the second time.

## Step 1 — Account + Course Globals (read in parallel)

Single source of truth for every course. Paths are relative to
`$CANVAS_LMS_ROOT/`.

```
~/CLAUDE.md                                          # account level
CLAUDE.md                                            # course-global index (the rule-file table)

.claude/CourseGlobalWorkflow/README.md               # system map

.claude/CourseGlobalWorkflow/Discipline/PolicyScope.md   # where policy may live at all
.claude/CourseGlobalWorkflow/Discipline/Writing.md       # how a policy file is written
.claude/CourseGlobalWorkflow/Discipline/Proof.md         # artifact, never prose

.claude/CourseGlobalWorkflow/Where/CourseConfig.md       # per-course coordinates + output layout
.claude/CourseGlobalWorkflow/Local/Paths.md              # `~` folding, multi-machine
.claude/CourseGlobalWorkflow/Where/Data.md               # source of truth + SQLite schema

.claude/CourseGlobalWorkflow/Access/Canvas.md            # Canvas API mechanics
.claude/CourseGlobalWorkflow/Access/CanvasAuth.md        # token resolve: env $<SCHOOL>_CANVAS_TOKEN → Canvas-Auth/*.json (match by base_url domain, flat token)
.claude/CourseGlobalWorkflow/Access/GitHub.md            # autograder · classroom.yml · Starter-Hub provisioning

.claude/CourseGlobalWorkflow/GRADING.md                  # grading policy
.claude/skills/grade/SKILL.md           # grading flow
.claude/CourseGlobalWorkflow/GradingEngine/              # 8 engine contracts — read the ones your task touches
```

⛔ This list and the table in `$CANVAS_LMS_ROOT/CLAUDE.md` must match the directory. Adding or
removing a rule file updates both in the same change.

## Step 2 — Detect course from cwd

```bash
pwd  # → identifies which project subdir we're in
```

Project locations:
```
$CANVAS_LMS_ROOT/
├── AVC/AVC-CS/{CS110, CS120, CS122, CS130, CS140, CS230}/
├── CoC/CoC-CMPSCI/{CMPSCI235}/
├── DVC/{COMSC-010NC, DVC-COMSC/COMSC140}/
└── VC/Ventura-CSV/{CSV09, CSV17}/
```

If cwd matches a project → read that project's `<project>/.claude/skills/readytogo.md` and continue from there.

## Step 3 — If outside any project

Present:
- Account rules (from `~/CLAUDE.md`)
- Available projects (the directory list above)
- Suggest: `cd` into the relevant project to load its full context.

## Step 4 — Active state (Course Globals)

```bash
# Open questions in GRADING.md (search for [TBD])
grep -n "TBD" "$CANVAS_LMS_ROOT/.claude/CourseGlobalWorkflow/GRADING.md" | head

# Recent working logs (per project)
find "$CANVAS_LMS_ROOT" -name "*working*log*" -type d 2>/dev/null
```

## Step 5 — Summary

```
### Session Context: Course_Globals (no specific project active)

**Cwd**: [pwd output]
**Detected project**: [project name or "none"]

**Active global rules**:
- GRADING.md (single grading policy)
- Access/Canvas.md (Canvas API mechanics; auth mode is derived from token presence)
- Discipline/Proof.md (artifact requirement per phase)
- GradingEngine/ (attachment + browser fetcher contracts)
- Where/Data.md (what we store vs read live)

**Available projects**:
- AVC: CS110, CS120, CS122, CS130, CS140, CS230
- CoC: CMPSCI235
- DVC: COMSC-010NC, COMSC140
- VCCCD: CSV09, CSV17

**Open items in GRADING.md** ([TBD] markers):
[grep output]

Ready. What are we working on?
```

---

## Canvas ops = Python (canvas_auth + canvas_core + grade_engine)

Every Canvas operation is Python — no JS, no `run.sh`. The call shape is `fn(session, course_id, …)`;
the domain lives inside the session. Token versus cookie is derived from whether a token exists →
`Access/CanvasAuth.md`.

- **login / session** = `canvas_auth.session.CanvasSession(school)`; a 401 triggers one
  `canvas_auth.login` and one retry.
- **Canvas CRUD, weekly module build** = `canvas_core.*` (`pages` / `modules` / `assignments` / …),
  plus each course's `build_week_module.py`.
- **grading** = `grade_engine`; no school is injected — `core._credential` picks token or session.
  **Posting** = `post_grades.py`.
- **due dates** = `canvas_core.assignments.set_due_dates`.
- **announcements** = `canvas_core.announcements`; sending is a function call,
  `send_announcement(CanvasSession(school), cid, title=T, message=M, confirm=SEND_CONFIRM)`
  (`Access/Canvas.md`).

An old `run.sh` orphan found in any course is deleted on sight.
