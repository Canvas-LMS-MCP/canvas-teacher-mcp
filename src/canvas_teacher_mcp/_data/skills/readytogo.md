---
name: readytogo
description: Generic session orientation. Loads account + course global rules and detects the active course from the current working directory. For project-specific orientation, run from inside a project dir — the per-course readytogo.md takes precedence over this one.
---

## ⛔ RULE #0 — 최우선. go 없이 행동 금지

**대화 중에는 절대 튀어나가서 바로 수정/실행하지 마라.**

- 사용자가 말하거나 질문하는 중에는 **말로만** 답한다. 툴 호출·파일 수정·코드 실행 금지.
- 명백한 오류를 발견해도, 대화 중이고 명시적 **"go"가 없으면** 바로 고치지 마라.
- 순서: **대화 마침 → 계획 제시 → 명시적 "go" 받음 → 그때 시행.**
- 이건 파일 생성뿐 아니라 **모든 행동**에 적용 (점수 수정, 코드 편집, 채점, POST 등 전부).
- 계정레벨 `~/.claude/CLAUDE.md` Rule #0와 동일 — 여기서도 최우선.


**항상 일 하면서 한줄 헤더 달아놓고 일해; 모 하고 있는지**
[Example] 너 
""" ▶ ① 컴파일 확인 + report_generator 총괄표도 같은 문제인지 확인 """
""" Another example """
▶ ② report_generator §4는 이미 정상(max=헤더). LabCh5P1 재작성 — comp 감점자 7명 노트북 다운받아 "어느 섹션 셀 미실행" 추출
=======================
---
[Inline coding prohibition]
⛔ RULE #0e — 채점 중 손코딩 절대 금지 (canonical 코드만)
----------------------------------------------------------------------------------------------------

# Ready to Go — Generic Orientation

This is the **global** readytogo. Inside a course-project directory (`<school>/<org>/<course>/`, `<school>/<org>/<course>/`, …) there is also a per-course `<project>/.claude/skills/readytogo.md`.

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
├── <school>/<org>/{<course>, <course>, <course>, <course>, <course>, <course>}/
├── <school>/<org>/{<course>}/
├── <school>/{<course>, <org>/<course>}/
└── VC/Ventura-CSV/{<course>, <course>}/
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
- <school>: <course>, <course>, <course>, <course>, <course>, <course>
- <school>: <course>
- <school>: <course>, <course>
- <school>: <course>, <course>

**Open items in GRADING.md** ([TBD] markers):
[grep output]

Ready. What are we working on?
```

---

## Canvas ops = Python (canvas_auth + canvas_core + grade_engine)

모든 Canvas 작업은 Python이다 — JS도 `run.sh`도 없다. 호출 형태는 `fn(session, course_id, …)`
(도메인은 세션 안). 인증(token vs cookie)은 token 존재로 파생 → `Access/CanvasAuth.md`.

- **로그인·세션** = `canvas_auth.session.CanvasSession(school)` (401 시 `canvas_auth.login` 자동 재로그인).
- **Canvas CRUD / 주간 모듈빌드** = `canvas_core.*` (`pages`/`modules`/`assignments`/…) · 코스별 `build_week_module.py`.
- **채점** = `grade_engine` (학교 불문 주입 없음 — `core._credential`이 토큰/세션 선택) → **POST** = `post_grades.py`.
- **마감일** = `canvas_core.assignments.set_due_dates`.
- **공지** = `canvas_core.announcements` — 발송은 함수 호출
  `send_announcement(CanvasSession(school), cid, title=T, message=M, confirm=SEND_CONFIRM)` (`Access/Canvas.md`).

어떤 코스에서 옛 `run.sh` orphan을 발견하면 그 자리에서 삭제.
