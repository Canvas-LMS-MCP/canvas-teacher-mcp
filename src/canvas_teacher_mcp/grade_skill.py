#!/usr/bin/env python3
"""grade_skill — Stage-A driver for the `grade` skill.

A THIN launcher for the operational grade engine (`grade_engine.core`). It carries
NO grading logic — it only puts `.claude/code` on sys.path, imports the engine, and
runs `propose_rubric` / `grade`. Named `*_skill` so it is never confused with the
operational `grade_engine/` package. It lives HERE in `.claude/code/` — the `skills/grade/`
copy was deleted 2026-07-27 (two copies had drifted; the skill-side one was stale). The
procedure that drives it: `Course_Globals/.claude/skills/grade/SKILL.md`.

Usage:
  grade_skill.py <config.json> <code> --propose-only [--canvas-id N]
  grade_skill.py <config.json> <code> [--rubric rubric.json] [--canvas-id N]

  --propose-only  print the rubric proposal (Step 1a) and exit; grade nothing.
  --rubric FILE   grade with this rubric JSON ({"item": max, ...}); omit = grader default.
  --canvas-id N   pass the Canvas assignment id explicitly (else the engine name-matches LIVE).

NEVER posts. `grade` writes the report `{code}_grade.md` in `<output_dir>/grade_result/` and the
machine record `{code}_grade.json` in `<output_dir>/grade_result/json/` — one stem, two homes; a
resubmission round adds `_2nd`/`_3rd` to BOTH. POST is a separate instructor-gated step (the
post-gate harness enforces it). [note: the poster's filename is not spelled out here on purpose —
this GATHER driver never posts, and naming it would trip the post-gate hook's text scan.]
"""
import argparse
import json
import os
import sys

# This file LIVES in .claude/code/, so the code dir is its own directory. (Until 2026-07-27 it
# sat in skills/grade/ and walked "../../code"; after the move that pointed at a non-existent
# Course_Globals/code and only worked because Python auto-adds the script's own dir.)
_CODE_DIR = os.path.dirname(os.path.abspath(__file__))
if _CODE_DIR not in sys.path:
    sys.path.insert(0, _CODE_DIR)


# NOTE: there is no transport injection any more. `canvas_rest` takes a token string OR a
# CanvasSession, and `grade_engine.core._credential` picks whichever the school has, so a
# token-less school needs no `--cookie` flag, and none may be added.


def _print_result(res):
    if not isinstance(res, dict):
        print(res)
        return
    # surface the artifact paths the engine returns (name varies across engine versions)
    for k in ("grades_json", "report_md", "report", "grades", "out_json", "out_md"):
        if k in res and isinstance(res[k], str):
            print(f"{k}: {res[k]}")
    scalars = {k: v for k, v in res.items() if isinstance(v, (str, int, float, bool))}
    print(json.dumps(scalars, ensure_ascii=False, indent=2))


def _probe(config_path, code, canvas_id, uid):
    """DIAGNOSTIC: print what Canvas actually holds for ONE student's submission.

    Reads only. Grades nothing, scores nothing, writes nothing — this exists so a
    "student submitted nothing" verdict can be CHECKED against the raw record instead of
    trusted. It prints the top-level shape AND every submission_history attempt, because
    Canvas reports `attachments` for the CURRENT attempt only: a file uploaded in attempt 1
    disappears from the top level the moment attempt 2 is a text entry, and the engine —
    which reads `submission.get("attachments")` — then sees an attachment-less submission.
    """
    from .grading.core import (_load_config, _credential, _resolve_canvas_id,
                                   _default_canvas)  # engine-owned resolution, not re-implemented

    cfg = _load_config(config_path)
    course_id = cfg["course_id"]
    base_url = cfg["canvas_base_url"]
    cred = _credential(cfg, base_url)
    asmt_id = _resolve_canvas_id(_default_canvas, base_url, cred, course_id, code, canvas_id)
    subs = _default_canvas.fetch_submissions(base_url, cred, course_id, asmt_id) or []
    sub = next((s for s in subs if s.get("user_id") == uid), None)
    if sub is None:
        print(f"no submission row for uid {uid} on {code} (asmt {asmt_id})")
        return 1

    def _atts(d):
        return [(a.get("id"), a.get("display_name"), a.get("content-type"), a.get("size"))
                for a in (d.get("attachments") or [])]

    print(f"=== {code} (asmt {asmt_id}) · uid {uid} · {(sub.get('user') or {}).get('name')}")
    print(f"workflow_state : {sub.get('workflow_state')}")
    print(f"submission_type: {sub.get('submission_type')}")
    print(f"attempt        : {sub.get('attempt')}")
    print(f"submitted_at   : {sub.get('submitted_at')}")
    print(f"TOP body       : {((sub.get('body') or '')[:400])!r}")
    print(f"TOP url        : {sub.get('url')}")
    print(f"TOP attachments: {_atts(sub)}")
    hist = sorted(sub.get("submission_history") or [], key=lambda x: (x.get("attempt") or 0))
    print(f"--- submission_history ({len(hist)} attempt(s)) ---")
    for h in hist:
        print(f"  attempt {h.get('attempt')} | {h.get('submission_type')} | {h.get('submitted_at')}")
        print(f"    body : {((h.get('body') or '')[:400])!r}")
        print(f"    url  : {h.get('url')}")
        print(f"    atts : {_atts(h)}")
    # Comment attachments are a REAL submission channel: a student who writes "see attached
    # files" often attached them to the COMMENT, not the submission. The engine reads
    # submission attachments only, so those files are invisible to it — print them here.
    for c in (sub.get("submission_comments") or []):
        print(f"  comment[{c.get('author_name')}]: {(c.get('comment') or '')[:200]!r}")
        if c.get("attachments"):
            print(f"    COMMENT ATTACHMENTS: {_atts(c)}")
            for at in c["attachments"]:
                print(f"      url: {at.get('url')}")
    return 0


def main(argv):
    p = argparse.ArgumentParser(prog="grade_skill.py", description="Stage-A driver for the grade skill.")
    p.add_argument("config", help="path to grade_engine/config/<course>.json")
    p.add_argument("code", help="assignment code (internal label, e.g. A05)")
    p.add_argument("--propose-only", action="store_true", help="print rubric proposal and exit")
    p.add_argument("--rubric", help="rubric JSON file {item: max}; omit = grader default")
    p.add_argument("--canvas-id", type=int, default=None, help="explicit Canvas assignment id")
    p.add_argument("--grader", default=None,
                   help="explicit grader override (nb/gh/quiz/general) — AI/user-designated type; skips the classifier")
    p.add_argument("--force-round", dest="force_round", action="store_true",
                   help="overrule the derived round and use --round as given. The round is "
                        "normally CROSS-CHECKED: `core.next_round()` derives it from disk and the "
                        "run STOPS when the two disagree, or when the layout cannot be counted "
                        "(a pre-`_stageA` course reads as 'first grading' though it is posted). "
                        "Use this to redo an earlier round on purpose, or to name the round for a "
                        "course whose history predates the round register — deliberately, out loud.")
    p.add_argument("--round", default=None,
                   help="RESUBMISSION round suffix (2nd/3rd/…) → <code>_grade_2nd.md AND "
                        "json/<code>_grade_2nd.json. Use it when students re-submitted and you are "
                        "grading that round, so each round keeps its own report and its own record. "
                        "An error re-run keeps the base stem <code>_grade (the old files roll to temp first).")
    p.add_argument("--only", type=int, default=None,
                   help="single-student run: grade ONLY this Canvas user_id (uid). Gathers just that one.")
    p.add_argument("--audit", action="store_true",
                   help="AUDIT / double-check: re-run the engine on ALREADY-GRADED submissions too "
                        "(normally skipped) to verify a posted score against a fresh baseline. Writes ONLY "
                        "to {code}_grade_audit.md / {code}_grades_audit.json — NEVER the canonical report. "
                        "Never posts.")
    p.add_argument("--probe", type=int, default=None, metavar="UID",
                   help="DIAGNOSTIC (reads Canvas, grades nothing, writes nothing): dump ONE "
                        "student's RAW submission shape — submission_type, attempt, top-level "
                        "body/url/attachments, and EVERY submission_history entry's type / body / "
                        "url / attachments. Use when the engine reports a student as empty or STOPs "
                        "on them, to see what Canvas actually holds before changing any code. "
                        "Added 2026-07-28 after top-level `attachments` was found to miss files "
                        "that live only in an earlier attempt.")
    p.add_argument("--q-grader", default=None, dest="q_grader",
                   help="QUIZ only: the grader for EVERY question (gh/nb/jshell/general). A quiz "
                        "is a COMPOSITE — its questions are graded by the same type graders an "
                        "assignment uses. Omit = each question gets `general`. Never inferred: "
                        "until 2026-07-28 the type came from whether the STUDENT pasted a repo "
                        "link, so a code question missing its link became a silent ungraded essay.")
    p.add_argument("--q-graders", default=None, dest="q_graders",
                   help="QUIZ only: per-question exceptions as JSON {\"question name\": \"gh\"}, "
                        "overriding --q-grader. For a MIXED exam (algorithm essay + program code "
                        "in one quiz).")
    p.add_argument("--fetch-instructions", action="store_true", dest="fetch_instructions",
                   help="STEP 1 — fetch the assignment page (description + every embedded/linked "
                        "Google Doc/Slides) into <code>_instructions.md and STOP. Grades nothing, "
                        "touches no submission. This exists because the FIRST act of grading is the "
                        "AI READING the assignment (GRADING §0, SKILL RULE #1) — until now the "
                        "instructions were only saved as a side effect of a scoring run, i.e. AFTER "
                        "the engine had already picked a rubric. Read the file this writes, then run "
                        "the scoring pass with the rubric you took from it (--rubric).")
    p.add_argument("--grace-days", type=int, default=None, dest="grace_days",
                   help="late grace in days for THIS RUN (omit = none). Was the per-course config field "
                        "`expected_late_grace_days`, identical (2) in all nine courses — a policy, not a "
                        "course coordinate, so it moved to the run. Quizzes/exams force 0 regardless.")
    a = p.parse_args(argv)

    from .grading.core import propose_rubric, grade, fetch_instructions  # engine import

    if a.fetch_instructions:
        # STEP 1 — the page in front of you, nothing graded. Read the file it writes, take the
        # rubric FROM it, then run the scoring pass with --rubric.
        info = fetch_instructions(a.config, a.code, canvas_id=a.canvas_id)
        print(json.dumps(info, ensure_ascii=False, indent=2))
        print(f"\n⛔ NOTHING GRADED. Now READ: {info['instructions']}\n"
              f"   Then run the scoring pass with the rubric you took from it (--rubric).")
        return 0

    if a.probe is not None:
        return _probe(a.config, a.code, a.canvas_id, a.probe)

    if a.propose_only:
        prop = propose_rubric(a.config, a.code, canvas_id=a.canvas_id, grader_override=a.grader)
        print(json.dumps(prop, ensure_ascii=False, indent=2))
        return 0

    from .grading.core import RubricError, RoundError
    rubric = json.load(open(a.rubric)) if a.rubric else None

    # ⛔ THE ROUND IS CROSS-CHECKED, NEVER TAKEN ON TRUST (2026-08-05).
    # Two sources, and neither is allowed to decide alone:
    #   · `next_round()` derives it from disk — right when the layout is countable, confidently
    #     WRONG when it is not (a pre-`_stageA` course reads as "first grading" though it is
    #     posted, and that is the answer that overwrites).
    #   · `--round` is what a human remembers — and forgetting it is exactly what destroyed
    #     <course> A61's 13-student report on 2026-08-05.
    # So the derived value VERIFIES the stated one. Agreement runs; silence runs only where the
    # derivation is cross-checkable; anything else stops and asks. `--force-round` is the single
    # explicit way to overrule it (going back to redo an earlier round is legitimate —
    # Grade-Workflow "the round is NOT auto-selected" — it just has to be said out loud).
    # The check itself lives in `core.grade()`, which already owns `json_dir` — deriving that path
    # a second time here would be the private re-derivation `code/README.md` forbids.
    try:
        res = grade(a.config, a.code, rubric=rubric, canvas_id=a.canvas_id,
                    grader_override=a.grader, report_round=getattr(a, "round", None),
                    force_round=a.force_round, only_uid=a.only,
                    audit=a.audit, grace_days=a.grace_days,
                    q_grader=a.q_grader,
                    q_graders=json.loads(a.q_graders) if a.q_graders else None)
    except RubricError as e:
        # GRADING §0: the page publishes a rubric the engine could not parse. STOP — do NOT grade on
        # a fabricated default. Surface it so the instructor confirms the rubric, then re-run with --rubric.
        print(f"\n⛔ STOP — RUBRIC NOT RESOLVED: {e}\n"
              f"The assignment page states a rubric the engine could not parse into grader items.\n"
              f"Confirm the rubric with the instructor, then re-run with --rubric <file.json>.")
        return 3
    except RoundError as e:
        # The round decides which files this gather overwrites, so an unsettled round stops the run
        # BEFORE anything is fetched or written. Same shape as the rubric stop above.
        print(f"\n⛔ STOP — ROUND NOT SETTLED: {e}")
        return 4
    _print_result(res)
    # VIEW-GATE: record every artifact Stage A surfaced (answer_images/answer_docs) so the
    # poster can later verify the AI actually READ each one before posting (§0Z, enforced).
    gj = res.get("grades_json") if isinstance(res, dict) else None
    if a.audit:
        print("\n🔍 AUDIT run — wrote to _audit files only; canonical report untouched; "
              "no view-manifest (audit never posts). Compare the baseline against the posted score.")
    elif gj and os.path.exists(gj):
        try:
            from .grading.lib import view_gate
            # ONE MANIFEST PER ROUND. The name carried no round suffix, so a 3rd-round gather
            # overwrote the 2nd round's manifest and the 2nd round's finished record could no
            # longer be posted — its evidence list now belonged to a different gather.
            _rsfx = f"_{a.round}" if getattr(a, "round", None) else ""
            man = os.path.join(os.path.dirname(gj), f"{a.code}_view_manifest{_rsfx}.json")
            n = len(view_gate.build_manifest(gj, man))
            # STAMP THE PATH INTO the record — the poster READS this field. The old poster
            # re-derived the name by cutting the code out of the filename, so any other
            # naming produced a path that did not exist and the gate SILENTLY SKIPPED — a
            # bypass nobody added on purpose. A written-down path cannot be mis-guessed.
            # The manifest is a sibling of the record, so it lives in grade_result/json/ too.
            _g = json.load(open(gj))
            _g["view_manifest"] = os.path.abspath(man)
            with open(gj, "w") as _f:
                json.dump(_g, _f, indent=2, ensure_ascii=False, default=str)
            # …and into the ROUND REGISTER, so the render can look the manifest UP for this
            # round instead of guessing its name from `code` (see core.py "ROUND REGISTER").
            _rp = os.path.join(os.path.dirname(gj), f"{a.code}_rounds.json")
            if os.path.exists(_rp):
                _rg = json.load(open(_rp))
                _rk = (getattr(a, "round", None) or "").strip() or "base"
                if _rk in (_rg.get("rounds") or {}):
                    # folded (`~/…`) so the register reads on either Mac — see lib/paths.py
                    from .grading.lib import paths as _paths
                    _rg["rounds"][_rk]["manifest"] = _paths.fold(man)
                    with open(_rp, "w") as _f:
                        json.dump(_rg, _f, indent=1, ensure_ascii=False)
            print(f"view-manifest: {man} ({n} artifact(s) to VIEW before posting)")
        except Exception as e:  # noqa: BLE001 — manifest is a safety add-on, never block gather
            print(f"view-manifest: SKIPPED ({e})")
    print("\n⛔ DATA READY — NOT GRADED (0 judged). Stage A only GATHERED (diffs + screenshot URLs "
          "in review_content). Stage B = per student READ the diff + VIEW every screenshot, then "
          "judge + individual comment. Nothing posted.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
