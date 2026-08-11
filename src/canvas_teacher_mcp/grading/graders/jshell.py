"""JShell-lab grader — GENERIC GATHERER (GRADING.md Part E).

The SECOND kind of program homework (no GitHub / autograder). The student practices in JShell as the
lab's slides show, `/save -history`s the session, and writes the WHY answers. Submission arrives as
(a) a downloaded `.txt`/`.jsh` file linked in the body and/or (b) inline text, plus a result
screenshot and the reflection answers pasted into the Canvas text box.

DESIGN — the engine GATHERS, the AI SCORES. This grader holds ZERO lab-specific knowledge: no
per-step regex, no hardcoded point table, no detection. It (1) gathers lab-agnostically via the
central reader — the /save-history text, the WHY answers, whether a save file was submitted, every
image — and SURFACES them IN FULL in `review_content` (§0Z: Stage B reads all, never re-fetches or
truncates); and (2) loads the lab's MANIFEST (`grade_engine/manifests/<code>.json`), which carries
the ONLY lab-varying data as pure VALUES: the step list (id/label/pts/expect), the explanation
split, the file points. Per-step scoring is AI Stage B's job (read `all_text` / `items`, judge each
manifest step). The grader emits raw=0 (placeholder, like `general`) and NEVER writes a postable
comment (§7.1). A new JShell lab = a new manifest JSON only — this code is never touched.
"""
import json
import os
import re

from ..lib import attachments

_MANIFEST_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "manifests")

# Inline JShell session markers — used ONLY to decide file_present (does an item carry a shell?).
_SHELL_RE = re.compile(r"jshell>|/save|import\s+java|Scanner|System\.out\.print", re.I)

# Generic 30/15/5 split (GRADING.md Part E) — used only when a lab has no manifest yet. No lab specifics.
_DEFAULT_CODE_MAX, _DEFAULT_EXPL_MAX, _DEFAULT_FILE_MAX = 30, 15, 5


def _load_manifest(code):
    """Mirror of graders/nb.py — read manifests/<code>.json; no manifest is fine (AI reads the
    instructions' Step breakdown directly)."""
    p = os.path.join(_MANIFEST_DIR, f"{code}.json")
    try:
        with open(p) as f:
            return json.load(f), p
    except Exception:  # noqa: BLE001
        return None, p


# What this grader promises to emit (lib/contract.py). Declared, not inferred.
PRODUCES = frozenset({"review_content", "needs_review", "rubric_items"})


def default_rubric(points_possible):
    """3 top-level items (the Canvas summary / report show these; Code is itemized per step in the
    manifest / instruction DOC)."""
    return {"Code practice": _DEFAULT_CODE_MAX, "Explanation": _DEFAULT_EXPL_MAX,
            "File submission": _DEFAULT_FILE_MAX}


def grade(*, submission, asmt, course, download_dir, browser_fetcher=None,
          canvas_token=None, **kwargs):
    # Universal gather via the central reader (all files + body + images). AttachmentReadError
    # propagates → core.py applies the §1 STOP. NEVER re-fetch outside this path.
    # NO github_org: a JShell lab has no GitHub repo / autograder — never resolve one.
    materials = attachments.read(
        submission, download_dir=download_dir, canvas_token=canvas_token,
        browser_fetcher=browser_fetcher)

    # Surface EVERYTHING the central reader gathered (Attachments.md): body + every attachment —
    # .txt/.jsh shell, PDF, linked Google Doc, Office. `all_text` already concatenates all of it,
    # so the grader NEVER re-fetches and NEVER drops content (a PDF-only or gdoc-linked submission's
    # work all lives here). Stage B reads all_text + items IN FULL (§0Z).
    ok_items = [it for it in materials.get("items", []) if it.get("status") == "ok"]
    items_out = [{"kind": it.get("kind"),
                  "name": (it.get("meta") or {}).get("name") or it.get("source"),
                  "magic": it.get("magic"),
                  "text": it.get("text") or "",                        # FULL extracted text (pdf/gdoc/txt/office)
                  "path": it.get("view_path") or it.get("path")}       # image/screenshot path to VIEW
                 for it in ok_items]
    images = [it.get("view_path") or it.get("path") for it in ok_items
              if it.get("magic") in ("png", "jpeg", "gif") and (it.get("view_path") or it.get("path"))]
    # A saved-shell artifact was submitted = any non-image file/doc item carrying JShell text.
    file_present = any(_SHELL_RE.search(it.get("text") or "") for it in ok_items
                       if it.get("magic") in ("text", "pdf") or it.get("kind") in ("gdoc", "external_pdf"))

    # The ONLY lab-varying data — pure VALUES from the manifest (built by the jshell-lab skill at lab
    # creation, hand-authored on first grading). No detection logic lives here.
    manifest, mpath = _load_manifest(asmt.get("code"))
    steps = (manifest or {}).get("steps") or []
    expl = (manifest or {}).get("explanation") or {
        "max": _DEFAULT_EXPL_MAX, "base": 10, "quality_max": 5, "quality_tiers": [5, 4, 2, 0]}
    code_max = (manifest or {}).get("code_max", _DEFAULT_CODE_MAX)
    file_max = ((manifest or {}).get("file") or {}).get("max", _DEFAULT_FILE_MAX)
    expl_max = expl.get("max", _DEFAULT_EXPL_MAX)

    review_content = {
        "all_text": materials.get("all_text") or "",        # COMPLETE gathered content (body + every
                                                            # attachment: .txt/.jsh, PDF, gdoc, Office).
                                                            # Stage B reads THIS in full; feeds core.py
                                                            # ground_truth code_src. Nothing dropped.
        "reflection_text": materials.get("all_text") or "",  # WHY answers live in all_text (pasted OR in a
                                                            # linked gdoc) — feeds core.py ground_truth reflection.
        "body_text": materials.get("body_text") or "",       # just the Canvas text box (a subset of all_text)
        "items": items_out,                                 # every attachment, FULL text — the .txt/.jsh
                                                            # shell, the PDF, the gdoc each visible
        "file_present": file_present,                       # a saved-shell artifact (file/doc) submitted → File pts
        "images": images,                                   # result-screenshot paths (VIEW when judging)
        "steps": steps,                                     # manifest step list [{id,label,pts,expect}] — pure data
        "explanation": expl,                                # {max, base, quality_max, quality_tiers, questions}
        "rubric": {"code": code_max, "expl": expl_max, "file": file_max},
        "manifest": mpath if manifest else None,
    }

    # Manifest sanity (GRADING.md Part E: per-step pts MUST sum to code_max) — surfaced, never crashes.
    notes = []
    if steps:
        _sum = sum(s.get("pts", 0) for s in steps)
        if _sum != code_max:
            notes.append(f"⚠ MANIFEST: step pts sum to {_sum}, not code_max {code_max} — fix "
                         f"{mpath} before trusting the split.")
    _steps_line = ("; ".join(f'{s.get("id")}({s.get("pts")}) {s.get("label")}' for s in steps)
                   if steps else "NO manifest — read the assignment instructions' Step breakdown")

    return {
        "raw": 0, "posted": 0,            # placeholder — AI Stage B sets the final score
        "scores": {},
        "rubric_items": [("Code practice", code_max), ("Explanation", expl_max),
                         ("File submission", file_max)],
        # No comment field of any name — the engine authors no student-facing text
        # (GRADING §7.1). `comment_render` in Stage B is the ONE renderer.
        "review_content": review_content,
        "needs_review": notes + [
            "JSHELL LAB — AI Stage B scores from review_content (do NOT re-fetch / truncate §0Z):\n"
            f"  • Code ({code_max}, itemized per manifest step): {_steps_line}. Read the saved shell in "
            "`all_text` / `items` IN FULL; for EACH step judge whether the student DID it (typed the "
            "code; triggered + fixed any error the step asks for) and award that step's pts on "
            "SUBSTANCE, not form.\n"
            f"  • Explanation ({expl_max} = {expl.get('base', 10)} base answered + "
            f"{expl.get('quality_max', 5)} quality tier {expl.get('quality_tiers', [5, 4, 2, 0])}): "
            "read the WHY answers in `all_text` IN FULL — they may be pasted in the text box OR live in "
            "a linked Google Doc / PDF; BOTH are already in `all_text` / `items` (never re-fetch). Cite "
            "the specific answer per question.\n"
            f"  • File ({file_max}, all-or-nothing): `file_present`.\n"
            "  • Grade SUBSTANCE, not form: do NOT dock for a missing 'your own' example or a missing "
            "result screenshot when the work + understanding are evident (§4 / instructor policy)."],
        "finalizable": materials.get("status") == "ok",
    }
