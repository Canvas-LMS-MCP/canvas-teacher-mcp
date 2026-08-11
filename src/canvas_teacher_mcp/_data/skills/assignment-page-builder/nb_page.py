"""nb_page — GLOBAL NB (Colab / Jupyter notebook) page builder (config-driven).

The ONE builder for a notebook lab's Canvas page. A course's LOCAL conductor calls this; course
coordinates come through the ONE reader `course_config.load(slug)` (course_id, base, token_env,
output_dir) — never hardcoded, never a json opened here. Sibling of `git_page.py` (git/program type).

Follows `assignment-page-builder/nb-assignment-format.md` (pinned sections [1]..[6]) and
`nb-homework-create/SKILL.md` §6 (the page MUST carry the rubric table, the grading guide, and the
submission spec — ch03 failed by omitting them). Grading keys are the engine's `comp`/`rev`/`refl`
(GRADING.md Part C); this builder names them on the page so the student sees what is scored.

RENDERING IS THE SKELETON'S — this file owns none of it. Write plain text with `backticks`; the
skeleton's ic/rich_ul/rich_ol/rich_table/link/pre/callout do the HTML. If a shape is missing, ADD IT
TO THE SKELETON — never re-implement it here.

The notebook IS the instruction, so there is no gdoc: `doc_blocks=None` -> a summary-only page.

lab — the data the conductor passes:
    assignment_id, name,            # Canvas item
    title,                          # page title line
    gist,                           # [1] one line: what you build
    notebook_url,                   # the GitHub .ipynb (students open it in Colab)
    due_note?,                      # (label, text) -> a navy callout at the very top, e.g. an
                                    #   off-cycle deadline the student must not misread
    shape: [(label, [sub, ...])],   # [2] how the notebook works
    sections: [str, ...],           # [3] the section list (numbered)
    todo: [(label, [sub, ...])],    # [3] what to do
    guides?: [{title, lead?, steps?, images?, warn?, warn_title?, note?, note_title?}],
                                    # [4] HOW-TO sections, one per topic, each with its own heading.
                                    #   Use these for the steps that decide whether the work can be
                                    #   graded at all — how to pin a revision, how to share the link
                                    #   the right way. A student skips a one-line mention buried in
                                    #   `todo`; a titled section with a screenshot and a coloured
                                    #   box gets read. `images` = [{url, alt?, width?, caption?}]
                                    #   (a Canvas file URL is used VERBATIM — the ?verifier= token
                                    #   is part of it). `warn` = yellow box (never do this),
                                    #   `note` = navy box (must not miss).
    submit: [(label, [sub, ...])],  # [5] what to submit
    rubric_pts?: {comp,refl,rev}    # [6] POINTS only. The rubric TEXT is DERIVED from the
                                    #   notebook's manifest (`rubric_from_manifest`) — how many
                                    #   problems, how many example cells, how many reflections, and
                                    #   the real pin names. Never hand-write rubric prose: a page
                                    #   that says "a Reflection at the end of EVERY section" while
                                    #   the notebook has one at the end is telling students to do
                                    #   something that does not exist (<course> ch02, 2026-08-02).
                                    #   No manifest -> build error, not a silent default.

⛔ Never put the authenticity-DETECTION policy on the page (nb-homework-create §6) — how revision
timing is used to flag copy-paste is Stage-B grading policy, instructor-only. State expectations only.
"""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
# The tree root comes from the environment, never from a directory NAME — walking up looking for
# one only works inside this tree, and an installed package sits outside it.
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "..", "code")))
from canvas_root import root  # noqa: E402
_CG = str(root())
sys.path.insert(0, os.path.join(_CG, ".claude", "code"))

from canvas_core import assignment_page_builder as skel  # noqa: E402
import course_config  # noqa: E402  # THE config reader (single source; never re-implement)

# Rubric WEIGHTS are policy (GRADING.md Part C); the rubric TEXT is DERIVED from the notebook.
# Only the split is a default — a lab that weights differently passes `rubric_pts`.
DEFAULT_PTS = {"comp": 30, "refl": 10, "rev": 10}


def rubric_from_manifest(manifest, pts=None):
    """Build the rubric rows FROM the notebook's own manifest — never hand-written prose.

    A hardcoded rubric lies as soon as a notebook changes shape. The 2026-08-02 <course> ch02 page
    shipped "the Reflection question answered at the end of EVERY section" while the notebook had
    exactly ONE reflection, at the end — the page told students to do something that does not exist.
    The manifest already holds the truth (`sections`, `section_labels`, `exec_cells`, `tasks` with
    `type`), so the wording is computed from it and cannot drift.

    manifest = the loaded `grade_engine/manifests/<code>.json` dict.
    """
    pts = {**DEFAULT_PTS, **(pts or {})}
    tasks = manifest.get("tasks", [])
    labels = manifest.get("section_labels") or []
    n_sec = manifest.get("sections") or len(labels)
    n_exec = manifest.get("exec_cells")
    # A task's type lives in the stamped anchor comment: "<!-- @anchor:R6 type=reflect -->".
    # `reflect` = the section takeaway (the `refl` rubric row). `explain` = a PROBLEM whose answer
    # happens to be prose ("explain why // gives 5") — that is completeness, not reflection.
    # Counting explain as reflection produced "All 2 Reflection questions" on a notebook with ONE.
    n_reflect = sum(1 for t in tasks if "type=reflect" in (t.get("prompt") or ""))
    n_code = len(tasks) - n_reflect

    comp = "Answer all %d problems, and RUN every one of the %d example cells so its output shows" % (
        n_code, n_exec) if n_exec else "Answer all %d problems and run every cell so its output shows" % n_code

    if n_reflect == 0:
        refl = None                                   # nothing to grade -> no row at all
    elif n_reflect == 1:
        refl = "The one Reflection question, at the END of the notebook, answered properly"
    elif n_reflect >= n_sec > 0:
        refl = "The Reflection question answered at the end of EVERY section (%d of them)" % n_reflect
    else:
        refl = "All %d Reflection questions answered properly" % n_reflect

    if labels:
        shown = "`%s`" % "`, `".join(labels) if len(labels) <= 6 else "`%s` ... `%s`" % (labels[0], labels[-1])
        rev = "One pinned revision per section, named %s, over real working time" % shown
    else:
        rev = "One pinned revision per section, over real working time"

    rows = [("Notebook completeness", "comp", pts["comp"], comp)]
    if refl:
        rows.append(("Reflection", "refl", pts["refl"], refl))
    rows.append(("Revision process", "rev", pts["rev"], rev))
    return rows

# The grading guide — expectations only, never the detection mechanics (§6b).
_HOW_GRADED = [
    "**Completeness** — answer every problem and run every cell so its output is shown.",
    "__REFL__",     # replaced with the derived line (or dropped when the notebook has no reflection)
    "**Revision history** — pin a revision per section as you work. Your revision history is part of "
    "your grade: it is how the work is shown to be yours.",
    "**Process over result** — a finished notebook alone is not full marks. Show your work, and do not "
    "copy-paste code or submit work you did not do yourself.",
]


def _how_graded(rubric):
    """The expectation bullets, kept consistent with the DERIVED rubric rows. The reflection bullet
    used to be fixed prose ("a real answer at the end of each section") and contradicted a notebook
    with a single end-of-notebook reflection — the same drift the rubric text had."""
    refl = next((w for _i, k, _p, w in rubric if k == "refl"), None)
    out = []
    for line in _HOW_GRADED:
        if line != "__REFL__":
            out.append(line)
        elif refl:
            out.append("**Reflection** — %s%s" % (refl[0].lower() + refl[1:], "" if refl.endswith(".") else "."))
    return out


def _load_manifest(code):
    """The notebook's manifest is the source of truth for the rubric text (see rubric_from_manifest).
    Built by `nb_inspect --build-manifest`; missing one is a build error, not a fallback — a page
    whose rubric was not derived from the notebook is exactly the drift this function prevents."""
    p = os.path.join(_CG, ".claude", "code", "grade_engine", "manifests", "%s.json" % code)
    if not os.path.exists(p):
        raise SystemExit(
            "nb_page: no manifest for %s (%s).\n"
            "Build it first:  python3 -m grade_engine.lib.nb_inspect --build-manifest "
            "<template.ipynb> %s\n"
            "The rubric text is DERIVED from it — hand-writing the rubric is what let the page and "
            "the notebook disagree." % (code, p, code))
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _canvas_summary(lab):
    rubric = rubric_from_manifest(_load_manifest(lab["code"]), lab.get("rubric_pts"))
    total = sum(pts for _i, _k, pts, _w in rubric)
    parts = [skel.page_title(lab["title"]),
             "<p style='font-size:1.05em;'>%s</p>" % skel.ic("**%s**" % lab["gist"])]

    if lab.get("due_note"):
        label, text = lab["due_note"]
        parts.append(skel.callout(text, kind="note", title=label))

    parts += [
        skel.section("1. The notebook", skel.rich_ul([
            ("Open it on GitHub", [lab["notebook_url"]]),   # ic() links a bare URL — no link() here
            ("Then open it in Colab", [
                "In Colab: `File > Open notebook > GitHub`, paste the link above, and open it.",
                "Then `File > Save a copy in Drive` so you get your OWN copy. Work in that copy.",
            ]),
        ])),
        skel.section("2. What is in it",
                     skel.rich_ul(lab["shape"]) + skel.rich_ol(lab["sections"])),
        skel.section("3. What to do", skel.rich_ol(lab["todo"])),
    ]

    # HOW-TO guides — each its OWN numbered section, never folded into a paragraph elsewhere.
    # The two that decide whether a submission can be graded at all (pinning a revision, sharing the
    # link the RIGHT way) are the two students skip when they are one line inside "What to do".
    # Give each a heading, bullets, an optional screenshot, and an optional coloured callout.
    for g in lab.get("guides", []):
        body = ""
        if g.get("lead"):
            body += "<p>%s</p>" % skel.ic(g["lead"])
        if g.get("steps"):
            body += skel.rich_ol(g["steps"])
        for img in g.get("images", []):
            body += skel.image(img["url"], img.get("alt", ""), img.get("width"), img.get("caption"))
        if g.get("warn"):
            body += skel.callout(g["warn"], kind="warn", title=g.get("warn_title"))
        if g.get("note"):
            body += skel.callout(g["note"], kind="note", title=g.get("note_title"))
        parts.append(skel.section(g["title"], body))

    parts += [
        skel.section("What to submit", skel.rich_ol(lab["submit"])),
        skel.section("How this is graded",
                     skel.rich_table(["Item", "Points", "What earns it"],
                                     [[i, str(p), w] for i, _k, p, w in rubric]
                                     + [["Total", str(total), ""]])
                     + skel.rich_ul(_how_graded(rubric))),
    ]
    return "\n".join(parts), total


def nb_page(course_slug, lab, *, push=False, due_at=None, points=None):
    """Build an NB lab's Canvas page. Returns out (out['html']). push=True pushes to the Canvas
    assignment (needs lab['assignment_id']). Points default to the rubric's total."""
    cfg = course_config.load(course_slug)
    html, total = _canvas_summary(lab)
    out_path = os.path.join(cfg["output_dir"], "Canvas-Pages", "%s.html" % lab["code"])
    return skel.make_page(
        cfg["course_id"], lab.get("assignment_id"), lab["name"],
        None,                       # the notebook IS the instruction — no gdoc
        html,
        output_path=out_path,
        push_canvas=push, due_at=due_at,
        points=points if points is not None else total,
        base=cfg["canvas_base_url"], token_env=cfg["canvas_token_env"],
    )
