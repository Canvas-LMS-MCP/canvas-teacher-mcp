#!/usr/bin/env python3
"""Stage-B PREPARE — the missing executable between Stage A and the render.

WHY THIS EXISTS
---------------
Three of the four grading stages were code and one was not:

    Stage A  ->  grade_skill.py + core.grade()          code
    Stage B  ->  (nothing)                              prose only   <-- this file
    render   ->  report_generator.py + 3 gates          code
    POST     ->  post_grades.py + the post-gate hook    code

Everything Stage B must do lived in GRADING.md (1100+ lines), skills/grade/SKILL.md, eight
GradingEngine contracts and three skills. Prose has no execution guarantee, so each session
re-derived the criteria and applied a slightly different bar. Measured outcome across one
14-assignment chapter (163 submissions): every rule with code was honoured 100% (the
view-gate caught 163/163, comment_render admitted no reason-less deduction), and the rules
that existed only in prose were not — the commit item came out as one of TWO values for
every single student, because the engine surfaced its signals and Stage B never read them.

So this module computes everything that is COMPUTABLE and hands back a skeleton whose only
empty slots are genuine judgment. It does not grade. It removes the excuse.

WHAT IS COMPUTABLE vs WHAT IS NOT
---------------------------------
computable (done here)              | judgment (left empty, for the AI)
-----------------------------------|-----------------------------------------------
commit-quality tier (§4F.6)         | is the correctness proof actually correct?
elab-vs-server contradiction        | is the trace mathematically sound?
passing-commit content              | does the write-up match the code?
late status, prior score            | is the elaboration the student's own?
per-item evidence shape             | how much a deduction is worth

The contradiction check is the clearest case: "I had no errors" next to N server-recorded
failing runs is a string test and a number comparison. It was done by hand 88 times in one
batch; it is four lines of code.

USAGE
    python3 -m grade_engine.stage_b <grade_result/json/<code>_grade.json> > <code>_authoring.json

Then fill the empty judgment slots and render. `report_generator` refuses to render if the
commit tier was not consulted (`commit_gate`), so this step cannot be skipped silently.
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import report_generator as RG  # noqa: E402
from lib import commit_inspect  # noqa: E402


def _difficulty(code):
    """`commit_difficulty` from `manifests/<code>.json` — same file `graders/gh` reads.

    Read directly rather than imported from the grader: this module is run as a script
    (`sys.path` points at the package dir), so importing `graders.gh` pulls in the package
    `__init__` and its relative imports break. Two four-line readers of the same one-key file
    is the cheaper trade; the FILE is the shared source of truth, not the function.
    """
    try:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "manifests", f"{code}.json")
        with open(p) as f:
            return (json.load(f) or {}).get("commit_difficulty")
    except Exception:  # noqa: BLE001 — absent is a valid state (needs_difficulty is then set)
        return None

# A write-up claiming a clean run. Deliberately narrow: these are assertions of NO error, not
# hedges. Matched against the student's own elaboration and cross-checked with the server's
# failing-run count — the engine states the contradiction as a fact and never scores it.
_NO_ERROR_RE = re.compile(
    r"(no|not any|didn.?t (have|run into)|never)\s+(real\s+)?"
    r"(error|bug|crash|issue|problem)s?\b"
    r"|error[- ]free"
    r"|without (hitting|any) (any )?(bugs?|errors?)"
    r"|on (my|the) first try"
    r"|worked (correctly|fine) (the )?first",
    re.I)


def _failing_runs(rc):
    """Server-recorded failing autograder runs before the pass (the un-fakeable half of the
    contradiction test — a run exists per push and its conclusion is GitHub's, not the
    student's)."""
    pc = (rc or {}).get("pass_commit") or {}
    if pc.get("prior_failing_runs") is not None:
        return pc["prior_failing_runs"]
    return sum(1 for r in ((rc or {}).get("run_history") or [])
               if r.get("conclusion") == "failure")


def _elab_text(rc):
    for k in ("elaboration", "elaboration_text", "answer_text", "all_text"):
        v = (rc or {}).get(k)
        if isinstance(v, str) and v.strip():
            return v
    return ""


def _resolve_record(record_path):
    """Prefer the durable Stage-A copy over the poster record at the same stem.

    `json/<code>_grade.json` holds the Stage-A gather until the render replaces it with the
    post-ready record — after which `commit_diffs`, `run_history` and the commit timestamps
    are gone from it. `json/<code>_stageA.json` is the copy the render never touches, so a
    re-grade (or an appeal months later) reads real evidence instead of an empty shell.
    Falls back to whatever was passed, so records written before the split still work.
    """
    p = os.path.abspath(record_path)
    d, base = os.path.dirname(p), os.path.basename(p)
    alt = os.path.join(d, base.replace("_grade", "_stageA", 1))
    if "_grade" in base and os.path.exists(alt):
        return alt
    return p


def merge_commit_tier(authoring_path, record_path=None, write=True):
    """Refresh ONLY the commit row of an existing authoring file from the engine's tier.

    For a batch already judged: the elaboration scores, reasons and quotes cost real reading
    and must not be thrown away because the commit rule changed. This rewrites the commit
    item — score, evidence, reason, and the `commit_quality` block the render gate looks for —
    and touches nothing else.

    It writes the ENGINE value. Raising above it is a Stage-B decision made afterwards, in the
    authoring file, and `report_generator.commit_tier_issues` then requires the reason.
    """
    data = json.load(open(authoring_path))
    rec_path = _resolve_record(record_path or authoring_path.replace(
        "_authoring.json", "_grade.json").replace(
        os.sep + data.get("code", ""), os.sep + "json" + os.sep + data.get("code", "")))
    rec = json.load(open(rec_path))
    by_uid = {str(s.get("user_id") or s.get("uid")): s for s in rec.get("students", [])}

    item = next((r["item"] for r in data.get("rubric", []) if "commit" in r["item"].lower()), None)
    if not item:
        return data, 0
    cmax = next(r["max"] for r in data["rubric"] if r["item"] == item)

    n = 0
    for stu in data.get("students", []):
        rc = (by_uid.get(str(stu["uid"])) or {}).get("review_content") or {}
        # RECOMPUTE from the raw gather rather than reading the verdict Stage A stored.
        # The stored verdict is only as current as the rule that produced it, so a rule fixed
        # after the gather would silently keep grading by the old one — which is exactly how a
        # 12-commit, 0-deletion history kept its "the code visibly failed and you repaired it"
        # credit after the prerequisite that denies it was added. Recomputing means a rule
        # change costs a re-merge (seconds, no network) instead of a re-gather.
        # `graders/gh` publishes the inspect result under `commits` in review_content (the key
        # `commit_inspect` is the RECORD-level name). Getting this wrong is silent — the code
        # falls back to the stored verdict and grades by the old rule while reporting success —
        # so read both names and SAY SO when neither is there.
        insp = rc.get("commits") or rc.get("commit_inspect")
        # REBUILD from the raw diffs when they are on hand. A stored inspect carries only the
        # per-commit fields that existed at gather time, so a NEW per-commit signal (e.g.
        # `interior_insert`) would read as absent for every student and the rule change would
        # quietly do nothing. The diffs are the source; re-derive from them.
        diffs = rc.get("commit_diffs")
        if isinstance(insp, dict) and isinstance(diffs, list) and diffs and insp.get("commits"):
            raw = [{"date": str(r.get("dt") or ""), "additions": r.get("additions"),
                    "deletions": r.get("deletions"), "message": r.get("message")}
                   for r in insp["commits"]]
            rebuilt = commit_inspect.inspect(raw, diffs)
            if rebuilt.get("has_content"):
                insp = rebuilt
        if isinstance(insp, dict) and insp.get("has_content"):
            cq = commit_inspect.commit_quality(
                insp, rc.get("pass_commit"), _difficulty(data.get("code", "")),
                rc.get("run_history"))
            cq["recomputed"] = True
        else:
            cq = rc.get("commit_quality")
            if isinstance(cq, dict):
                cq = dict(cq, recomputed=False)
        if not isinstance(cq, dict) or cq.get("tier") is None:
            continue
        score = round(cmax * cq["tier"], 2)
        score = int(score) if float(score).is_integer() else score
        stu["commit_quality"] = {
            "engine_score": score, "tier": cq["tier"], "row": cq.get("row"),
            "recomputed": cq.get("recomputed"),
            "n_repair_after_failure": cq.get("n_repair_after_failure"),
            "n_excluded_after_pass": cq.get("n_excluded_after_pass"),
            "pass_boundary_found": cq.get("pass_boundary_found"),
            "wide": cq.get("wide"), "effective_cycles": cq.get("effective_cycles"),
            "waived": cq.get("waived"), "needs_difficulty": cq.get("needs_difficulty"),
            "reasons": cq.get("reasons", []), "params": cq.get("params", {}),
        }
        stu["earned"][item] = score
        facts = " ".join(cq.get("reasons", []))
        # Below max => the render requires BOTH a per-item evidence block and a reason with a
        # fix clause. Both are built from the engine's own factual sentences, which is what
        # makes the deduction answerable when the student writes back.
        stu.setdefault("evidence", {})[item] = {"saw": facts, "score": score}
        if score < cmax - 0.01:
            stu.setdefault("reasons", {})[item] = facts
        else:
            stu.get("reasons", {}).pop(item, None)
        n += 1

    data["commit_gate"] = n > 0
    if write:
        with open(authoring_path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    return data, n


def prepare(record_path):
    """Stage-A record -> authoring skeleton with every mechanical verdict already filled."""
    record_path = _resolve_record(record_path)
    skel = RG.scaffold(record_path)
    rec = json.load(open(record_path))
    by_uid = {str(s.get("user_id") or s.get("uid")): s for s in rec.get("students", [])}

    commit_item = next((r["item"] for r in skel["rubric"]
                        if "commit" in r["item"].lower()), None)
    gated = False
    for stu in skel["students"]:
        src = by_uid.get(str(stu["uid"]), {})
        rc = src.get("review_content") or {}
        cq = rc.get("commit_quality") or {}
        pc = rc.get("pass_commit") or {}
        notes = []

        # 1. COMMIT TIER — the engine's advisory score for the commit row, plus the reasons
        #    behind it. Stage B may exceed it, but then `commit_tier_issues` demands a reason.
        if commit_item and cq.get("tier") is not None:
            cmax = next(r["max"] for r in skel["rubric"] if r["item"] == commit_item)
            stu["commit_quality"] = {
                "engine_score": round(cmax * cq["tier"], 2),
                "tier": cq["tier"], "row": cq.get("row"), "wide": cq.get("wide"),
                "effective_cycles": cq.get("effective_cycles"),
                "waived": cq.get("waived"), "needs_difficulty": cq.get("needs_difficulty"),
                "reasons": cq.get("reasons", []), "params": cq.get("params", {}),
            }
            stu["earned"][commit_item] = stu["commit_quality"]["engine_score"]
            gated = True
            if cq.get("needs_difficulty"):
                notes.append("⚠ no `commit_difficulty` for this assignment — tier computed "
                             "without a §4.4/§4.8 floor; confirm the carve-out")

        # 2. PASSING COMMIT — what actually turned it green, in the student's own numbers.
        #    §4F.3.1.5 requires this sentence in any commit deduction, so it is pre-stated.
        if pc.get("sha"):
            notes.append(f"passing commit {pc['sha']} \"{pc.get('message','')}\" "
                         f"(+{pc.get('additions')}/-{pc.get('deletions')}, "
                         f"content={pc.get('content')}, verdict={pc.get('verdict')}) "
                         f"after {pc.get('prior_failing_runs')} failing run(s)")

        # 3. ELAB vs SERVER — a claim of no errors against runs the server recorded as failed.
        #    A FACT, not a verdict: an incremental build that fails until complete is a
        #    legitimate answer, it just has to be the answer the student gives.
        nfail = _failing_runs(rc)
        text = _elab_text(rc)
        if nfail and text and _NO_ERROR_RE.search(text):
            m = _NO_ERROR_RE.search(text)
            notes.append(f"⚠ ELAB-vs-SERVER: write-up says \"{text[max(0, m.start()-40):m.end()+40].strip()}\" "
                         f"but the repository records {nfail} failing run(s) before the pass")

        # 4. AUTHENTICITY flags already computed by the server-time proctor (§4F.4).
        for f in ((rc.get("authenticity") or {}).get("flags") or []):
            notes.append(f"authenticity: {f}")

        # 5. QUIZ — the QUESTIONS are the rubric items, so every block above found nothing.
        #    A quiz record keeps its mechanical verdicts one level down, in
        #    `review_content.per_question[<att>:<question>]`, and blocks 1-4 look only at the
        #    student level: for an exam the skeleton reached Stage B with no tier, no passing
        #    commit and no authenticity, and the only way left to see them was to read the
        #    record with a private script — precisely what RULE #0e forbids. They are surfaced
        #    here as DATA, one entry per question. No score is derived: a question is worth its
        #    own published split (e.g. 35 autograder / 40 elaboration / 20 commit / 5 link),
        #    which lives in the question text, not in this record — inventing one here would be
        #    the grader default that GRADING §0 forbids.
        perq = rc.get("per_question") or {}
        if perq:
            qsum = {}
            for qname, q in perq.items():
                qcq = q.get("commit_quality") or {}
                qpc = q.get("pass_commit") or {}
                qau = q.get("authenticity") or {}
                qsum[qname] = {
                    "autograder": q.get("autograder_tests"),
                    "repo": q.get("repo"),
                    "commit_tier": qcq.get("tier"), "row": qcq.get("row"),
                    "wide": qcq.get("wide"),
                    "effective_cycles": qcq.get("effective_cycles"),
                    "n_repair_after_failure": qcq.get("n_repair_after_failure"),
                    "n_excluded_after_pass": qcq.get("n_excluded_after_pass"),
                    "commit_reasons": qcq.get("reasons", []),
                    "pass_commit": {k: qpc.get(k) for k in
                                    ("sha", "message", "additions", "deletions",
                                     "content", "verdict", "prior_failing_runs")},
                    "authenticity": {"verdict": qau.get("verdict"),
                                     "accepted": qau.get("accepted"),
                                     "repo_to_pass_min": qau.get("repo_to_pass_min")},
                    "elaboration_chars": len(q.get("elaboration") or ""),
                    "screenshots": len(q.get("screenshot_urls") or []),
                }
                for f in (qau.get("flags") or []):
                    notes.append(f"{qname} authenticity: {f}")
            stu["per_question"] = qsum

        if notes:
            stu.setdefault("engine_notes", []).extend(notes)

    skel["commit_gate"] = gated
    skel["_stage_b"] = {
        "prepared_from": os.path.abspath(record_path),
        "filled_by_engine": ["earned[commit]", "commit_quality", "per_question",
                             "engine_notes"],
        "left_for_judgment": ["earned[test/elab/link]", "reasons", "evidence.saw",
                              "evidence.quote", "notices"],
    }
    return skel


def elab_uplift(authoring_path, write=True):
    """Raise the elaboration item where the REPOSITORY proves work the write-up under-sells.

    Two adjustments, both additive to the judged score and both capped at the item max:

      +1  GENEROSITY — all three parts attempted and the score is below 12. The judged scale
          docked thin-but-present sections hard enough that a complete, honest, short answer
          landed in the same band as a missing one. A part that is there and does its job is
          worth its marks even when a stronger student wrote four times as much.

      +2  PROVEN DEVELOPMENT — the commit history is a real debugging history (logic row, at
          least three commits landing on a red build, spaced far enough apart to be separate
          attempts). This is the case the instructor asked to reward: a student who genuinely
          built and debugged the program but wrote a weak part 3. The process is evidenced on
          the server whether or not the prose reports it, and the item should not read as if
          no work happened. It is credit for what the repository shows, not for the writing.

    Deliberately mechanical: it applies the same test to every student from data already in
    the record, so nobody is lifted by mood. The reason string names which adjustment fired,
    so the student comment can say why.
    """
    data = json.load(open(authoring_path))
    item = next((r["item"] for r in data.get("rubric", [])
                 if "elaboration" in r["item"].lower()), None)
    cmax = next((r.get("max") for r in data.get("rubric", []) if r["item"] == item), 15)
    if not item:
        return data, 0
    n = 0
    for stu in data.get("students", []):
        cur = stu.get("earned", {}).get(item)
        if cur is None:
            continue
        cq = stu.get("commit_quality") or {}
        parts = stu.get("elab_parts_present")          # None => infer from the judged score
        all_three = parts if parts is not None else (cur >= 6)
        bumps, why = 0, []
        if all_three and cur < 12:
            bumps += 1
            why.append("+1 all three parts attempted (generosity pass)")
        if (cq.get("row") == "logic" and (cq.get("n_repair_after_failure") or 0) >= 3
                and (cq.get("effective_cycles") or 0) >= 1):
            bumps += 2
            why.append(f"+2 repository proves real debugging "
                       f"({cq.get('n_repair_after_failure')} commits landed on a failing build, "
                       f"{cq.get('effective_cycles')} separate attempts)")
        if not bumps:
            continue
        new = min(cmax, cur + bumps)
        if new == cur:
            continue
        stu["earned"][item] = new
        # The evidence block records the BASIS for the score; the render refuses to publish a
        # record whose basis disagrees with what was awarded (that mismatch is how a silent
        # hand-edit used to slip through). An uplift is part of the basis, so it goes here too.
        ev = (stu.get("evidence") or {}).get(item)
        if isinstance(ev, dict) and ev.get("score") is not None:
            ev["score"] = new
        stu.setdefault("elab_uplift", {}).update(
            {"from": cur, "to": new, "why": why})
        base = stu.setdefault("reasons", {}).get(item) or ""
        stu["reasons"][item] = (base.rstrip() + " " if base else "") + (
            "Adjusted upward on review: " + "; ".join(why) + ".")
        n += 1
    if write:
        with open(authoring_path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    return data, n


def main(argv):
    if not argv:
        print("usage: python3 -m grade_engine.stage_b <json/<code>_stageA.json>", file=sys.stderr)
        print("       python3 -m grade_engine.stage_b --merge-commit <authoring.json> <record.json>",
              file=sys.stderr)
        return 2
    if argv[0] == "--merge-commit":
        if len(argv) < 3:
            print("usage: --merge-commit <authoring.json> <record.json>", file=sys.stderr)
            return 2
        _, n = merge_commit_tier(argv[1], argv[2])
        print(f"✓ commit row refreshed for {n} student(s) in {os.path.basename(argv[1])}")
        return 0
    if argv[0] == "--elab-uplift":
        if len(argv) < 2:
            print("usage: --elab-uplift <authoring.json>", file=sys.stderr)
            return 2
        _, n = elab_uplift(argv[1])
        print(f"✓ elaboration raised for {n} student(s) in {os.path.basename(argv[1])}")
        return 0
    print(json.dumps(prepare(argv[0]), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
