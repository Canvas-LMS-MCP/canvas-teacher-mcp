# NbInspect

Notebook deep-read as structural functions — railings, not signs. `lib/nb_inspect.py`.
What the results COST is `GRADING.md` Part C.

Two failures it makes impossible: the grader never holds a truncatable blob (`deep_read` returns
verdicts and evidence, and `load_notebook` raises rather than return a partial read), and every
judgment is on the TEMPLATE DIFF, so the template's own example image and placeholder can never be
counted as student work.

## Reading the notebook

- `load_notebook(path)` → the full parsed ipynb. Raises `NotebookError` when unreadable, so a
  partial read is never mistaken for "the student did nothing".
- `template_added_cells(student_cells, template_cells)` → the cells the student added or modified.
- `has_real_image(cell)` → evidence string or `None`. Reads the FULL source — `![alt](http|data:|attachment:)`,
  `<img src=…>`, cell attachments — and excludes the `Image Link` placeholder.

## Completeness

- `resolve_tasks(cells, tasks)` is the general per-problem path. `tasks` is the assignment
  MANIFEST (`[{anchor, type, prompt}]`, one entry per problem). It locates each problem by
  `@anchor` tag, else by instruction-text containment, sets the answer region to
  `[anchor+1 .. next anchor]` including student-added cells, and returns per problem
  `{found, method, region, evidence{cells, code, executed, code_output, md, md_text_chars},
  needs_ai_read, flag}`. Score each region equally, 1/N.
- Crash-safe by construction — anchors present, anchors removed, cells deleted, empty notebook.
  An unlocated region sets `needs_ai_read`; it never zeroes silently and never raises.
- `execution_analysis(cells, gap_cap_sec, burst_sec)` reads Colab `metadata.executionInfo` —
  the per-cell run timestamp. Returns `{code_cells, executed, span_min, active_min, burst_count,
  burst_frac}`. `executed` is the completeness numerator; `active_min` is the idle-capped
  cell-to-cell gap SUM, not `max − min`; `burst_frac` is reported separately so one long gap
  cannot mask a majority burst. Thresholds are named constants in `graders/nb.py`, surfaced in
  `review_content["params"]`.

⛔ Read `executionInfo`, never cell `outputs` (the template ships outputs) and never top-level
`execution_count` (Colab nulls it). There is no per-cell run COUNT — only the LAST run's timestamp
survives, so a cell is binary executed or not.

- `deep_read(student_path, template_path)` is the LEGACY 03NB shape with hardcoded task1/2/3.
  `resolve_tasks` supersedes it for any N-problem lab.

## Revision

Colab's named pins are not exposed by the Drive API — only `id`, `modifiedTime`, `keepForever`. So
revision is judged on content plus time over the PINNED revisions, never by name. Auto-save also
creates revisions, so progression over ALL revisions proves nothing.

- `revision_progression(revs)` → `{steps, content_steps, span_min, bursted, ok, evidence}`, judged
  on `keepForever=true` only, oldest→newest, each carrying its parsed `nb`. `ok` = at least 3 pins
  that grow content over real time. Burst, save-only and empty pins fail. The revisions come
  straight from `attachments.read(...)["notebook"]["revisions"]` — this module is network-free.
- `revision_check(revisions)` → count, pinned, span, median gap, burst. Auxiliary signal.
- `revision_diff(nb_old, nb_new)` → the cell sources added between two revisions.
- `score_revision(progression)` → `{score, reason}`. Lenient intro mapping — genuine 9,
  attempted-but-insufficient 6 (burst, too few, partial all collapse here), nothing 0. The reason
  carries FACTS only — pin times, gaps, what each pin added — plus fix guidance. Instructor tone;
  show, never threaten.

## Where it plugs in

These are the NB grader's functions, not a separate driver. `core.grade(course, code,
grader_override=…)` runs fetch → grader → `grades.json` → `report_generator` → the poster, and
`graders/nb.py` is the gatherer that calls the functions above and emits structured
`review_content` for Stage B. Never write that orchestration inline.

The manifest lives at `grade_engine/manifests/<code>.json`, built once from the template, so
`resolve_tasks` needs only `cells` plus the manifest at grade time. `nb-homework-create` stamps
the anchors when the notebook is created.
