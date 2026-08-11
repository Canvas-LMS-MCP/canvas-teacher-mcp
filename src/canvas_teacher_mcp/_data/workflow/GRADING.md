# Grading policy

> ⛔ **Grading never posts.** Every run stops at save + report. Posting is a separate step the
> instructor commands. A `PreToolUse` hook blocks any grade or comment write until the instructor
> opens the post-gate from a real terminal (`date +%s > ~/.claude/.post-gate`, 20 min). Claude
> cannot open it. Non-grade Canvas writes are unaffected.

Order of operations → `skills/grade/SKILL.md`. This file is what is CORRECT: rubric, late,
comments, report. Both are required reading.

A course overrides this only through a `Grading override: <path>` line in its own `CLAUDE.md`;
the override names only what it changes.

Engine contracts stay in their own files — `GradingEngine/*`, `Where/Data.md`, `Access/*`.

---

# PART A — every assignment

## Entry

- Read the assignment page, and every quiz QUESTION, before running anything.
  `grade_skill.py --fetch-instructions` saves it and grades nothing.
- Look the answer up on the page before asking the instructor.
- Designate the type from what the page asks for. A sibling assignment is not evidence, and no
  designation means `general`, not a stop.
- Go back to the instructions whenever a run confuses you. Nearly every mid-run question is a
  requirement that was on the page.
- Say POST-READY only after the render succeeded — that is the whole definition. The render
  supplies every precondition the poster has (coordinates, view proof, reasons) or fails, so a
  dry-run rehearsal discovers nothing. A re-render is free: the view proof binds to the gather,
  not the conversation.

## The flow — any subject, any type

Download in full → deep-read → check against the rubric → per-item scores → per-item reasons →
total, save, report. The engine never refuses for want of a type; `general` runs this flow.

A grader earns its place only by reading a machine artifact a human would otherwise run —
autograder result, notebook cells, per-question quiz data. It supplies MECHANICS, never a rubric.

## Rubric

Grade on what the STUDENT SAW. The page is the contract; a number living only in a grader's source
was never shown to anyone and cannot justify a score.

| # | Source | When |
|---|---|---|
| 1 | `--rubric` from the instructor | whenever given — if the engine cannot consume it, STOP |
| 2 | the points TABLE on the assignment page | the student's contract |
| 3 | the Canvas rubric object | where a course attaches one |
| 4 | grader default | only when none of the above states a rubric |

- Match a page rubric on the TABLE, never on a heading phrase — `Rubric (50 points)`,
  `How it is graded`, `Grading`, or no heading at all.
- Reject a rubric whose items do not sum to `points_possible`; `core.grade()` refuses it.
- Grade a re-grade on the SAME rubric — §5.2 of the prior report. Never redesign mid-cycle.
- Fix the engine when a report shows different maxima than the page. Do not reopen the rubric.

## Read everything, in full

- Read every piece of student material to the last character. `[:N]`, `head`, `.head()`, `limit=`,
  "first N chars" — all forbidden while grading. Large content gets read in chunks.
- Open every surfaced artifact with the `Read` tool, at the ENGINE path
  (`/tmp/grade_engine_*/…`). A private re-download's path will not match the manifest and the post
  is blocked. Contract: `GradingEngine/ViewGate.md`.
- Never write "not viewed" as a deduction. Not viewing is the grader's omission.
- Read attachments only through `grade_engine.lib.attachments.read()`. `status == "stop"` or
  `AttachmentReadError` ⇒ the student is `🚨 NOT GRADED`, flagged, skipped entirely — no partial
  score, no comment, no PUT. Contract: `GradingEngine/Attachments.md`.

## Late

- Check `students.accommodation` and `late_waivers` before scoring.
- Waive per accommodation for DSP and EOPS students. An instructor may waive a whole assignment
  for everyone; record it in report §3.
- Two different late cases, never conflated:
  - **The submission is late** (`submitted_at > due_at`) ⇒ WHOLE-score penalty, applied by Canvas
    via `submission[late_policy_status]=late`. Never deduct by hand.
  - **On time but the commits ran past due** ⇒ the TEST item only, per Part B §2. Never apply the
    test-only tier to a submission that was itself late.
- Anchor a resubmission's late penalty to the FIRST submission
  (`submission_history[0]`) — a student is never penalized more for fixing their work. The caller
  passes `initial_submitted_at` to `late_policy.compute_late`.
- Skip a full re-read on a re-grade in ONE case: no new commit AND the elaboration is identical to
  what the prior round's record quotes ⇒ carry the prior score, and say so. Anything else — one
  commit, one sentence — read it in full. Skipping can never lower a score (the floor gate), but it
  can miss an uplift, which is the whole point of a re-grade. A student with no prior score is not
  a re-grade at all: floor 0, grade normally.

## Comments

- Print students in CANVAS order with the Canvas name string as-is. Never re-sort, never reformat
  a name, never omit a row — copy the Stage-A report's Section-1 table.
- Give every deduction a reason carrying WHAT was wrong, EVIDENCE quoted from the submission, and
  HOW TO FIX it. Re-verify you did not simply miss an attachment.
- Raise a flag instead of deducting when the reason cannot be written confidently.
- Keep waiver rationale, accommodation labels and internal adjustments OUT of the student comment.
  The student knows their own accommodation; naming it stigmatizes. Record waivers in report §3.
- Author the comment once, in Stage B, through `lib/comment_render` only. Fixed order: GREETING
  (name) → EVALUATION (rubric table + per-below-max reason) → CHEER (one dry line) → SIGNATURE.
  Instructor register — evidence, never threats, no exclamation spam.
- The engine emits FACTS only, under no comment-shaped field name. Four such drafts were built and
  read by nobody; a draft nobody reads is a second source of student-facing wording sitting beside
  the one path that enforces the reason gate.
- Post from the `comment` field alone. Absent ⇒ Stage B did not run ⇒ ABORT that record. A blocked
  post is recoverable; a posted reason-less comment is permanent.

## Report

Two files per session, one stem — report `grade_result/{Code}_grade.md`, record
`grade_result/json/{Code}_grade.json`. A re-submission round suffixes BOTH (`_2nd`, `_3rd`, …) via
`--round 2nd`, so each round keeps its own report and its own postable record. An error re-run
reuses the stem; the engine rolls the existing pair into a temp folder first.

The round travels as DATA — `scaffold()` stamps `"round"` from the Stage-A record and the render
names its output from it. `argv[1]` is an explicit override, not the mechanism.

Round-suffixed: `{Code}_stageA*` · `{Code}_grade*` · `{Code}_view_manifest*` ·
`{Code}_view_verified*` · the Stage-B authoring. Shared by every round: `{Code}_instructions.md` ·
`{Code}_ground_truth.json` · `json/{Code}_rounds.json` · `json/{Code}_posted_comments.json` ·
`{Code}_evidence/` (the next gather overwrites it, so an earlier round's basis survives only as
the quotes in its own record).

Record the rubric as a table — `Item | Max`, or `Item | Max | Criteria` once criteria are decided.
Never hardcode rubric items in a grader.

Five sections, every run:

| § | Holds |
|---|---|
| 1 | flags and anything needing instructor action before posting |
| 2 | the rubric used — the source of truth for a re-grade |
| 3 | late waivers applied, with their source, plus any blanket waiver |
| 4 | one row per student: per-item scores, raw, posted, late flag, reasons |
| 5 | the comments, human-readable |

## Who decides

- The engine produces a baseline from what it extracted, and never posts.
- Stage B (chat AI) is the final grader: it reads this file plus the type-specific part, does what
  the engine cannot — external content, semantic judgment — and authors the comment.
- Record a disagreement in the `ai_review` block; Stage B's score stands.
- Never score an item 0 because the engine skipped it. Gather the data with whatever tool reaches
  it, then score.
- Score genuinely inaccessible content per the type's inaccessible rule and tell the student how to
  fix the access. That is graded, not an engine gap.
---

## PART B — GitHub assignments

Applies on top of Part A when the assignment CODE appears in the Canvas instructions. No code on
the page means no repo lookup — grade it as a normal Canvas submission.

### Section 0. Finding the repo

Finding a student's repo is a solved problem. **"I can't find the repo" is never an outcome.**

- Deep-read the SUBMISSION first — the pasted link names their exact repo, and every other answer
  lives there too.
- Take the canonical repo from the org-hub log, matched by Canvas student email (name is the
  fallback).
- Reconcile the two: consistent ⇒ grade · differ ⇒ FLAG and read the submitted one · link but not
  in the log ⇒ FLAG unregistered · neither ⇒ 0 and Section 0.
- Never score 0 just because no link was pasted. The log is the source of truth and the repo is
  in it.

Algorithm, reconcile table and the batch-drain caveat: `GradingEngine/RepoResolution.md`.

### Section 1. Test result

Score the test rubric item in proportion to the autograder result — a 10-point item at 70/100
earns 7.0. Proportional scoring applies to that item only, never to the whole assignment.

### Section 2. Commit-late — the test item only

Scope: the submission was ON TIME but the code reached its passing state after the due date. A
late submission takes the whole-score Canvas penalty instead (Part A). The two never stack.

The ENGINE computes this — `graders/gh.py _commit_late_frac` on timestamps and a fixed table.
Stage B never does the time arithmetic; it keeps the semantic history judgment (§4).

Completion time = the `created_at` of the graded run. At or before due ⇒ no deduction.

| Late by | Assignments · labs | | Late by | Quizzes · exams |
|---|---|---|---|---|
| < 2 days | waive | | < 3 hours | waive |
| < 3 days | 10% | | < 12 hours | 10% |
| < 5 days | 20% | | < 24 hours | 20% |
| else | 30% | | < 48 hours | 40% |
| | | | else | 50% |

Each quiz attempt is judged at its own submission time (Part D).

**Which run is read** (`_decide_as_of`): on time ⇒ the latest run, so an eventual pass still
counts · late ⇒ the run as of submission time · a quiz attempt ⇒ the run as of that attempt.

**Waivers are separate data, never the tier.** The tier is a fixed global rule. Who is forgiven is
decided per run and per student, first hit wins: `late_waivers` rows, then the accommodation table
(DSP/EOPS ⇒ 7 days), then `--grace-days` on the run. Quizzes and exams force 0 regardless.

**[TBD]** whether a waiver also reduces the commit-late tier. Today the engine applies the tier on
raw timestamps and waivers act only on the whole-submission late path.

### Section 3. Failing tests

Read the student's code, the test code, the data file and the autograder log, then tell the
student WHY it failed in full technical detail and HOW to fix it — a concrete change or a concept
hint, never the full solution. This goes in their Canvas comment.

### Section 4. Commit History

Grade the history as evidence that this student developed this code. In a fully online course the
commit history IS the proctoring — it is the only substitute for watching someone work — so a
submission whose development is not visible in git is not accepted for full commit credit even
when the tests pass. Announce this in the assignment spec; it is policy, not a gotcha.

**The engine computes the verdict; Stage B decides the score.** Tiers, thresholds, diff
classification, the passing-commit analysis and the server-time authenticity check all live in
`GradingEngine/CommitAuthenticity.md`. Read the verdict there, never re-derive it, and never judge
a history from commit COUNT or commit MESSAGES alone — both are gameable and neither detects a
bulk dump.

**What earns full credit.** The passing algorithm visibly FAILED and was FIXED, or the student
backtracked out of a wrong approach. Clean forward assembly does not, however many commits it took.

**Carve-outs — check the assignment before applying any strict rule.**

- Accept a single clean commit on beginner work (early chapters of an intro course) and on labs or
  trivial assignments under ~10 lines.
- Apply the strict end only to exams and advanced assignments.

**Consequences, applied by Stage B.**

| Finding | Consequence |
|---|---|
| one-shot pass (`oneshot_bulk` / `oneshot_trivial`) | commit item capped at 50% on an assignment, 0-tier on a quiz or exam |
| not proctorable (`single` / `instant` / `backdated`) | commit item 0 on an EXAM or ADVANCED assignment, and the elaboration's errors-and-lessons component goes to 0 with the rest graded at the strict end — an undemonstrated error earns nothing |
| a passing history with no runtime-error fixes | cannot earn full commit marks; "it passed first try" on an advanced task must be PROVEN |
| the same student, single or instant commits across several assignments | flag for the instructor, record it, never silently pass it. Forward-only — posted grades stay posted |

The AUTOGRADER item stays objective throughout. Never zero a working program on suspicion; proven
cheating is a separate instructor escalation.

**Watch notes.** Record a repeat pattern in SQLite `students.notes` as FACTS plus assignment codes,
never a conclusion. The engine re-surfaces every note in Stage-A Section 0 on every later grading
and marks it when the current run is also flagged, so the instructor sees the pattern beside the
new verdict. Never shown to the student.

### Section 4.1 The comment must be about THIS student's repository

A generic commit deduction is a defect — the student must never be able to say "you didn't look at
mine". Every commit-history or elaboration deduction carries:

- their commit COUNT and SHAPE — "2 commits: a 29-line bulk push, then one small fix"
- at least one of their own commit MESSAGES, quoted
- the concrete timing — spacing, or the repo-created-to-first-push gap
- what a proper history for THIS task would have looked like, in terms of their actual bug —
  "a commit when the merge dropped the tail elements, then another once the leftover loop fixed it"
- THE PASSING COMMIT, said out loud — when the autograder first went green and what that commit
  changed, in their own numbers. This is the one sentence that makes a commit deduction impossible
  to dismiss.

For an elaboration deduction, quote their own sentence and name exactly what is missing.

⛔ **Cite their FACTS, never the verdict.** `instant`, `paste`, `pre-written`, `not proctorable`,
"fabricated", "suspect" are instructor-only words. The student comment states the process
requirement and their visible data; the judgment stays in the report.

### Section 4.2 Elaboration authenticity

- Grade the write-up as technique, not word-count: the invariant, the exact mechanism, why it is
  correct per input class, the real errors. Generic prose and spec restatement earn little.
- Treat errors described in the write-up but absent from the commits as the strongest copy signal.
- Read the RAW markup, not the stripped text — the engine hands Stage B
  `review_content.elaboration_raw_html` (git) / `answer_raw_html` (quiz). Inline code tokens
  rendered as `<span style="color…;font-family…">` come from a rendered-markdown source; typing
  directly into Canvas essentially never produces them. Read the span in context; a count proves
  nothing.
- Treat paste markup as a SIGNAL, never a verdict — it shows "pasted from a rendered source", not
  misconduct. The copy read stands only when the markup combines with an elab-commit mismatch,
  generic voice, or a server-time flag.
- Dock on the legitimate ground (insufficient specific technique, unverified claims) and add a
  neutral double-check question. Never write an accusation.

### Section 5. GitHub Assignment Report (student comment)

### Section 5. The comment carries the reason

Post no deduction without its explanation. Cover whichever applied: which commit-history rule
triggered and what to do next time · the test failure cause and fix · which commit-late tier hit,
how many points it cost, and why.

---

## PART C — Colab / Jupyter notebooks

Applies on top of Part A when the submission is a Colab notebook. The engine gathers structured
evidence (`graders/nb.py` → `attachments.read()` + `nb_inspect`); Stage B scores it. Mechanics,
functions and thresholds: `GradingEngine/{Attachments,NbInspect}.md`. Order: `grade-nb`.

**Rubric keys: `link` · `comp` · `rev` · `refl`** — link and access, completeness, revision
history, reflection. Weights come from the assignment's own rubric (page ▶ Canvas ▶ default
20/30/30/20).

**Weigh process over result.** A clean pass with no error-fix history and one bulk pin is a red
flag, not full marks.

**Start from the MANIFEST** (`grade_engine/manifests/<code>.json`). It holds `exec_cells` (the
completeness denominator), `sections` (the expected pin count) and `expected_active_min` (the
time ramp's `E`). Missing ⇒ build it from the template FIRST
(`nb_inspect --build-manifest`) and confirm the counts with the instructor. Never hand-count.
`nb-homework-create` stores it at creation.

### What each item scores

**`link` — the submission format.** The instructed submission is a LIVE Colab share, shared as
Editor. Judge by the Drive mimeType: `application/vnd.google.colaboratory` is correct;
`application/x-ipynb+json` and `application/json` mean the student uploaded a raw `.ipynb` and
pasted its URL. Grade the WORK normally either way — it is real — but score the format: `link` = 0,
or deduct on `rev` when the rubric has no `link` item. Same for a Viewer-only share
(`capabilities.canEdit` false). Tell the student to open the TEMPLATE in Colab, work there, and
share as Editor. A `drive.google.com/file/d/…/view` link does not open as live Colab at all — that
is inaccessible, not a gradeable share.

**`comp` — cells the student actually EXECUTED**, from Colab's per-cell `metadata.executionInfo`,
over the manifest's `exec_cells`. A code cell with no `executionInfo` was never run — deduct.
Then refine with per-problem correctness: read each problem's answer region and judge whether the
answer is RIGHT, not merely run. A region that cannot be located is read by hand, never
auto-zeroed.

**`rev` — pinned revisions only** (`keepForever`). Auto-saves do not count. Compare the pinned
count against the manifest's `sections`; short ⇒ partial or zero. Pin NAMES are not exposed by the
Drive API, so count and timing are the evidence. Zero pins ⇒ 0.

**`refl` — a real takeaway plus a ROUGH sense of time.** A per-section breakdown is ideal but
never required, and never dock a genuine student on reflection FORM. The assignment page says
where it lives (Canvas body or a `## Reflection` cell) — read there. Substance decides: a real
takeaway and a rough time ⇒ full or near-full, a token line ⇒ partial, nothing ⇒ 0. When it lives
in the notebook, judge only student-AUTHORED markdown; the template diff keeps instructor text out.

### Effort and authenticity — the lever

Completeness is the core score. Effort comes from the executionInfo TIMESTAMPS, never from the
pin count — one pin does not mean no work, and the pin signal once mis-flagged real workers as
paste.

- `active_min` = the sum of cell-to-cell gaps, each capped at 5 minutes, so idle time is excluded.
- `burst_frac` = the fraction of gaps under 2 seconds. At or above 0.50 with at least 10 executed
  cells it flags paste / no-think, reported separately so one long gap cannot mask a majority burst.

**Time-plausibility ramp** — graduated, never a hard 0. `T = 0.4 × E` where `E` is the manifest's
`expected_active_min`. It fires ONLY when completion is at or above 80% AND `active_min < T`;
few cells done fast is honest incompleteness, already scored low, and is not ramped twice. Then
`F = min(1, active/T)`, `comp × (0.5 + 0.5F)` and `rev × (0.3 + 0.7F)`. No `E` in the manifest ⇒
the ramp is SKIPPED with a loud flag, never a fabricated threshold. Every constant is named in
`graders/nb.py` and surfaced in `review_content.params` so any grade stays explainable later.

The point is DIFFERENTIATION — keep diligent students high and open a real gap for low-effort work,
not to shave points off strong students for form. Same evidence pattern, same treatment.

### Inaccessible notebooks

Score `rev` 0, `refl` from whatever body text is visible, `comp` 0 when the ipynb itself cannot be
read and partial when only its metadata is. Tell the student: "I could not access your notebook —
please share the Colab as Editor, and resubmit if you would like the work re-evaluated." This is
graded with an access failure, not an engine STOP. The score posts.

### Recording the decision

Write Stage B's judgment into the record's `ai_review` block — `engine_score`, `alt_score`,
`verdict` (AGREE / DISAGREE), the per-item breakdown, the reasons, and `checked_at`. Stage B's
score is what posts.

---

## PART D — Canvas quizzes and exams

Applies on top of Part A, and Part B for any code question, whenever the assignment is a Canvas
quiz graded through `graders/quiz.py`. A quiz scores differently from an assignment.

### Per question, never a total

- Write a score into EVERY question (`quiz_submissions[][questions][<qid>][score]`). Canvas sums
  them; that sum is the quiz score.
- Never use `fudge_points`. It bypasses the question record and corrupts it. A wrong total means a
  wrong question score — fix that question.

### Every attempt, graded on its own

- Grade each attempt independently, like a separate assignment. Three attempts, three gradings.
- Return EVERY entry of `submission_history`. Collapsing to one attempt silently drops the rest.
- Never average or pick the best. Canvas applies the quiz's own aggregation policy; the grader
  only scores.
- Grade an essay question by AI logic review (Part A), a code question by autograder result and
  commit history (Part B).

### A code question is graded COMMIT-TIME

An attempt reflects what the student had pushed WHEN that attempt was submitted — an early attempt
never borrows credit from code pushed later. Per attempt, with `T` = that attempt's timestamp:

- Take the LAST autograder run created at or before `T`; its `totalPoints/maxPoints` scales the
  test item. No run at or before `T` ⇒ test score 0.
- Limit the commit history to commits authored at or before `T`.
- Apply the quiz HOURS commit-late tier (Part B) when that attempt's graded run is past due.

Engine: `gh._fetch_repo_data(as_of=T)`, called once per attempt by `quiz.py`.

### Exam strictness

On a quiz or exam the commit history IS the proctoring, so the bar is not "did they commit" but
"did the algorithm ever fail before it passed". A `oneshot_bulk` or `oneshot_trivial` passing
commit ⇒ commit item 0 (an assignment caps at 50%), plus the elaboration ripple — an
"errors I fixed" narrative with no failing run behind it earns nothing. The autograder item stays
objective. State it in the comment as the student's own facts, never as an accusation (Part B).

### Posting

- Post per-attempt, per-question scores through `post_grades.py`. One poster, every school; the
  credential is derived (`Access/CanvasAuth.md`). It reads the same `entry["attempts"]` the engine
  emits.
- Post comments ONLY through the poster. Canvas comments are per-attempt and the poster sends
  `comment[attempt]`, which is what lets a re-run recognise its own earlier comment and skip it. A
  hand-PUT `comment[text_comment]` carries no attempt, so a later re-post cannot match it and
  duplicates — and Canvas comments cannot be deleted.


---

## PART E — JShell labs

The second kind of program homework: no repo, no starter, no autograder. The student practises in
JShell exactly as the slides show, saves the session, and explains. Three submitted items — the
`/save -history labN.txt` file, a screenshot of the results (the saved file holds no console
output), and the WHY answers from the instruction doc.

**50 points, entered as actual points.** Percentages belong to policy, never to the lab page.

| Part | Points | Earned by |
|---|---|---|
| Code practice | 30 | every DO item present in `/save -history` — each example statement typed, plus the required fixes, make-it-run and make-your-own tasks |
| Explanation | 15 | the WHY answers: answering at all, plus the quality of the error-and-lesson write-up |
| File submission | 5 | all-or-nothing — the `/save -history` file is there |

- Write instructions 1:1 with the grading. Every step is either a DO (counts toward the 30) or a
  WHY (counts toward the 15).
- Itemize the 30 per code-producing step in the rubric table (`step["pts"]` in `jshell_lab.py`,
  which asserts the sum). Weight harder steps more; a research step with no shell code carries no
  code points and its answer counts under Explanation. Keep the itemization in the DOC rubric only
  — the Canvas summary stays 30/15/5.
- Use the Explanation 15 as the soft-grading lever: when asked to be lenient, be generous there,
  tiered (5/4/2/0) on the quality portion.
- Designate the type with `--grader jshell`. The classifier slot in `core.py` is still a commented
  placeholder, so an undesignated run falls through to `general`.
- The grader gathers and scores nothing: `items` (the saved history), `images` (VIEW them),
  `reflection_text`, `file_present`, and `steps` when the lab has a manifest. Stage B assigns every
  point from the table above.
