# Conventions

What this server enforces, and the working rules behind it. The enforced ones are in the code —
no argument turns them off. The rest are practice worth borrowing.

Distilled from several years of running nine courses through this code. The numbers that belong to
those courses — late tiers, rubric splits — are deliberately absent. Bring your own.

## Enforced

- **Create and update unpublished.** Publishing is a human act. Every page, assignment and quiz
  this server writes arrives with `published: false`.
- **Never delete.** No tool removes a course, an assignment, a page or a submission.
- **Back up a description before overwriting it.** Canvas has no revisions API for assignments —
  `/assignments/{id}/revisions` is 404 — so an overwrite is final. The old HTML is saved first.
- **Fail loudly.** A Canvas error raises, 404 included. Every URL is assembled from your config, so
  a 404 means the address is wrong. A silent `None` once surfaced as "this assignment has no
  submissions".
- **Send what Canvas actually accepts.** Several endpoints return HTTP 200 and change nothing — a
  JSON-encoded grade, a partial quiz-question payload, `seconds_late_override` sent alongside
  `late_policy_status`. The client sends the working form.

## Grading, when you get there

Not in this release. These are the rules that made grading survivable:

- **The rubric the student saw wins.** The points table on the assignment page outranks a Canvas
  rubric object, which outranks any default in the software. A number that exists only in source
  was never shown to anyone and cannot justify a score.
- **Read everything, in full.** No previews, no `head`, no first-N-characters while grading. An
  80-character preview once hid a student's image and cost them the marks.
- **Look at every artifact before posting.** If the tooling surfaced a drawing and nobody opened
  it, that is the grader's omission, not the student's.
- **Give every deduction a reason** naming what was wrong, quoting the evidence, and saying how to
  earn the marks next time.
- **Keep accommodations out of the student's comment.** The student knows; naming it stigmatizes.
  Record waivers in the instructor's report.
- **Re-grade upward only.** A second pass exists to find work that improved. Never lower a posted
  score without saying so deliberately.
- **Store no grades.** Canvas is the record.

## Layout

Everything a session writes goes under the course's `output/`, in a folder named for the KIND of
artifact — never for one assignment, because the file name already carries that.

`input/` is yours: material that arrived from outside. Anything the assistant authored is output,
including the JSON a builder rendered from.

One step's output is the next step's input, so a source file and what it renders share a folder and
a stem.

## Proof

State a result as a file, not as a sentence. Write the artifact, then point at it. A phase with no
artifact did not happen, whatever the transcript says.
