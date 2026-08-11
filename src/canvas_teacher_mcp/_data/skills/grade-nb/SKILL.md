---
name: grade-nb
description: >
  NB (Colab / Jupyter notebook) grading SUB-SKILL — the type-specific plug-in for the global
  `grade` skill. When an assignment's submission is a Colab/Drive notebook, `grade` dispatches
  HERE for the notebook + revision-history inspection, then returns to the general flow
  (report → self-challenge → POST). Consolidates GRADING.md Part C + GradingEngine/NbInspect.md
  into concrete steps. The NB grading RUNS THROUGH THE ENGINE (`core.grade` → `graders/nb.py` +
  `nb_inspect`) — this skill is the METHOD, not a standalone driver. Master is `skills/grade/SKILL.md`.
tools: [read_assignment_instructions, run_stage_a, get_submission, classify_submissions]
---

# grade-nb — notebook + revision-history inspection (sub-skill of `grade`)

Invoked FROM `skills/grade/SKILL.md` when a submission IS (or is designated) a Colab/Jupyter notebook —
then it is **REQUIRED, not optional** (do not eyeball an NB on the bare general path). It runs INSIDE
the full `grade` spine — it does NOT replace or shortcut it:
**Step 0 (scope: needs-grading queue + late/waivers) → Stage A (the ENGINE gathers via
`attachments.read` → `graders/nb.py`: `notebook{cells, pinned revisions}` + body/all_text, then
`nb_inspect.resolve_tasks` region completeness + `revision_progression`/`score_revision` process →
emitted as `review_content`) → Stage B (ALL general rules — §0Z FULL read, instructions rubric,
per-below-max reason, `comment_render` — the AI SCORES from `review_content`: comp per-problem 1/N,
rev process, refl from the reflection location) → report → self-challenge → POST.** It supplies the
NB-specific DETAIL within Stage A + Stage B; it NEVER skips Step 0 or the general Stage-B rules. Policy
homes: `GRADING.md Part C` + `GradingEngine/NbInspect.md` (this file orders them into steps — it does
not re-decide policy).

## ⛔ Two rules that made past NB grading wrong (do NOT repeat)
1. **§0Z — never truncate.** Read the WHOLE notebook, every cell source + output, IN FULL. The engine
   `lib/nb_inspect.load_notebook` reads the entire file (raises if it can't) so nothing is sliced.
2. **DIFF vs the template — never regex the merged notebook.** Judge only the **student-ADDED cells**
   (`template_added_cells(student, template)`). The template's own example `<img>`, the
   `![Description](Image Link)` placeholder, and provided task cells will fool a merged scan.

## Fetching = the ENGINE's job (grade-nb never calls gws)
`attachments.read(submission)` (called by `graders/nb.py`) fetches the notebook in ONE read →
`["notebook"] = {drive_id, accessible, cells, revisions(pinned)}` PLUS `body_text` / `all_text`
(where the Reflection lives). **grade-nb / any grader NEVER calls `gws` directly** (Attachments.md;
engine `selftest` greps for `gws`/HTTP outside `attachments.py` → STOP). The 2026-07-03 gws-cwd
detail lives INSIDE `attachments.py`, not here.

## ⛔ FILE-FIRST — the notebook is the grade; screenshots are AUXILIARY (do NOT download them)
NB grading reads the **actual file**: cells (code + explanation text) for completeness, and the
**actual pinned revisions** (times + content, via the revisions API) for process. A submitted
**revision-history SCREENSHOT is FORMALITY ONLY** (grade-nb §B) — you NEVER grade from it. So the
engine does **NOT download body images for NB** (`graders/nb.py` calls `attachments.read(…,
fetch_visual=False)`): the images are inventoried but not fetched. This is both correct (file-first)
and the fix for the gather timeout — downloading ~98 revision screenshots for a 17-student lab was
what blew the 3-min budget (now ~148s). A **diagram-type ANSWER image** (e.g. a Venn-diagram lab) is
the exception — the ONE case a picture IS the answer; fetch it on demand (`fetch_visual=True`), and
when any image IS fetched the grader uses the **downscaled `view_path`** (Lanczos ≤1400px, cheap
vision; §0Z holds — same image, smaller). Principle: **read the file to grade; pull a screenshot only
if a diagram answer requires it — a supporting device, never the primary.**

## Step A0 — read the template's instructions → set the NB internal rubric (do FIRST)

**⇒ THE FIRST NB STEP — reached ONLY once `grade` has confirmed this assignment is NB (§4 dispatch);
non-NB assignments never come here. That confirmation is the trigger: the MANIFEST.** Every NB grade
needs `grade_engine/manifests/<code>.json` — it holds `exec_cells` (the completeness denominator, GRADING
Part C §2), `sections` (the pin-per-section expectation, §3), and **`expected_active_min` (E)** (the
time-plausibility threshold, §4b.1). So the FIRST thing once NB is confirmed:
1. **Manifest exists?** (`grade_engine/manifests/<code>.json`) → use it, continue.
2. **Missing?** → BUILD it canonically, BEFORE Stage A (never hand-count):
   - a. Find the template from the assignment instructions (a GitHub/Colab link, e.g. `<org>/PythonCH04/ch04.ipynb`).
   - b. Fetch to a local file: `gh api repos/<org>/<repo>/contents/ch0N.ipynb --jq .content | base64 -d > /tmp/chNN.ipynb`.
   - c. `python3 -m grade_engine.lib.nb_inspect --build-manifest /tmp/chNN.ipynb <code> --note "..."`.
   - d. **CONFIRM with the instructor**: show `exec_cells` + `sections`. The 'section' count can be off (sub-problems vs top-level — e.g. ch04's 38 `Problem X.Y` → **8** top-level sections). Only proceed once the numbers are right.
3. **⇒ AUTHOR `expected_active_min` (E) — MANDATORY, every NB lab (GRADING §4b.1).** Read the template's
   @answer/problem cells, rate each trivial(1)/moderate(3)/hard(6) min, sum → **E = genuine active-min for
   THIS lab** (content-based, NOT the class median). Write it into the manifest. The engine sets `T=0.4×E`
   and ramps implausibly-fast work; **no E ⇒ the ramp is SKIPPED and the report carries a loud flag** —
   so a lab graded with no E is graded with NO time check. Cross-check E against the class median active
   (surfaced in `review_content.params`) after Stage A; if wildly off, revisit E or flag a class anomaly.
4. Assignments created via **nb-homework-create store the manifest at creation** → zero prep.

The template notebook (e.g. `ch03.ipynb`) IS the instruction source: its markdown TASK cells state what
each section/question ASKS — CODE tasks ("complete / write / run …") and EXPLAIN tasks ("explain why …,
describe the difference …"). `grade_nb_skill.py` returns **`template_tasks`** = those extracted prompts
(each with `type=code|explain` + its anchor). From them:
1. **List per-section what-to-do** — which slots are code answers, which are explanations.
2. **Set the NB INTERNAL rubric** — the breakdown of the NB score PORTION (the % of the assignment that
   is the notebook): per-task correctness (code + explanation) + completeness + revision process +
   reflection. It must MATCH what the instructions ask — a section that asks for an explanation MUST
   carry an explanation item. This is the sub-skill's OWN rubric inside the NB portion.
3. **Score by COMPARING the student's actual content to each task's instruction — NOT by stats.** Read
   the student's CODE and EXPLANATION (via the resolved answer cell) and judge against what was asked.
   Stats (executed / empty counts) are SUPPORTING evidence only, never the score itself. Example:
   *"explain why the loop fails"* → READ the student's markdown answer → did they actually read it and
   answer correctly? → award/deduct on your OWN criteria with a specific reason (GRADING §4.1–4.2).
   *"complete the function"* → check the answer cell ran with correct output; read the code only as far
   as needed to judge correctness (anchor keeps it targeted, not a full 58-cell read).

The NB internal rubric + per-task scores + reasons are what this sub-skill returns UP to the general
Stage B (which folds them into the assignment's Grading-block rubric).

## Anchor resolution — REGION-based (answer = anchor .. NEXT anchor)
Anchors mark **PROBLEM cells only** — `<!-- @anchor:P#.# -->` (from `nb-homework-create`) or, for a
LEGACY / MIXED batch, the instruction's own text. There is **NO separate `@answer` cell and no inserted
cell** — the answer is simply the REGION after the problem. `grade_nb_skill.resolve_tasks` (plural) runs
**PER STUDENT** (so a mixed batch — some students on the stamped template, some on the old one — is
handled automatically):
1. **Locate** each task's problem cell: `@anchor` tag → instruction-text **CONTAINS** → not found.
2. **Answer region = `[anchor cell + 1 .. the NEXT located anchor]`.** So ANY cell the student ADDED
   under the problem (a fresh answer cell, an edited "Answer here", extra code) is **INCLUDED** — no
   next-cell-only trap, no dependence on a designated answer cell.
3. **Region evidence** (BOTH signals, no code-vs-explain gate): `{cells, code, executed, code_output,
   md, md_text_chars}`. The inline AI reads `cells[region[0]:region[1]]` + the prompt and judges the
   code AND the explanation together.
4. **Not located → `needs_ai_read`** → the INLINE AI (you, layer 2) reads/locates it; escalate to a §1
   instructor flag ONLY if the AI also can't. Never auto-zero blind, never crash.

Colab has NO stable cell id across "Save a copy" (verified) — the anchor tag or the instruction text is
the handle; the AI-read is the last-resort locator. Mixed anchored + un-anchored students in ONE
assignment grade fine — each resolves by whatever their notebook actually has.

## What to inspect (maps to the rubric)

### A. Notebook (cells) — completeness + real work
- **Completeness:** every EXAMPLE cell run (has `execution_count` + `outputs`); every BLANK cell
  actually solved (not a placeholder / `000` / empty). `deep_read(student_path, template_path)` →
  `{accessible, completeness(0..9), evidence[], error, …}` (its per-task fields fit the template's
  shape; where they don't, read the added cells directly — see below).
- **Real student code:** `template_added_cells(student_cells, template_cells)` = the cells the student
  wrote (not the template). **YOU read these sources directly** — did they SOLVE the problem, or leave
  it blank / paste? 
- **Copy-paste across students:** compare added-cell sources between students; near-identical solutions
  = flag.
- `accessible=False` (notebook not shared as Editor / deleted) → inaccessible rule (Part C §5): 0 on
  the affected items + comment "share as Editor and resubmit"; NOT a silent zero, NOT an engine STOP.

### B. Revision history (the PROCESS — heavily weighted here)
- **PINNED only** (`keepForever=true`). Auto-save revisions (Colab default, ~30s gaps) are EXCLUDED —
  a long auto-save list does NOT prove deliberate section pinning.
- `revision_progression(revs)` (revs = pinned, oldest→newest, each carrying parsed `nb`) →
  `{steps[], content_steps, span_min, bursted, ok, evidence}`; `score_revision(progression)` →
  `{score, reason}`. `revision_check(revs_meta)` → `{count, pinned, span_min, median_gap_min, gaps_min, bursted}`.
- **Revision + Reflection = the AUTHENTICITY LEVER (GRADING Part C §4b), NOT form deductions.**
  Completeness is the CORE; rev/refl modulate for 괘씸도 — weigh 경중 (proportionality):
  - **Genuine process** (real pins growing content over realistic time, no burst; a reasonable
    takeaway + a ROUGH time) → award rev/refl **full / near-full.** Do NOT dock a high-completeness
    student over per-section timing or reflection form. Diligent → stays high.
  - **RED FLAG** = full/high completeness but thin/no pins, one bulk pin, a burst, or a span far too
    short for the work → suspicion of copy-paste / direct AI → apply the lever **STRICTLY**, deduct in
    proportion to the suspicion + note it. Purpose = keep diligent students high AND open a real score
    gap for suspicious / low-effort work (differentiation tool). Same evidence → same treatment.
- The submitted revision-history SCREENSHOT is FORMALITY ONLY — grade from the ACTUAL file's pinned
  revisions (times + content) in `attachments.read()["notebook"]["revisions"]`.

## The ENGINE path — `core.grade` → `graders/nb.py` (run this, NOT a standalone driver)
```
grade_engine.core.grade(config_path, code)          # via the grade_skill.py Stage-A driver
```
`graders/nb.py` (the GATHERER — never scores the rubric, never posts) does, per needs-grading student:
1. `att = attachments.read(submission, …)` → `att["notebook"]{cells, revisions(pinned)}` + `all_text`
   (body / Reflection) + `has_visual`. **No gws here** — `attachments.py` already fetched it.
2. Load the assignment MANIFEST `grade_engine/manifests/<code>.json` (`[{anchor, type, prompt}]`).
3. `nb_inspect.resolve_tasks(att["notebook"]["cells"], manifest)` → per-problem region + evidence.
4. `revision_progression` / `score_revision` on `att["notebook"]["revisions"]` → process.
5. Emit **`review_content`** (below), `raw` = provisional, `needs_review` → the AI Stage B SCORES it.
```
review_content: { tasks:[{anchor, type, prompt, found, method, region, evidence, needs_ai_read}],
                  revision:{pinned, span_min, gaps_min, bursted, score, reason},
                  reflection_text, has_visual }
```
The AI (Stage B, INLINE) scores **comp** (per-problem region, EQUAL 1/N), **rev** (process), **refl**
(reflection location) per GRADING Part C §2–4, then `report_generator` + `post_grades.py`. The AI reads
any region on demand from the fetched cells (§0Z full, targeted by `region`).

It reuses the canonical `grade_engine/lib/nb_inspect` functions — no new grading logic here; the driver
only GATHERS the notebook data correctly (the part that used to be hand-rolled ad-hoc).

## Rubric mapping (the general `grade` flow confirms the rubric first)
Typical NB rubric (confirm per assignment — Canvas Grading block ▶ propose): Link&access · Notebook
completeness · Revision history (process) · Reflection.
- **Completeness = the ANSWER portion, scored per ANCHOR, EQUAL 1/N.** Each anchor is one gradeable unit
  — a code answer OR an explanation answer, following the instructor's own separation (that is why code
  and follow-up questions get SEPARATE anchors, e.g. `P3.1` code + `P3.1Q` explain). Score each anchor
  0..1 *against what THAT problem asks*: code → runs + correct output; explain → substantive answer;
  a hybrid region (code + explanation under one anchor) → judged as ONE unit against the ask (do NOT
  split into a code-only / explain-only lens). **Completeness points = `(Σ anchor scores / N) ×
  Completeness_weight`** — the 1/N is ONLY inside Completeness.
- **Revision (process) = `score_revision` + §B deductions** — NOT per-anchor (pins / span / burst /
  total-time realism).
- **Reflection = a reasonable takeaway + a ROUGH time (per-section NOT required).** The real modulation
  is the authenticity lever (§4b), not reflection form.
- **Link & access = notebook opened as Editor.**
Below-max items REQUIRE a specific reason (GRADING §4.1–4.2).

## Scoring — two layers: code (deterministic) + INLINE AI (the default method)
The NB score is produced in two layers. **Layer 2 is INLINE — the session AI (you), in chat. That is
the current, default, only-built method.** (Subagent parallelization is a FUTURE option for very large
batches — see the note at the end; do NOT spawn agents for class-size work.)

**Layer 1 — deterministic (`grade_nb_skill.py`, NO LLM).** Scores the bulk mechanically → completeness
(executed / output / empty), each `tasks[]` `answer_ok` for CODE (ran + non-error output), revision
process (`revision_score` + span/burst/pins), `anchors_missing`. The code returns **evidence + verdicts
+ `answer_idx`**, never reason text.

**Layer 2 — semantic, INLINE (you).** For what code can't judge: EXPLAIN answers (correctness /
substance), FAILING or borderline code, copy-paste suspicion, **and any task flagged `needs_ai_read`**
(the mechanical resolver couldn't locate it → YOU read that student's notebook + the prompt to FIND and
judge the answer; escalate to a §1 instructor flag ONLY if you also can't find it). Per such task:
- Read the EXACT answer via `tasks[i].answer_idx` from the saved `<uid>/latest.ipynb` (§0Z full,
  targeted — the anchor keeps it to one cell, not a 58-cell read). The gatherer does NOT dump answer
  sources; you read on demand.
- Judge it against the task's `prompt`.
- **YOU author the per-task score + REASON directly** (backed by layer-1 evidence) → write into the
  authoring JSON (`earned` + `reasons`) → `comment_render` → the comment carries your reasons.

So there is no separate "sub-grader returns the reason" in inline mode: the CODE returns evidence, and
YOU (inline) write the reason. Results fold into the NB internal rubric; instructor reviews + go → POST.

### (LATER — not built, not default) subagents for very large batches
Only when one context can't hold the semantic volume: one agent PER STUDENT — you inject its answer
cells (via `answer_idx`) + the rubric; it returns `{task, score, reason}` via a STRICT schema; you
handle nulls/deaths and keep the human gate. Never one agent per cell. Class-size (≤~30) = inline.

## Back to `grade`
After `grade_nb_skill.py` + your Stage-B judgment: author comments via `lib/comment_render`, build the
authoring JSON, `report_generator` → grades.json → POST (post-gate + go). All of that is the general
`grade` skill — this sub-skill ends when the per-student NB scores + evidence are ready.

## See also
- **`skills/nb-homework-create/SKILL.md`** — the CREATION mirror (stamps the `@anchor`/`@answer` this
  grader resolves). Keep the two in sync.
- `GRADING.md` Part C §1–6 + §0Z · `GradingEngine/NbInspect.md` (function contracts) · `skills/grade/SKILL.md` (master).
