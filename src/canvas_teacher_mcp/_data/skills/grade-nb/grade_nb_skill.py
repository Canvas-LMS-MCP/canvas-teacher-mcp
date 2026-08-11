"""RETIRED 2026-07-03 — the standalone NB gatherer is superseded by the ENGINE path.

Grade NB assignments with:  grade_engine.core.grade(config, code)  ->  graders/nb.py
  (gathers via attachments.read  +  nb_inspect.resolve_tasks region completeness
   +  revision_progression) -> emits review_content -> the AI Stage B scores.

Why retired: this file called `gws` directly, violating the Attachments.md contract
("graders never call gws"). Its region/1-N logic now lives in
grade_engine/lib/nb_inspect.py (`resolve_tasks`). The anchor STAMPER (creation side)
is unaffected: skills/nb-homework-create/nb_create.py. See skills/grade-nb/SKILL.md.
"""
raise SystemExit(
    "grade_nb_skill.py is retired — use grade_engine.core.grade -> graders/nb.py "
    "(region logic moved to grade_engine/lib/nb_inspect.resolve_tasks)."
)
