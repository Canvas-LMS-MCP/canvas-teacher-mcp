---
name: grade-git-program
description: "Grading SUB-SKILL for git-program assignments AND git-program quiz questions (the M-series coding items) — the type-specific plug-in of the global `grade` skill, analogous to `grade-nb`. ONE skill for both: internally a quiz question is graded STRICTER (quiz-exam-policy) and a homework LOOSER. Runs THROUGH THE ENGINE (core.grade → graders/gh) + GRADING Part B; reads the build-time grading info left by git-homework / quiz-builder. STATUS: STUB — full setup at first grading."
---

# grade-git-program — grade a git coding assignment / quiz question (SUB-SKILL of `grade`)

Type-specific plug-in for `grade`, like `grade-nb`. When a submission is a **git coding item** (a
git-homework assignment OR a git-program quiz question), `grade` dispatches HERE, then returns to the
general flow (report → self-challenge → POST). **ONE skill covers homework + quiz** (they are ~95%
identical): the only difference is STRICTNESS — a **quiz question** is graded at the strict end
(forbidden-function source check, exact-arrangement tests, a non-algorithm solution below half); a
**homework** is looser. The weights come from `GRADING.md`, or from the course's `Grading override:`
document when its `CLAUDE.md` declares one.

> **STATUS: PARTIAL** (first grading = M1QP1, 2026-07-08). Autograder(50) + commit-server-time
> authenticity(§4F.4) are BUILT & wired through the engine; elaboration(30) is judged by Stage B on the
> instructions rubric. Remaining stubs: quiz-question forbidden-function source-check gate + per-question
> posting path (TODO below). Do NOT hand-roll grading — it RUNS THROUGH THE ENGINE (see below).

## Runs through the engine (never hand-roll)
- **`grade_engine.core.grade(config, code)` → `graders/gh`** already grades GitHub assignments (autograder
  score via `github_access.list_runs` + `parse_total_points_from_log_zip`; commit-late). This sub-skill is
  the METHOD, not a standalone driver — same rule as `grade-nb`.
- Policy home: **`CourseGlobalWorkflow/GRADING.md` Part B** (GitHub assignments), plus the course's
  `Grading override:` document when its `CLAUDE.md` declares one (GRADING.md Q4). Read whichever is in
  force; this file only adds the git-program-specific method.

## Rubric (the in-force weights — see the policy home above)
| Item | Weight | Source |
|---|---|---|
| Repo link submitted | 5% | submission |
| Autograder result (score/100 × this weight) | 50% | engine `gh` (Layer 1) |
| Elaboration (algorithm + all-inputs correctness + errors/lessons) | 30% | AI Stage B |
| Commit process (timing + count, genuine progression) | 15% | AI Stage B (server-time authenticity) |

- **Autograder = only the 50% slice.** Elaboration + Commit (45%) are judged in Stage B.

### Commit process = the online-exam PROCTOR (server-time authenticity — BUILT)
Fully-online course + online exams → the commit history is the anti-plagiarism proctor. **Single /
all-at-once commit is NOT accepted for full commit credit even if tests pass** (policy, not courtesy —
GRADING.md Part B **§4F.4**).
- **Trusted clock = SERVER time**: repo `created_at` → the passing run's `created_at`. Commit dates are
  forgeable, used ONLY to detect backdating (author span ≫ server window). Self-reported minutes are never
  the clock.
- **Engine-implemented (do NOT hand-roll `gh api`)**: `graders/gh.py._fetch_repo_data` captures the server
  timestamps → `lib/commit_inspect.authenticity(insp, repo_created_at, graded_run_created_at)` returns
  `{repo_to_pass_min, verdict, accepted, backdated, flags}`. Verdicts: `instant` (repo→pass < ~5–10 min
  heuristic + single/no-fix), `no-commits-in-window` (single commit over a long window — worked locally,
  process not in git), `backdated`, `clean`. It rides through `review_content.authenticity` and the Stage-A
  report **auto-prints** the flags in *Section 0* every run — no prompting.
- **Stage B uses it**: read `review_content.authenticity`; a not-`accepted` verdict caps the commit item
  (§4F 5-group). **Instructor-only** — the student comment states the process requirement ("commit history is
  how online work is verified; a single all-at-once commit isn't accepted for full commit credit"), never the
  suspicion. Threshold is per-assignment tunable later via the git-program manifest.

## Quiz vs homework (the one internal difference)
- **Quiz question:** STRICT — the autograder source-checks forbidden shortcuts (`sorted/.sort/min/max`),
  T2/T3/T4 assert the exact arrangement, non-algorithm solutions score < 50. Quiz FINAL score is
  **per-question** (see below), never `posted_grade`.
- **Homework:** looser — the same rubric, no exact-arrangement / forbidden-function hard gate unless the
  spec demands it.

## Quiz scoring — per-question, NOT posted_grade (Access/Canvas.md [Quiz Submission Scoring])
A quiz-type item's final grade is the **sum of per-question scores**; setting `submission[posted_grade]`
leaves the quiz stuck at `workflow_state=pending_review`. So a git-program **quiz question** is scored on
its question submission, not via `post_grades.py` (which posts ASSIGNMENT grades). **TODO (at first
grading): the per-question posting path** (distinct from the assignment `post_grades.py`).

## Build-time info this sub-skill READS (left by quiz-builder / git-homework)
Per git-program item, the build persists (placeholder now, full later): the **rubric split**, the
**forbidden functions**, the **T1–T4 test design**, and the **repo / `<CODE>`**. TODO: settle the storage
(a git-program grading manifest, mirroring `grade_engine/manifests/<code>.json` for NB) at first grading.

## TODO (remaining after M1QP1)
1. ~~Autograder 50% + commit authenticity through `graders/gh`~~ — **DONE** (server-time proctor §4F.4,
   `commit_inspect.authenticity`). Still TODO: quiz-question **forbidden-function source-check** gate
   (`sorted/.sort/min/max`) + exact-arrangement T2–T4, surfaced to Stage B.
2. Build-time manifest schema (rubric / forbidden / tests / repo + **per-assignment authenticity threshold**)
   + where `quiz-builder`/`git-homework` write it.
3. Per-QUESTION quiz posting path (not `post_grades.py`).
4. Wire `grade` §4 dispatch: git-program confirmed → this sub-skill (like NB → grade-nb).

## See also
- `grade/SKILL.md` (master) · `grade-nb/SKILL.md` (the pattern this mirrors).
- `CourseGlobalWorkflow/GRADING.md` Part B · the course's `Grading override:` document if declared · `Access/Canvas.md` [Quiz Submission Scoring].
