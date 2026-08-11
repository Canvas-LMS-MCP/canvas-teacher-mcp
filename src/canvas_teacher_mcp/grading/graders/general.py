"""General grader — the UNIVERSAL Stage-A scaffold (GRADING.md Part A §0).

Used for any assignment the classifier could not map to a type-grader (math, English,
political science, art — ANY subject) AND as the safety FLOOR when a type guess is wrong.
It only GATHERS: every material via the central reader (`attachments.read` — all files +
Canvas text + repo_link + Colab notebook, regardless of type), plus the Canvas rubric. It
SCORES NOTHING — `raw=0` is a placeholder; **AI Stage B** reads the gathered materials and
scores each rubric item against the Canvas rubric / instructions (GRADING §7, §4.5). There
is NO subject knowledge and NO judgment in this code — that is the AI's job by design.
"""
from ..lib import attachments

# What this grader promises to emit (lib/contract.py). Declared, not inferred: the engine
# cannot otherwise tell a field that is empty on purpose from one that was dropped — the
# gap that let quiz.py lose `review_content` and silently switch the view-gate off.
PRODUCES = frozenset({"review_content", "needs_review", "rubric_items"})


def default_rubric(points_possible):
    # No automated rubric — the Canvas rubric / instructor decides; AI scores in Stage B.
    return {}


def grade(*, submission, asmt, course, download_dir, browser_fetcher=None,
          canvas_token=None, **kwargs):
    # Universal gather (type-independent): all files + Canvas text + repo_link + notebook.
    # AttachmentReadError propagates → core.py applies the §1 STOP (materials check failed).
    materials = attachments.read(
        submission, download_dir=download_dir,
        github_org=course.get("github_org"), canvas_token=canvas_token,
        browser_fetcher=browser_fetcher)

    # SURFACE what was gathered so Stage B can actually READ it (§0Z). Without this the universal
    # fallback grader gathered the submission but returned nothing to read -> every general-graded
    # assignment was scored blind. Mirror the jshell grader's review_content shape (the type-agnostic
    # subset): the FULL gathered text + every attachment + every image path to VIEW.
    ok_items = [it for it in materials.get("items", []) if it.get("status") == "ok"]
    items_out = [{"kind": it.get("kind"),
                  "name": (it.get("meta") or {}).get("name") or it.get("source"),
                  "magic": it.get("magic"),
                  "text": it.get("text") or "",                    # FULL extracted text (pdf/gdoc/txt/office)
                  "path": it.get("view_path") or it.get("path")}   # image/screenshot path to VIEW
                 for it in ok_items]
    images = [it.get("view_path") or it.get("path") for it in ok_items
              if it.get("magic") in ("png", "jpeg", "gif") and (it.get("view_path") or it.get("path"))]

    # Rubric rows for the report. core.grade always normalizes the rubric to
    # (label, points) tuples in asmt["rubric"] (core.py: [(k, v) for k, v in rubric.items()]);
    # a Canvas rubric dict may also appear if passed raw. Accept both.
    rubric_items = [
        (r[0], r[1]) if isinstance(r, (tuple, list))
        else (r.get("description") or str(r.get("id")), r.get("points"))
        for r in (asmt.get("rubric") or [])
    ]

    return {
        "raw": 0, "posted": 0,          # placeholder — AI Stage B sets the final score
        "scores": {},
        "rubric_items": rubric_items,
        # No comment field of any name — the engine authors no student-facing text
        # (GRADING §7.1). `comment_render` in Stage B is the ONE renderer.
        "review_content": {             # ← the gathered submission, SURFACED for Stage B to read (§0Z)
            "all_text": materials.get("all_text") or "",   # COMPLETE gathered content (body + every attachment)
            "body_text": materials.get("body_text") or "", # just the Canvas text box (subset of all_text)
            # The RAW submission HTML, unstripped. Some rubrics grade the MARKUP itself — a
            # "format this in Canvas with HTML" assignment scores headings / tables / <pre><code> /
            # <img> / links / bold, none of which survive tag-stripping, so Stage B could not judge
            # them at all from body_text. It is also the elab-authenticity read (GRADING §4F.7.2),
            # which the gh/quiz graders already surface and this one did not. (<course> A203, 2026-08-02.)
            "body_raw_html": (submission.get("body") or ""),
            "items": items_out,                            # every attachment, FULL text
            "images": images,                              # image/screenshot paths (VIEW when judging)
        },
        "needs_review": [
            "GENERAL grader (no automated type-grader): AI Stage B MUST read the gathered "
            "materials and score every rubric item from the Canvas rubric / instructions. "
            "raw=0 is a placeholder, not a final score."],
        "finalizable": materials.get("status") == "ok",
    }
