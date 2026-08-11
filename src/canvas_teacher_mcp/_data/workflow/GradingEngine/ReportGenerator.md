# ReportGenerator

Stage B provides WHAT — judged scores, reasons, flags, as a JSON. The code owns HOW — fixed
sections, the summary table, the comments. `report_generator.py` + `lib/comment_render.py`.

Naming, rounds and the report's five sections are policy: `GRADING.md`.

## Two modules, one direction

`comment_render.render_comment(rubric, earned, reasons, points_possible=, held=)` returns ONE
comment string, and BOTH the report §5 and the poster's `comment[text_comment]` call it — so what
the report shows is byte-identical to what the student receives. It lives in its own module so the
poster never imports the reporting module: `comment_render` ← `report_generator`,
`comment_render` ← the poster.

## The comment gate is at GENERATION

`render_comment` always emits the full rubric breakdown, and raises `CommentError` when a
below-max row has no reason, or has a reason with no how-to-fix clause (`For full marks:` /
`To earn full marks:`). A policy-invalid comment cannot be produced, so a report containing one
cannot be written. Structural — no forgetting, no rework loop.

## Input

```json
{ "code": "03NB", "assignment_id": 3466672, "points_possible": 30,
  "due_at": "…", "run_date": "…", "round": "2nd",
  "rubric":   [{"item": "Link & access", "max": 6, "criteria": "…"}],
  "notices":  ["free-text note for the §1 header"],
  "students": [{"uid": 12345, "name": "…",
                "earned":  {"Link & access": 6, …},
                "reasons": {"Elaboration": "…"},
                "flags": [], "late": false, "waived": false, "held": false}] }
```

- Declare the `rubric` ONCE — item, max, criteria — not per student.
- Give `reasons[item]` wherever `earned[item] < max`, or generation FAILS.
- Store no `raw`. The code computes `sum(earned)`, so no stored total can drift.
- `held: true` ⇒ that student is not scored (`—` in the table) and the comment says re-share or
  resubmit.

## Output

```
python3 -m grade_engine.report_generator <grades.json> [out.md]
```

Writes the report — §1 flags · §2 rubric · §3 late · §4 summary table · §5 comments. The same
record is what the poster reads after the instructor's go. Generation never posts.

`scaffold()` stamps `"round"` from the Stage-A record it was built from, and the render derives its
own filename from that field — `{code}_grade_{round}.md` plus the matching record. `argv[1]` still
wins as an explicit override. `_audit` is not a round and is never stamped.

⛔ **Add no roster guard.** A render-time check comparing the names already in the file against the
ones about to be written only ESTIMATES whether two runs are the same grading, and a third round is
normally a SUBSET of the second — so it passes and overwrites anyway. A guess standing behind a
fact is not a second line of defence.

Every path this engine serializes goes through `paths.fold()` and comes back through
`paths.resolve()` — `Local/Paths.md`.

## Stage-A artifact schema (`{Code}_grade-stage-a_{ts}.json`)

Naming, folder and the required final line: `Discipline/Proof.md`.

```json
{ "result": "saved" | "partial" | "fail",
  "n_graded": 0, "n_flagged": 0,
  "sqlite_reads": {"students_accommodations": [], "late_waivers_for_code": [],
                   "assignments_notes_for_code": ""},
  "students": [
    { "uid": 102841, "accommodation": null, "late_waiver": null,
      "materials_read": ["<path>"],
      "autograder_run_id": 0, "autograder_steps": [], "autograder_error_text": null,
      "commit_time_check": {"last_ontime_commit_sha": "", "last_ontime_run_id": 0,
                            "due_effective_utc": "", "used_run_id": 0},
      "deduction_comments": [{"item": "", "points_lost": 0,
                              "error_quoted_from_artifact": "", "fix_suggestion": ""}],
      "student_comment_handling": [{"comment_text_verbatim": "", "classification": "",
                                    "draft_reply": "", "flag": null}],
      "commit_authenticity": {"engine_commit_score": 0, "n": 0, "verdict": "",
                              "accepted": false, "has_runtime_err": false},
      "score_components": {} }] }
```

FAIL when any of the three `sqlite_reads` is missing · `commit_time_check` is missing for a student
with an org-hub repo · a rubric item lost points without a `deduction_comments` entry carrying BOTH
`error_quoted_from_artifact` and `fix_suggestion` · a non-passing autograder has no
`autograder_error_text` · a student-authored comment has no `student_comment_handling` entry
(answered with `draft_reply` or flagged `INSTRUCTOR ACTION NEEDED` — never silently ignored).
PARTIAL when `materials_read` is empty while the submission has attachments.

`commit_authenticity` is an AUDIT TAG, not a gate. When Stage B's row differs from
`engine_commit_score`, `comment_render.reconcile_commit` tags it (`↑ engine 0→5`) and records
`commit_vs_engine{engine, final, reason}`. It never reverts the reasoned decision and never fails
the render.

Stage B records `{result, flags, rows:[{uid, materials_ok, verdict, engine_score, alt_score,
reason}]}`. POST records `{result, posted, students_posted, students_skipped_dup_comment,
students_skipped_already_graded, errors}`, with `result` DERIVED from the real HTTP outcomes —
every student posted ⇒ `posted`, some failed ⇒ `partial`, none ⇒ `fail`.
