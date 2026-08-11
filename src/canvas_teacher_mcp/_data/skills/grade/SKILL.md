---
name: grade
description: >
  GLOBAL step-by-step grading skill. The ONE ordered procedure for grading ANY course's
  Canvas assignment OR quiz/exam through the shared grade engine — Stage A (engine, no post)
  → Stage B (AI review in chat) → report → pre-post self-challenge → POST (instructor go +
  post-gate). Bundles the canonical policy (GRADING.md — Part D is the quiz/exam half), the
  flow (skills/grade/SKILL.md), the layer map (CourseGlobalWorkflow/README.md), and the engine
  contracts (GradingEngine/*) into one sequential runbook, and ships the runnable Stage-A
  driver `grade_skill.py`. Invoke BEFORE any grading work — never grade ad-hoc.
tools: [read_assignment_instructions, propose_rubric, run_stage_a, post_grades, list_submissions, classify_submissions]
---

# grade — the runbook

Run THIS to grade. Never hand-roll fetch / score / post.

**GRADING A QUIZ / EXAM?** Read `GRADING.md` **PART D** (scored per QUESTION, never
`fudge_points`) and `CourseGlobalWorkflow/README.md` §*the same symmetry on the GRADING side*
(a quiz is 3 tiers: `graders/quiz.py` only ITERATES attempt × question and calls the SAME type
graders; a question carries its OWN published rubric, which outranks any grader default).
Everything else on this page applies to a quiz unchanged.
Policy → `GRADING.md` · Flow → `skills/grade/SKILL.md` · Engine contracts → `GradingEngine/*`.
This file is the ORDER. It does not re-explain them. Incident history → Appendix, bottom.

## THE LOOP (memorize)

```
READ instructions → RUBRIC from them → Stage A (--rubric) → READ evidence (Read tool)
→ judge → render → table → self-challenge → [go + gate] → POST
```

## 5 RULES THAT DECIDE PASS/RE-RUN

1. **READ FIRST.** The assignment page — every quiz QUESTION too — before the engine runs.
   `grade_skill.py … --fetch-instructions` writes `<code>_instructions.md`, grades nothing.
2. **RUBRIC = THE PAGE.** Pass it: `--rubric`. Engine default is never the answer.
3. **EVIDENCE = `Read` TOOL.** Batch several `Read` calls in ONE message. `cat`/`sed` leaves no
   record → the view-gate blocks the post. Same round-trips, so there is no speed argument.
4. **NEVER TRUNCATE (§0Z).** Full text, every screenshot VIEWED, at the ENGINE path.
5. **ENGINE + POLICY ONLY.** No new scripts. Missing capability → add it to the engine or ask.

Each is checked mechanically later. Skipping buys a re-run, never time.

## GATES — test, never ask

| Gate | Effect |
|---|---|
| post-gate | posting (even dry-run) blocked unless the instructor opened `~/.claude/.post-gate` from a real terminal. You cannot open it. |
| code-gate | no new `.py/.js/.sh`. Extend canonical code by Edit. |
| view-gate | post ABORTS if any manifest artifact was never `Read`. Contract: `GradingEngine/ViewGate.md`. |
| quote gate | `report_generator` refuses a render whose `evidence[item].quote` is not a real substring of the student's work. |
| comment gate | `comment_render` raises unless every below-max row has a reason + a `For full marks:` fix. |
| floor gate | the render refuses any student whose total falls below their Canvas `entered_score`. Override with `"allow_lower": true` + a reason. |

---

## 0. Identity

`course_config.load("<slug>")` — the ONE reader. Never open a config json, never hardcode
`course_id`/domain/org. Stored: `canvas_url, school, db_path, github_org, drive_folder`.
Derived: `canvas_base_url, course_id, domain, canvas_token_env, repo_prefix, output_dir`.
Config holds WHERE the course is, never HOW to grade it (no rubric, no type, no grace).

Transport: REST for every school; `core._credential` picks token or `CanvasSession`. No flags.

---

## 1. Step 0 — scope

- READ the assignment page (+ embedded docs). Take **RUBRIC**, **DUE**, and **CODE**.
  No local file is the ledger; Canvas is what exists.
- **CODE — copy it, never derive it.** It is the `assignment=` value in the page's repo-request
  link (`…/classroom/issues/new?template=request-<slug>.yml&assignment=A31`); no such link ⇒ not
  a git assignment. Then confirm it is a key in `<org>/classroom/config.json` →
  `courses.<slug>.assignments`. **Not a key ⇒ STOP** — the page is wrong, and grading on it
  searches `{repo_prefix}-{code}-*` for repos that cannot exist and silently scores everyone 0.
  Never type it from memory, never infer it from a title / filename / an earlier assignment.
- WHAT to grade = LIVE needs-grading queue: `submitted_at` set AND
  `workflow_state ∈ {submitted, pending_review}`. Never use score to detect ungraded.
- Print active waivers (`late_waivers` DB / accommodation / `--grace-days`) before scoring.

## 2. Step 1 — Stage A (engine, no post)

**FIRST, for a git assignment only — is the org-hub log current?** The log is a BATCH: `log-build`
(in `<org>/classroom-admin`) is its only writer and drains the pending request issues on a schedule
(05:00 PDT) or on demand. A repository provisioned after the last drain is **not in the log yet**.
One check per SESSION, never per student:

```
gh run list --repo <org>/classroom-admin --workflow=log-build --limit 1
```

Last successful drain **older than the newest submission you are about to grade** ⇒ run it once
(`gh workflow run log-build --repo <org>/classroom-admin`), then start. Otherwise skip — a backlog
older than the last drain is already covered, and draining per student re-creates the branch-head
contention the design removes. In practice: grading today's or last night's submissions ⇒ drain;
grading an older backlog ⇒ don't.

Skip this entirely for `nb`, `quiz`-essay and `general` work — nothing there reads the log.

```
cd "$CANVAS_LMS_ROOT/.claude/code"
python3 grade_skill.py <slug> <code> --canvas-id N --fetch-instructions   # read first, grades nothing
python3 grade_skill.py <slug> <code> --canvas-id N --grader gh --rubric r.json
python3 grade_skill.py <slug> <code> --only <uid>      # single-student gather
python3 grade_skill.py <slug> <code> --audit           # re-run on graded; _audit files only
```
Quiz: `--grader quiz --q-graders '{"Question 11":"gh"}'` (per-question). `--q-grader X` types
ALL questions — only for a uniform quiz. Omit ⇒ every question `general`.

Writes `grade_result/<code>_grade.md` + `grade_result/json/<code>_grade.json` +
`json/<code>_view_manifest.json` + `<code>_evidence/<uid>.txt`. Touches Canvas never.

## 3. Step 2 — Stage B (you, per student)

**0. FIRST, ALWAYS — build the skeleton with the engine, never by hand:**
```
python3 -m grade_engine.stage_b <out>/grade_result/json/<code>_stageA.json > <out>/grade_result/<code>_authoring.json
# re-grading only the commit row of an ALREADY-judged batch (keeps every other judgment):
python3 -m grade_engine.stage_b --merge-commit <code>_authoring.json json/<code>_stageA.json
```
This fills every MECHANICAL verdict — commit-quality tier, the passing commit, elab-vs-server
contradictions, authenticity flags — and leaves only judgment empty. Skipping it is not a
shortcut: `report_generator` refuses to render when the commit tier was not consulted
(`commit_gate`). Read `engine_notes` per student before scoring anything.

1. READ `<code>_instructions.md` — the bible. Grade against it, not a template.
2. READ every evidence file + every screenshot with the **`Read` tool**, in full.
3. **COMMIT ROW** — `commit_quality` is pre-filled with the engine tier. Content decides the row
   (`logic_fix` ≥1 ⇒ real debugging even if the edit is one character; `syntax_fix` only ⇒ the
   logic never failed; purely additive ⇒ one-shot shape), and commits closer than 1 min to each
   other are NOT counted, so a burst of micro-commits buys nothing. Award ABOVE the tier only
   with a written reason — that is allowed and expected (a student who debugs locally looks
   identical to a copier in the diff; only the write-up separates them) and it is recorded as
   `commit_vs_engine`. **Commit COUNT alone proves nothing**, and neither does "the autograder
   was red" — an unfinished program is red too, so a history that never deletes a line never
   repaired anything.
3a. **⚠ THE AMBIGUOUS CASE — `elab_commit_match` (REQUIRED when the row is `assembly`).**
   The commits show only additions, but the write-up describes real debugging. This is neither
   full marks nor the floor, and the render REFUSES until you decide:
   | value | meaning | score |
   |---|---|---|
   | `corroborated` | the errors described are visible in the commits | **full marks** — nothing beats this, the two records agree |
   | `claimed_only` | described but not visible in the history | **−1** if the write-up quotes what only a real run produces (exception text, the actual wrong output) · **−2** if it is general debugging talk |
   | `absent` | no error account at all | engine tier stands |
   For `claimed_only` the comment ADVISES, never accuses: *"your write-up reads like real
   debugging, but the history does not show it — commit the broken state first, then the fix,
   and the two will back each other up."* A student who debugged locally is credited; a student
   who only WROTE about it does not score the same as one whose history proves it.
4. **PASS COMMIT** (`review_content.pass_commit`): `oneshot_bulk` / `oneshot_trivial` ⇒ commit
   item ≤50% (assignment) or 0-tier (quiz/exam). Say in the comment when it passed and what that
   commit changed.
5. Server-time authenticity (`authenticity.flags`) — instructor-only, never student-facing.
6. Score each item from evidence; below-max ⇒ specific reason + `For full marks:` fix +
   `evidence[item].quote` (verbatim).
7. Elaboration/write-up: build the manifest from the instruction, compare, differentiate hard —
   spec restatement ≠ algorithm.
8. Comment ONLY via `lib/comment_render`. Record DISAGREE in `ai_review`; never auto-overwrite.

## 4. Step 3 — render + show

```
python3 -m grade_engine.report_generator <authoring.json> <out>/<code>_grade.md
```
Then print ONE per-student table in chat (student | uid | item scores | total | flags) and wait.

**POST-READY = this command succeeded. Nothing else** (GRADING §RULE #0P). Do not say the word
after a render you have not run, and do not add a dry-run to "confirm" it — the render supplies
every precondition the poster has (coordinates from Stage A, view-gate proof, reasons) or fails.
A rehearsal that finds something the render missed is a bug in the render; fix it there.

**A re-render is free.** The view proof binds to the gather (`run_id`), so re-rendering to fix a
sentence never costs the reading again. Re-running **Stage A** does void it — that is new material.

**Naming — one stem, two homes.** report `grade_result/<code>_grade.md`, record
`grade_result/json/<code>_grade.json`, manifest beside the record. Overwrite the stem; never a
date. Resubmission round only → `--round 2nd`.

**Re-grade checklist:** `--round 2nd` · do NOT trust the Stage-A baseline (re-read the latest
attempt yourself) · `final = max(new, entered_score)` — the floor is on the skeleton, never from
an older round's file · late anchors to the FIRST submission · comment
attaches to the latest attempt and is not a duplicate.

**WHICH round number** — a SESSION counter, not a per-student submission count; read it off
`json/<code>_rounds.json` (or `ls json/<code>_grade*.json`) PER ASSIGNMENT: base only → `2nd`;
`_2nd` there → `3rd`. `_audit` is not a round. Full rule + which artifacts carry the suffix:
`skills/grade/SKILL.md` REPORT FILE NAMING.

**Skipping a re-read** is allowed in ONE case: no new commit AND the elaboration is byte-identical
to the prior round's quotes → carry the prior score. Anything else, read it in full — the floor
gate stops you lowering a score, nothing stops you MISSING an uplift (GRADING §3.6).

⛔ **Need Stage-A shape? Read `<code>_stageA{round}.md/.json`, never `<code>_grade*`.** `_grade` is
written twice per round (Stage A draft → render final), so its shape is not stable; `_stageA` is
the archive nothing overwrites.

## 5. Step 4 — self-challenge (evidence, not yes/no)

RUBRIC matches the prior posted split · LATE per student in PDT · COMMITS read as diffs ·
TEST failures with root cause · CONSISTENCY with already-graded peers · every below-max row has a
reason · nothing touched beyond the assignment you were told to grade.

## 6. Step 5 — POST (instructor "go" + gate open)

```
python3 .claude/code/post_grades.py <record.json>            # DRY-RUN
python3 .claude/code/post_grades.py <record.json> --post
python3 .claude/code/post_grades.py <record.json> --post --fix   # replace MY OWN wrong comment
```
Poster is PURE TRANSIT: score / comment / late are DATA. Artifact
`QA_artifacts/<code>_grade-post_<ts>.json`, `result` derived from real HTTP statuses.

**Comments — two lines.** DUPLICATE = my comment already on THIS attempt → skip. DELETE = only my
own wrong comment on the same attempt, via `--fix` (id recorded in `<code>_posted_comments.json`).
Nothing else is ever deleted.

---

## 7. Repo resolution (gh)

Code in the instructions ⇒ GitHub assignment. `lib/repo_resolve.resolve_reconciled`: submitted
link vs org-hub log (`<org>/classroom-admin/log/*.json`, matched by Canvas email) → consistent
grade · differ FLAG · link-not-in-log FLAG unregistered · neither 0 + Section 0.
"Can't find the repo" is never an outcome. Detail: `GradingEngine/RepoResolution.md`.

## 8. Type dispatch

Type is DESIGNATED (`--grader`), never sniffed. No designation ⇒ `general`, said out loud in
Section 0. `general` can grade anything — but when a sub-skill matches it is MANDATORY.

| Submission | type | run |
|---|---|---|
| repo + autograder | `gh` | engine `graders/gh` (repo resolve first) |
| Colab/Jupyter notebook | `nb` | **`grade-nb`** (manifest check is its Step A0) |
| Canvas quiz | `quiz` | engine `graders/quiz` — per question × attempt; never `fudge_points` |
| anything else | `general` | engine gathers → Stage B scores |

A sub-skill runs INSIDE this spine; it never replaces Step 0 or the Stage-B rules.

## 9. Comment format

GREETING (name) → EVALUATION (full rubric + per-below-max WHAT/EVIDENCE/HOW-TO-FIX) → CHEER (one
dry line) → SIGNATURE. No waiver rationale, no accommodation labels, no internal adjustments.
Instructor register: show evidence, never threaten.

## 10. STOP vs quality-0

Engine STOP (`AttachmentReadError`, Canvas 5xx, selftest fail) → not graded, fix the cause, never
a 0. Quality-0 (private doc / dead link / unshared notebook) → 0 on that item + resubmit guidance.

## 11. Code this drives

Everything runs from `.claude/code/` — nothing lives in this skill dir.
`grade_engine/core.py` · `graders/{gh,nb,quiz,jshell,general}.py` ·
`lib/{attachments,repo_resolve,comment_render,commit_inspect,nb_inspect,late_policy,view_gate}.py` ·
`report_generator.py` · `grade_skill.py` · the poster · `canvas_rest` + `canvas_token_auth`.

---

# APPENDIX — why these rules exist (incidents; not procedure)

Read once. Nothing here is a step; every line is a rule above that was paid for.

- **2026-07-31 · shell instead of Read.** Six assignments' evidence was dumped with `cat` "to go
  faster". The view-gate counts `Read` calls, so all 70 files read as never-opened: 3 assignments
  posted, 6 blocked, full re-read required. Batched `Read` costs the same round-trips.
- **2026-07-30 · quiz typed without reading it.** A quiz was run `--q-grader gh` on the assumption
  that it matched the week's git assignments. Two of its four questions were text-only algorithm
  design (links explicitly not accepted). Entire Stage A discarded.
- **2026-07-30 · rubric default.** The page published 3/15/6/6; the engine's parser did not
  recognise the "Grading (30 points)" heading and fell back to 15/6/9. The AI should have read the
  page and passed `--rubric` — the parser is a convenience, not the source.
- **2026-07-30 · local file mistaken for the ledger.** A session read a leftover
  `input/<TERM>/asmt/week6.json` it had authored itself, found 7 assignments, and told the
  instructor the other six "do not exist". Absence in a local file is not absence in the course.
- **2026-07-21 · M3Q7.** The engine downloaded every drawing; the AI never opened them, docked ~9
  students for "drawing not re-VIEWED", and posted. → the view-gate exists.
- **2026-07-08 · commit count ≠ process.** Count-based commit scoring passed a solution that
  arrived whole and green on its first run. → server-time authenticity + the passing-commit check.
- **2026-06-24 · hand-built comments.** Plain-text comments bypassing `comment_render` reached 18
  students without a rubric table. → comments are rendered, never written.
- **2026-07-26/28 · config squatters.** `asmt_types`, `expected_late_grace_days`,
  `term_exceptions_path`, and `classify_assignment` all pre-declared HOW to grade from WHERE the
  course is. All deleted. Do not reintroduce a type sniffer in `grade_skill.py` either.
- **2026-07-29 · quiz repo resolution.** `quiz.py` called the old `resolve()` while assignments used
  `resolve_reconciled()`; a code question with no pasted link scored 0 though the org-hub log had
  the repo. One implementation, both tiers.

## See also
`GradingEngine/{ViewGate,CommitAuthenticity,RepoResolution,ReportGenerator,NbInspect,Attachments}.md` ·
`Discipline/Proof.md` ("no artifact = the phase did not happen") ·
per-course deltas: `<Course>/.claude/skills/grading/SKILL.md` (thin override only).
