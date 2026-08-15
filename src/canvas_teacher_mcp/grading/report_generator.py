#!/usr/bin/env python3
"""Deterministic grade-report generator.

AI provides WHAT (a grades JSON with judged scores/reasons/flags); this renders
HOW — the fixed report sections, the summary table, and the per-student comments
in ONE canonical format, every time. It replaces the ad-hoc per-session report
scripts (the source of format drift + the dropped-rubric-in-comment bug).

Comments are rendered via `lib.comment_render` — the SAME function the poster
uses — so the report comment == the posted comment, and §4.5.3 (rubric + reason)
is enforced at generation: a below-max row without a reason makes generation FAIL.

Emits BOTH: the report `<code>_grade.md` AND the post-ready `json/<same stem>.json`
(uid/score/comment/late) that the canonical poster consumes — same comment_render for
both, so report == posted. The json mirrors the report's own filename, so a `_2nd` round
keeps its own record. Optional coverage harness flags attachments that look unread.

Usage:
    python3 -m grade_engine.report_generator <authoring.json> [out.md]
    # or
    python3 grade_engine/report_generator.py <authoring.json> [out.md]

Input JSON schema:
    {
      "code": "03NB", "assignment_id": 3466672, "points_possible": 30,
      "due_at": "2026-06-22T06:59:59Z", "run_date": "2026-06-23",
      "rubric": [ {"item": "Link & access", "max": 6, "criteria": "..."}, ... ],
      "notices": ["free-text process note", ...],          # optional, header §1
      "students": [
        { "uid": 137919, "name": "Chrissa Huang",
          "earned":  {"Link & access": 6, "Notebook completeness": 9, ...},
          "reasons": {"Elaboration": "..."},               # required where earned<max
          "flags": [], "late": false, "waived": false, "held": false }
      ]
    }
"""
from __future__ import annotations

import json
import os
import re
import sys

from .lib.comment_render import render_comment, CommentError
from .lib import paths as _paths


def _last(name):
    return name.split()[-1] if name else ""


def _commit_item(rubric):
    """The rubric item the ENGINE scores from commit history (count + server-time
    authenticity), i.e. the git commit item — matched by name. None => not a git
    assignment, so the whole commit-reconciliation gate is inert (JShell/NB/etc.)."""
    for r in rubric:
        if "commit" in r["item"].lower():
            return r["item"]
    return None


def _commit_floor(s, commit_item):
    """engine_floor dict for render_comment (AUDIT tag only): the engine's commit
    signal score from the student's `commit_authenticity` block. Empty when no commit
    item / no engine score recorded. Never blocks — it only makes the engine value
    show as a tag next to Stage-B's decision."""
    if not commit_item:
        return {}
    ca = s.get("commit_authenticity")
    if not isinstance(ca, dict) or ca.get("engine_commit_score") is None:
        return {}
    return {commit_item: ca["engine_commit_score"]}


def _raw(stu, rubric):
    """Rubric total PLUS any instructor bonus. The bonus is deliberately OUTSIDE the rubric —
    inflating a rubric row to fake it would corrupt that row's meaning and the re-grade basis
    (GRADING §2.5 reuses the as-graded rubric) — and it MAY push the score past
    points_possible, which is the instructor's call to make."""
    if stu.get("held"):
        return None
    return (sum(stu["earned"].get(r["item"], 0) for r in rubric)
            + float(stu.get("bonus") or 0))


# ─────────────────────── QUIZ: per-question / per-attempt ───────────────────────
# A quiz is NOT an assignment with a bigger rubric. Canvas computes a quiz total from
# the score written into EACH question of EACH attempt (GRADING Part D §1.1–§1.2), so
# the render must carry `attempt × question` scores, never one student total. Two rules
# this code exists to enforce:
#   · question attribution is DATA — Stage A stamps `question_id` on every rubric row.
#     NEVER parse it out of the item name ("Q1 …" / "[No 3] …"): a renamed item would
#     silently re-attribute points.
#   · a question's score is COMPUTED here as the sum of that question's rubric rows, so
#     there is no hand-entered number to get wrong. A supplied `question_scores` is only
#     ever CROSS-CHECKED against the computed value — never trusted over it.
# Contract violations RAISE. Before this existed, a quiz whose authoring carried no
# per-question data rendered "fine" and the poster then refused it, which is what pushed
# a human into hand-summing the rubric rows into the authoring file (2026-07-29).

def _is_quiz(data):
    return (data.get("kind") == "quiz") or bool(data.get("quiz_id"))


def _question_ids(rubric):
    """Ordered distinct question_ids from the rubric. Raises if the quiz contract is
    unmet — every rubric row MUST name the question it belongs to."""
    missing = [r["item"] for r in rubric if not r.get("question_id")]
    if missing:
        raise CommentError(
            "QUIZ CONTRACT: rubric rows carry no `question_id` — "
            f"{len(missing)} of {len(rubric)} unattributed (e.g. {missing[0]!r}). "
            "Stage A must stamp `question_id` on every rubric row (read LIVE from Canvas: "
            "GET /courses/{cid}/quizzes/{quiz_id}/questions). The renderer will NOT guess "
            "attribution from item names, and a human must NOT hand-write question scores.")
    ids = []
    for r in rubric:
        qid = str(r["question_id"])
        if qid not in ids:
            ids.append(qid)
    if not ids:
        raise CommentError("QUIZ CONTRACT: no question_id found in the rubric.")
    return ids


def _question_scores(earned, rubric, qids):
    """{question_id: sum of that question's rubric rows}. COMPUTED, never taken from a
    human. Cross-checks that the per-question sums account for the whole rubric."""
    qs = {qid: 0 for qid in qids}
    for r in rubric:
        qs[str(r["question_id"])] += earned.get(r["item"], 0)
    total_by_q = sum(qs.values())
    total_by_item = sum(earned.get(r["item"], 0) for r in rubric)
    if round(total_by_q, 6) != round(total_by_item, 6):
        raise CommentError(
            f"QUIZ: per-question sums ({total_by_q}) != rubric sum ({total_by_item}) — "
            "a rubric row is attributed to a question that is not in the rubric.")
    return qs


def _quiz_attempts(s, rubric, qids):
    """Per-attempt [{attempt, question_scores, fudge_points:0}] for one student.

    Part D §2.1–§2.2: EVERY attempt is graded on its own merits and Canvas aggregates
    (average / highest / latest) — the grader never picks a winner, so an attempt left
    out is an attempt silently ungraded. `attempts_total` is stamped by Stage A from
    Canvas `submission_history`; if the authoring holds fewer attempts than that, REFUSE."""
    total = s.get("attempts_total")
    if total is None:
        raise CommentError(
            f"uid {s['uid']} ({s.get('name','?')}): quiz student has no `attempts_total` — "
            "Stage A must stamp it from Canvas submission_history. Without it a 2-attempt "
            "student is indistinguishable from a 1-attempt one and an attempt gets skipped.")
    atts = s.get("attempts")
    if not atts:
        # Single attempt is the length-1 case, not a special case: use the student's own
        # `earned` as attempt 1. More than one attempt REQUIRES per-attempt earned data.
        if total != 1:
            raise CommentError(
                f"uid {s['uid']} ({s.get('name','?')}): attempts_total={total} but the "
                "authoring has no per-attempt `attempts` list — grade EACH attempt "
                "(Part D §2.1); do NOT flatten several attempts into one view.")
        atts = [{"attempt": 1, "earned": s.get("earned", {})}]
    if len(atts) != total:
        raise CommentError(
            f"uid {s['uid']} ({s.get('name','?')}): attempts_total={total} but "
            f"{len(atts)} attempt(s) are graded — every attempt needs its own scores.")
    out = []
    for att in atts:
        if "attempt" not in att:
            raise CommentError(f"uid {s['uid']}: an attempts[] entry has no `attempt` number.")
        earned = att.get("earned")
        if earned is None:
            raise CommentError(
                f"uid {s['uid']} attempt {att['attempt']}: no `earned` — not graded. "
                "Every attempt is scored on its own merits (Part D §2.1).")
        computed = _question_scores(earned, rubric, qids)
        supplied = att.get("question_scores") or {}
        for qid, v in supplied.items():
            if round(float(v), 6) != round(float(computed.get(str(qid), 0)), 6):
                raise CommentError(
                    f"uid {s['uid']} attempt {att['attempt']} question {qid}: supplied "
                    f"question score {v} != rubric sum {computed.get(str(qid))}. The score "
                    "is COMPUTED from the rubric rows — remove the hand-written value or "
                    "fix the rubric scores; the renderer will not post a number that "
                    "disagrees with its own rubric.")
        out.append({"attempt": att["attempt"], "question_scores": computed, "fudge_points": 0})
    return out


def _quiz_tables(students, rubric, qids, pp, data):
    """§4 + §4b for a QUIZ: one row per student × attempt × question, then the aggregate.

    An assignment's §4 (one row per student) cannot show a quiz honestly — it hides both
    the question split and the attempts, so a 2-attempt student reads as a 1-attempt one
    and nobody can eyeball what the post will write. Here every row is exactly one PUT."""
    L = []
    by_q = {qid: [r for r in rubric if str(r["question_id"]) == qid] for qid in qids}
    qname = {}
    for qid in qids:
        nm = next((r.get("question_name") for r in by_q[qid] if r.get("question_name")), None)
        qname[qid] = f"{nm}({qid})" if nm else f"Q({qid})"
    widest = max(len(v) for v in by_q.values())

    L.append("## §4 — Grades (per attempt × per question — one row = one Canvas PUT)\n")
    L.append("| Student | uid | Att | Question (id) | "
             + " | ".join(f"item{i+1}" for i in range(widest)) + " | Q total |")
    L.append("|---|---|---|---|" + "---|" * (widest + 1))
    agg = {}
    for s in students:
        if s.get("held"):
            L.append(f"| {s['name']} | {s['uid']} | — | — | "
                     + " | ".join("—" for _ in range(widest)) + " | **HELD** |")
            continue
        for att in _quiz_attempts(s, rubric, qids):
            n = att["attempt"]
            src = next((a.get("earned", {}) for a in (s.get("attempts") or [])
                        if a.get("attempt") == n), s.get("earned", {}))
            for qid in qids:
                cells = [f"{r['item'].split(' - ')[-1]} {src.get(r['item'], '?')}/{r['max']}"
                         for r in by_q[qid]]
                cells += ["—"] * (widest - len(cells))
                L.append(f"| {s['name']} | {s['uid']} | {n} | {qname[qid]} | "
                         + " | ".join(str(c) for c in cells)
                         + f" | **{att['question_scores'][qid]}** |")
            agg.setdefault(s["uid"], {"name": s["name"], "att": {}})
            agg[s["uid"]]["att"][n] = sum(att["question_scores"].values())
    L.append("")

    # §4b — what CANVAS will show. We write every attempt; the quiz's own scoring_policy
    # decides the grade book value (Part D §2.2 — the grader never averages or picks).
    pol = data.get("scoring_policy")
    L.append("## §4b — Canvas aggregate (we write every attempt; Canvas picks)\n")
    natt = max((len(v["att"]) for v in agg.values()), default=1)
    L.append("| Student | uid | " + " | ".join(f"Att{i+1}" for i in range(natt)) + " | policy |")
    L.append("|---|---|" + "---|" * (natt + 1))
    for uid, v in agg.items():
        cells = [str(v["att"].get(i + 1, "—")) for i in range(natt)]
        L.append(f"| {v['name']} | {uid} | " + " | ".join(cells)
                 + f" | {pol or '⚠ scoring_policy NOT recorded by Stage A'} |")
    totals = [sum(v["att"].values()) / len(v["att"]) for v in agg.values() if v["att"]]
    if totals:
        L.append(f"\n_Graded: {len(agg)} student(s) · {sum(len(v['att']) for v in agg.values())} "
                 f"attempt(s) written._\n")
    if not pol:
        L.append("> ⚠ The quiz's `scoring_policy` is not in the authoring data, so this report "
                 "cannot state which attempt Canvas will keep. Stage A must record it "
                 "(GET /courses/{cid}/quizzes/{quiz_id} → `scoring_policy`).\n")
    return L


def generate(data):
    """Return the report markdown string. Raises CommentError if any below-max
    row lacks a reason (so a policy-invalid report can never be written)."""
    rubric = data["rubric"]
    commit_item = _commit_item(rubric)
    pp = data.get("points_possible") or sum(r["max"] for r in rubric)
    students = sorted(data["students"], key=lambda s: _last(s["name"]))
    code = data.get("code", "?")
    L = []
    L.append(f"# {code} — Grade report  (asmt {data.get('assignment_id','?')} · {pp} pts)\n")
    L.append(f"**Run:** {data.get('run_date','?')} · transport REST/{data.get('school','?')} "
             "· **NOT POSTED**\n")

    # §1 — flags / notices (header)
    L.append("## §1 — Flags / notices (instructor action before any post)\n")
    any_flag = False
    for s in students:
        if s.get("flags"):
            any_flag = True
            L.append(f"- **{s['name']}** ({s['uid']}): " + "; ".join(s["flags"]))
    for n in data.get("notices", []):
        any_flag = True
        L.append(f"- ⚠ {n}")
    if not any_flag:
        L.append("- (none)")
    L.append("")

    # §2 — rubric used.  A quiz shows WHICH QUESTION each row scores, with the live Canvas
    # question_id printed: the id is what the post actually writes to, so it belongs on the
    # page the instructor reads (a hand-copied id from a stale file is how the wrong question
    # gets scored — 2026-07-29).
    is_quiz = _is_quiz(data)
    qids = _question_ids(rubric) if is_quiz else []
    L.append("## §2 — Rubric used (= Canvas Grading block)\n")
    if is_quiz:
        L.append("| Question (id) | Item | Max | Criteria |")
        L.append("|---|---|---|---|")
        for r in rubric:
            L.append(f"| {r.get('question_name') or 'Q'}({r['question_id']}) "
                     f"| {r['item']} | {r['max']} | {r.get('criteria','')} |")
        L.append("")
        L.append("_Quiz: Canvas computes the total from each question's score, per attempt "
                 "(Part D §1.1–§1.2). Per-question scores are COMPUTED from the rows above._\n")
    else:
        L.append("| Item | Max | Criteria |")
        L.append("|---|---|---|")
        for r in rubric:
            L.append(f"| {r['item']} | {r['max']} | {r.get('criteria','')} |")
        L.append("")

    # §3 — late / waivers
    L.append("## §3 — Late / waivers\n")
    L.append(f"- due {data.get('due_at','?')}.")
    waived = [s["name"] for s in students if s.get("waived")]
    late = [s["name"] for s in students if s.get("late") and not s.get("waived")]
    L.append(f"- Waived (not shown in comment, §4.4): {', '.join(waived) if waived else 'none'}.")
    L.append(f"- LATE (Canvas whole-score penalty at post): {', '.join(late) if late else 'none'}.\n")

    # §4 — summary table
    if is_quiz:
        L.extend(_quiz_tables(students, rubric, qids, pp, data))
    else:
        L.append("## §4 — Grades (raw rubric sum; Canvas applies late penalty at post)\n")
        head = ("| Student | uid | " + " | ".join(f"{r['item']}/{r['max']}" for r in rubric)
                + " | Raw | Late |")
        L.append(head)
        L.append("|---|---|" + "---|" * (len(rubric) + 2))
        graded_raws = []
        for s in students:
            raw = _raw(s, rubric)
            if s.get("held"):
                cells = " | ".join("—" for _ in rubric)
                L.append(f"| {s['name']} | {s['uid']} | {cells} | **HELD** | notebook inaccessible |")
            else:
                graded_raws.append(raw)
                cells = " | ".join(str(s["earned"].get(r["item"], "?")) for r in rubric)
                lt = ("LATE" if (s.get("late") and not s.get("waived"))
                      else ("waived" if s.get("waived") else "ok"))
                L.append(f"| {s['name']} | {s['uid']} | {cells} | **{raw}** | {lt} |")
        if graded_raws:
            avg = sum(graded_raws) / len(graded_raws)
            held = sum(1 for s in students if s.get("held"))
            L.append(f"\n_Graded: {len(graded_raws)} (avg {avg:.1f}/{pp}) · Held: {held}._\n")

    # §5 — comments (rendered via shared comment_render → rubric + reasons, enforced)
    L.append("## §5 — Student comments (rubric + deduction reasons)\n")
    for s in students:
        raw = _raw(s, rubric)
        if not s.get("held") and raw == pp and not s.get("notes"):
            continue  # full marks and nothing to warn about → no comment
        ef = _commit_floor(s, commit_item)
        c = render_comment(rubric, s.get("earned", {}), s.get("reasons", {}),
                           points_possible=pp, held=s.get("held", False),
                           first_name=(s.get("name") or "there").split()[0], uid=s.get("uid", 0),
                           fmt="md", code_name=data.get("code", ""), notes=s.get("notes"),
                           engine_floor=ef, bonus=s.get("bonus"),
                           bonus_comment=s.get("bonus_comment"))
        L.append(f"#### {s['name']} — {'HELD' if s.get('held') else str(raw) + '/' + str(pp)}\n")
        L.append(c + "\n")
    L.append("_Comments carry the full rubric + a reason per below-max row "
             "(GRADING §4.5.3); no waiver/accommodation labels (§4.4). DRAFT — not posted._\n")
    L.append("**STATUS: NOT POSTED.** Resolve §1 → instructor 'go' → post-gate.\n")
    return "\n".join(L)


def grades_json(data):
    """Build the POST-ready grades.json from the authoring dict — PURE FUNCTION:
    score = sum(earned); comment = the SAME `comment_render` the report uses. Same
    authoring in => byte-identical grades.json out (the judgment is already frozen in
    `earned`/`reasons`; this step only renders + sums). Raises CommentError if a
    below-max row lacks a reason (so a policy-invalid grades.json cannot be written).
    Shape = what the canonical poster consumes (uid/score/comment/late fields).

    QUIZ vs ASSIGNMENT: driven by `kind` (stamped by Stage-A from the Canvas
    is_quiz_assignment attribute — no Canvas call here, offline). A quiz output ALSO
    carries `quiz_id`/`quiz_question_id` and, per student, `fudge_points: 0` — DATA the
    pure-transit poster sends so the total is the question score alone (§1.3; clears any
    stray fudge from a prior mistaken posted_grade). The poster re-verifies kind against
    Canvas (suspenders)."""
    rubric = data["rubric"]
    commit_item = _commit_item(rubric)
    pp = data.get("points_possible") or sum(r["max"] for r in rubric)
    is_quiz = _is_quiz(data)
    qids = _question_ids(rubric) if is_quiz else []
    students = []
    for s in data["students"]:
        held = s.get("held", False)
        # The POSTED score is the rubric sum PLUS the bonus — the same number the comment
        # shows. Computing it differently here from `_raw` above is how a report and its
        # posted grade drift apart, so both add the bonus.
        raw = None if held else (sum(s["earned"].get(r["item"], 0) for r in rubric)
                                 + float(s.get("bonus") or 0))
        ef = _commit_floor(s, commit_item)
        comment = render_comment(rubric, s.get("earned", {}), s.get("reasons", {}),
                                 points_possible=pp, held=held,
                                 first_name=(s.get("name") or "there").split()[0],
                                 uid=s.get("uid", 0), fmt="html", code_name=data.get("code", ""),
                                 notes=s.get("notes"), engine_floor=ef,
                                 bonus=s.get("bonus"), bonus_comment=s.get("bonus_comment"))
        late = "late" if (s.get("late") and not s.get("waived")) else "none"
        rec = {"uid": s["uid"], "score": raw, "comment": comment,
               "late_policy_status": late,
               "seconds_late_override": s.get("seconds_late_override")}
        if is_quiz:
            # A quiz carries NOTHING that resembles an assignment's single grade: the poster
            # sends per-attempt, per-question scores only (no posted_grade, no
            # late_policy_status). `fudge_points: 0` is DATA the poster transits so the total
            # is the question scores alone and any stray fudge from an earlier mistaken
            # posted_grade is cleared — never a way to grade (§1.3).
            # `score` stays on the record for the report/dry-run DISPLAY only.
            rec["fudge_points"] = 0
            rec["attempts"] = _quiz_attempts(s, rubric, qids)
            # NOT an omission: the lateness is already in the question scores. Canvas's late
            # policy works off ONE submission time and cannot deduct per attempt, so the engine
            # scores each attempt at its own timestamp with the quiz HOURS commit-late tier
            # (`GRADING.md` Part D). Restoring these fields would deduct twice for the same
            # lateness. The poster sends what it is given, so the decision has to be made here.
            rec.pop("late_policy_status", None)
            rec.pop("seconds_late_override", None)
        # AUDIT TAG (non-blocking): record where Stage-B's commit score deviates from the
        # engine signal, in EITHER direction (Stage-B is the decider; this is a trail).
        ca = s.get("commit_authenticity") if commit_item else None
        if isinstance(ca, dict) and ca.get("engine_commit_score") is not None:
            fin = s.get("earned", {}).get(commit_item)
            if fin is not None and float(fin) != float(ca["engine_commit_score"]):
                rec["commit_vs_engine"] = {
                    "engine": ca["engine_commit_score"], "final": fin,
                    "reason": s.get("reasons", {}).get(commit_item)}
        students.append(rec)
    out = {"school": data.get("school"), "canvas_base_url": data.get("canvas_base_url"),
           "course_id": data.get("course_id"), "assignment_id": data.get("assignment_id"),
           "kind": "quiz" if is_quiz else "assignment",
           "students": students}
    if is_quiz:
        out["quiz_id"] = data.get("quiz_id")
        out["quiz_question_id"] = data.get("quiz_question_id")
    return out


def coverage_issues(data):
    """HARNESS: every rubric item that LOST points must carry per-item evidence
    {saw, verdict, score}, and wherever evidence is present `evidence[item].score` MUST
    equal `earned[item]`. So a deduction is not a bare number — it shows WHAT was seen,
    the VERDICT, and the score it produced. Flags (=> FAIL, no output):
      - a BELOW-MAX item with no `saw` (= docked without recording a basis), and
      - `evidence.score != earned` on any item that carries evidence (= the recorded
        basis disagrees with the awarded score).
    It does NOT verify the `saw` text is TRUE — a human samples that.

    SCOPE — below-max rows only (narrowed 2026-08-01). It used to demand `saw` on EVERY
    row, full marks included. That was wrong twice over: GRADING §4.1-4.2 requires a
    documented basis for a DEDUCTION (a full-mark row has nothing to justify), and "the
    grader actually looked" is already proven by the VIEW-GATE, which checks real `Read`
    calls in the session transcript — so a `saw` line on an untouched row re-proved what
    the view-gate had already proven, at roughly 40% of the authoring volume. Full-mark
    rows MAY still carry evidence; when they do, the score cross-check still applies."""
    rubric = data["rubric"]
    issues = []
    for s in data["students"]:
        if s.get("held"):
            continue
        who = f"{s.get('name')} ({s['uid']})"
        ev = s.get("evidence") or {}
        earned = s.get("earned", {})
        for r in rubric:
            it = r["item"]
            e = ev.get(it)
            got = earned.get(it)
            below_max = got is not None and float(got) < float(r["max"]) - 0.01
            if not isinstance(e, dict) or not str(e.get("saw", "")).strip():
                if below_max:
                    issues.append(f"{who}: item '{it}' lost points ({got}/{r['max']}) but has NO "
                                  f"evidence.saw — record what you saw + verdict + score, then re-run.")
                continue        # full marks and no evidence recorded → nothing to justify
            if "score" not in e:
                issues.append(f"{who}: item '{it}' evidence has no `score`.")
                continue
            if abs(float(e["score"]) - float(earned.get(it, -999999))) > 0.01:
                issues.append(f"{who}: item '{it}' evidence.score={e['score']} ≠ earned="
                              f"{earned.get(it)} — the recorded basis disagrees with the awarded score.")
    return issues


def commit_tier_issues(data):
    """COMMIT-TIER GATE — Stage B may not silently ignore the engine's commit-quality tier.

    The failure this closes is specific and was measured: across a 14-assignment chapter the
    commit item came out as one of TWO values for every student, because the engine's tier was
    surfaced and never consulted. `coverage_issues` could not catch it — it only requires a
    reason for a BELOW-max row, and the un-consulted answer was always FULL marks.

    So: awarding MORE than the engine tier requires a written reason. Awarding the tier, or
    less, is already covered (a below-max row needs its reason anyway). Departing upward is
    legitimate and expected — a student who debugged locally and pushed in one burst looks
    identical to a copier in the diff, and only the write-up separates them — it just has to
    be SAID, which is what makes it auditable afterwards (`commit_vs_engine`).

    Fires only when Stage A actually produced a tier (`commit_gate` stamped by stage_b.prepare),
    so authoring files from before this gate, and courses whose engine has not re-run, are
    unaffected. Written down rather than re-derived, for the same reason the view-manifest path
    is written down: a path that is guessed is a gate that can be guessed away.
    """
    if not data.get("commit_gate"):
        return []
    commit_item = next((r["item"] for r in data.get("rubric", [])
                        if "commit" in r["item"].lower()), None)
    if not commit_item:
        return []
    issues = []
    for s in data.get("students", []):
        if s.get("held"):
            continue
        who = f"{s.get('name')} ({s['uid']})"
        cq = s.get("commit_quality")
        if not isinstance(cq, dict) or cq.get("engine_score") is None:
            issues.append(f"{who}: no `commit_quality.engine_score` — Stage B did not consult the "
                          f"commit tier. Re-run `stage_b.prepare` and author from its skeleton.")
            continue
        earned = (s.get("earned") or {}).get(commit_item)
        if earned is None:
            continue
        if float(earned) > float(cq["engine_score"]) + 0.01 and not str(
                (s.get("reasons") or {}).get(commit_item, "")).strip():
            issues.append(
                f"{who}: commit item {earned} exceeds the engine tier {cq['engine_score']} "
                f"({cq.get('row')}, cycles={cq.get('effective_cycles')}) with NO reason. "
                f"Awarding above the tier is allowed — say why (e.g. the write-up shows the "
                f"student ran the code locally), and it is recorded as commit_vs_engine.")
        # The ambiguous case must be DECIDED, not skipped. When the engine saw no repair in
        # the commits, the write-up is the only remaining evidence and somebody has to read
        # it — leaving it unread is what produced a whole chapter of identical commit scores.
        cmax = next(r["max"] for r in data["rubric"] if r["item"] == commit_item)
        m = s.get("elab_commit_match")
        if cq.get("row") == "assembly" and m not in ("corroborated", "claimed_only", "absent"):
            issues.append(
                f"{who}: the commits show no repair, so `elab_commit_match` must be set — "
                f"corroborated (errors visible in the commits) / claimed_only (described but "
                f"not visible) / absent (no error account). Read the write-up and decide.")
        elif m == "claimed_only" and float(earned) > float(cmax) - 0.99:
            issues.append(
                f"{who}: elab_commit_match=claimed_only but the commit item is {earned}/{cmax}. "
                f"A debugging account the history does not corroborate is worth credit, not "
                f"full marks — deduct 1 (the write-up quotes something only a real run "
                f"produces) or 2 (general debugging talk), and tell the student to commit the "
                f"broken state so the two records agree.")
    return issues


def _norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def regrade_floor_issues(data):
    """A RE-GRADE MAY NEVER LOWER AN EXISTING SCORE — the floor is what the student already has.

    The whole rule is one line: `final = max(new, entered_score)`.

    THE FLOOR IS CANVAS, NOT OUR FILES (2026-08-03). `entered_score` is the grade currently on
    the gradebook, pre-late-penalty — it already contains everything ever posted, whether this
    engine posted it or the instructor typed it in by hand. It needs no round ledger, no
    `attempt` bookkeeping, no walking N-1, N-2 … and no reconciling two generations of file
    name; the gradebook IS the ledger. This function used to reconstruct that number from
    disk and picked up the Stage-A record instead, whose `score` is a 0 placeholder, so every
    re-grade was compared against 0 and nothing was ever blocked.

    A student who was never graded has `entered_score = None` -> floor 0, and the gate is
    correctly silent. An ungraded intermediate attempt has no score anywhere, so it cannot
    raise the floor — which is the intended policy, not an oversight.

    Returns a list of blocking issues. To grade DOWN deliberately (correcting a mistaken
    over-award), set `allow_lower: true` on that student with a reason — a decision on the
    record, never an accident.
    """
    issues = []
    for s in data.get("students", []):
        floor = s.get("entered_score")
        if floor is None or s.get("allow_lower"):
            continue
        floor = float(floor)
        new = sum(float(v or 0) for v in (s.get("earned") or {}).values()) \
            + float(s.get("bonus") or 0)
        if new < floor - 1e-9:
            issues.append(
                f"{s.get('name','?')} ({s.get('uid') or s.get('user_id')}): re-grade would "
                f"LOWER the existing score {floor:g} → {new:g}. A re-grade never lowers a grade "
                f"(final = max(new, entered_score)). Raise it back to {floor:g}, or set "
                f"\"allow_lower\": true with a written reason if the first score was wrong.")
    return issues


def groundtruth_issues(data, gt):
    """GROUND-TRUTH QUOTE GATE (un-fakeable; replaces 'please read the code' prose). The completeness
    & elaboration items MUST carry an `evidence[item].quote` that is a real substring of the student's
    OWN work (engine-captured `code_src` + `reflection`). A lazy/generic saw cannot be quoted, and a
    fabricated quote is not found → render FAILS (no output). Pasting the real code is what forces you
    to actually SEE it (the forbidden built-in, the wrong algorithm) and score honestly. Context-free
    and non-brittle — unlike auto-blocking on a built-in, which false-fires on problems where sorting
    is the point. Only active when a ground_truth file exists (older/other flows unaffected)."""
    if not gt:
        return []
    rubric = data["rubric"]
    gate_items = [r["item"] for r in rubric
                  if any(k in r["item"].lower() for k in ("complet", "elaborat", "reflect"))]
    issues = []
    for s in data["students"]:
        if s.get("held"):
            continue
        g = gt.get(str(s["uid"])) or {}
        src = _norm(g.get("code_src", "") + "\n" + g.get("reflection", ""))
        if not src:
            continue  # nothing gathered (e.g. inaccessible notebook) — quote gate cannot apply
        ev = s.get("evidence") or {}
        who = f"{s.get('name')} ({s['uid']})"
        for it in gate_items:
            q = (ev.get(it) or {}).get("quote")
            if not q:
                issues.append(f"{who}: item '{it}' has no evidence.quote — paste a VERBATIM span of the "
                              f"student's own code/answer you actually read (ground-truth reading gate).")
            elif len(_norm(q)) > 8 and _norm(q) not in src:
                issues.append(f"{who}: item '{it}' quote NOT found in the student's work "
                              f"(fabricated or unread): {q!r}")
    return issues


def commit_reason_warnings(data):
    """NON-BLOCKING lint: a commit reason that claims 'single / one commit' while the engine
    recorded n>1 student commits is the Miguel A2-6 failure — the reason decoupled from the real
    (time/quality) basis. Warn so it's visible before posting; NEVER blocks (Stage-B is the
    decider). Best-effort: needs `commit_authenticity.n` in the authoring to compare against."""
    commit_item = _commit_item(data["rubric"])
    if not commit_item:
        return []
    pat = re.compile(r"single[ -]?(all-at-once )?commit|(only |a )?one commit|single commit", re.I)
    warns = []
    for s in data.get("students", []):
        n = (s.get("commit_authenticity") or {}).get("n")
        reason = (s.get("reasons") or {}).get(commit_item, "")
        if isinstance(n, (int, float)) and n > 1 and pat.search(str(reason)):
            warns.append(f"  ⚠ {s.get('name')} ({s.get('uid')}): commit reason says 'single/one "
                         f"commit' but the engine counted n={n} student commits — reword to the "
                         f"ACTUAL basis (time / no error-fix history), not count.")
    return warns


def forbidden_notes(data, gt):
    """NON-BLOCKING signal: built-in shortcuts the engine found in each student's answer code. Whether
    they are ALLOWED depends on the problem, so this is a pointer for Stage B to look at — not an
    auto-fail. Printed on render so a shortcut-based 'algorithm' cannot pass unseen."""
    notes = []
    for s in data.get("students", []):
        g = gt.get(str(s.get("uid"))) or {}
        fb = g.get("forbidden") or {}
        if fb:
            flat = "; ".join(f"{k}={','.join(v)}" for k, v in fb.items())
            notes.append(f"  ⚠ {s.get('name')} ({s.get('uid')}): built-in shortcuts in answer — {flat}")
    return notes


def _stage_a_meta(md_path):
    """Names, late flags and the rubric (item + max) parsed out of the Stage-A report.
    The Stage-A RECORD carries neither — it stores `user_id` and engine score keys only —
    so the sibling `.md` is where a scaffold can find them without a Canvas call (this
    module stays offline). Returns ({uid: {name, late}}, [{item, max}]); either may be
    empty, and the scaffold degrades to blanks rather than failing."""
    names, rubric = {}, []
    try:
        with open(md_path) as f:
            txt = f.read()
    except OSError:
        return names, rubric
    for line in txt.splitlines():
        if not line.startswith("|"):
            continue
        c = [x.strip() for x in line.strip("|").split("|")]
        if len(c) == 2 and c[1].replace(".", "").isdigit() and c[0] not in ("Item", "Max"):
            rubric.append({"item": c[0], "max": float(c[1]), "criteria": ""})
        elif len(c) >= 3 and c[1].isdigit():
            names[c[1]] = {"name": c[0], "late": "LATE" in line.upper()}
    return names, rubric


def scaffold(record_path):
    """Build the Stage-B authoring skeleton FROM ARTEFACTS THAT ALREADY EXIST — the
    Stage-A record, its sibling report, and the ground-truth file. Re-gathering is never
    needed, so this is usable in the middle of a batch whose Stage A is already done.

    The engine fills COORDINATES ONLY — uid, name, late, the rubric, and the engine's own
    baseline. Stage B fills every judgment: scores, the one-line `saw`, deduction reasons,
    and `evidence.quote`. The win is that a skeleton whose SHAPE is right by construction
    cannot fail the coverage gate, which used to be discovered only at render time, i.e.
    after every student had already been judged.

    ⛔ NEVER pre-fill anything taken from the STUDENT'S OWN TEXT — above all not
    `evidence.quote`. A first version of this function shipped `_quote_candidates`,
    sentences sliced out of the student's captured work, "so the quote is copied instead of
    retyped". That is a hole, not a convenience: the ground-truth gate passes a quote
    because a grader who never read the work could not have produced a verbatim sentence.
    Hand the grader machine-sliced verbatim sentences and the check becomes a tautology —
    the string is in the student's text because it was cut from it — and the whole
    assignment can be graded without opening it. Same anti-pattern `ViewGate.md` already
    warns about: "a null it can write is a gate it can switch off." A gate value the AI can
    generate is not a gate. Removed 2026-08-01. Retyping the quote is the mechanism, not
    the friction."""
    rec = json.load(open(record_path))
    code = rec.get("code", "grade")
    base = os.path.dirname(os.path.abspath(record_path))
    parent = os.path.dirname(base)
    # READ THE ROUND'S OWN GATHER REPORT (2026-08-04). This named only `<code>_grade.md`, which is
    # wrong twice over for a `--round 2nd` scaffold: it has no round suffix, so it reads round 1;
    # and `_grade*.md` is the FINAL report — Stage A writes the draft there and the render writes
    # the final over it, and the final's rubric table has a Criteria column that `_stage_a_meta`
    # does not parse as a rubric row. The result was a skeleton with an empty rubric and blank
    # names, `earned` with no keys, no commit tier merged, and `commit_gate` silently False —
    # nothing raised, Stage B just got the wrong shape. `<code>_stageA{sfx}.md` is the gather's
    # own copy: it carries the round in its name and NOTHING ever overwrites it (core.py: "Two
    # producers, two filenames"). No cross-round fallback — reading a DIFFERENT round's students
    # and rubric is worse than the blanks this function is documented to degrade to.
    _stem = os.path.splitext(os.path.basename(record_path))[0]
    _rsfx = ""
    for _tag in ("_stageA", "_grade"):
        if _tag in _stem:
            _rsfx = _stem.split(_tag, 1)[1]        # "" | "_2nd" | "_3rd" | "_audit"
            break
    md = next((p for p in (os.path.join(parent, f"{code}_stageA{_rsfx}.md"),
                           os.path.join(base, f"{code}_stageA{_rsfx}.md")) if os.path.exists(p)), "")
    meta, rubric = _stage_a_meta(md)
    # THE RECORD OUTRANKS THE REPORT MARKDOWN. `_stage_a_meta` recovers the rubric by parsing
    # the Item|Max table out of `<code>_grade.md`, which is all an assignment needs — but a
    # quiz row also needs its `question_id`, and a markdown table has none. Stage A now stamps
    # the real rubric on the record (core.py `_quiz_meta`), so prefer it whenever it is there:
    # otherwise scaffold hands Stage B a skeleton that `_question_ids` will refuse at render.
    _rec_rubric = rec.get("rubric")
    if _rec_rubric:
        rubric = _rec_rubric
    _is_quiz_rec = (rec.get("kind") == "quiz") or bool(rec.get("quiz_id"))

    students = []
    for s in rec.get("students", []):
        uid = str(s.get("user_id") or s.get("uid"))
        m = meta.get(uid, {})
        ev = {r["item"]: {"saw": "", "quote": "", "score": None} for r in rubric}
        # QUIZ: one `earned` block PER ATTEMPT, because Part D §2.1 grades each attempt on its
        # own merits and the poster writes each attempt separately. The flat `earned` above
        # stays as the summary the comment table renders from; `attempts` is what gets posted.
        _extra = {}
        if _is_quiz_rec:
            _n = s.get("attempts_total")
            _extra["attempts_total"] = _n
            _atts = [a.get("attempt") for a in (s.get("attempts") or []) if a.get("attempt")]
            if not _atts and _n:
                _atts = list(range(1, int(_n) + 1))
            _extra["attempts"] = [{"attempt": a,
                                   "earned": {r["item"]: None for r in rubric}}
                                  for a in _atts]
        students.append({
            "uid": int(uid), "name": m.get("name", ""),
            "earned": {r["item"]: None for r in rubric},
            **_extra,
            "reasons": {}, "evidence": ev,
            "_engine_baseline": s.get("scores", {}),
            # The grade already on the gradebook (pre-late-penalty) = the FLOOR for this
            # student. Carried onto the skeleton so `regrade_floor_issues` and Stage B both
            # SEE it; a floor nobody can read is a floor nobody applies.
            "entered_score": s.get("entered_score"),
            "flags": [], "late": bool(m.get("late")), "waived": False, "held": False,
        })
    out = {
        "code": code, "assignment_id": rec.get("assignment_id"),
        "points_possible": sum(r["max"] for r in rubric) or None,
        "due_at": "", "run_date": "",
        "rubric": rubric, "notices": [], "students": students,
    }
    # CARRY THE ROUND (2026-08-05). The round used to be expressed in THREE places that did not
    # know about each other: Stage A's `--round`, the authoring FILENAME (decoration — nothing
    # read it), and the render's argv[1]. Only the last one decided the output, so forgetting it
    # silently rewrote round 1: <course> A61's 13-student report became a 1-student file, with no
    # warning, because `out` fell back to the bare `{code}_grade.md`. The round is already known
    # HERE — `_rsfx` came from the record Stage A wrote — so it travels with the skeleton and the
    # render derives its own filename from it. `_audit` is excluded: it is a re-check run, never
    # a round (Grade-Workflow "WHICH ROUND NUMBER"), and its report is a side file by design.
    if _rsfx and _rsfx != "_audit":
        out["round"] = _rsfx.lstrip("_")
    if _is_quiz_rec:
        # `_is_quiz(data)` reads these off the AUTHORING file, not the record — without them
        # the renderer treats a quiz as an assignment and posts a `posted_grade`, which leaves
        # the quiz stuck at `pending_review` (post_grades `_put_quiz_scores`).
        out["kind"] = "quiz"
        out["quiz_id"] = rec.get("quiz_id")
    return out


def main(argv):
    if not argv:
        print("usage: report_generator.py <authoring.json> [out.md]  "
              "(writes <code>_grade.md AND json/<same stem>.json)\n"
              "       report_generator.py --scaffold json/<code>_grade.json  "
              "(prints an authoring skeleton; writes nothing)\n"
              "       report_generator.py --validate <authoring.json>  "
              "(runs the gates only; writes nothing)", file=sys.stderr)
        return 2

    if argv[0] == "--scaffold":
        if len(argv) < 2:
            print("usage: --scaffold json/<code>_grade.json", file=sys.stderr)
            return 2
        print(json.dumps(scaffold(argv[1]), indent=2, ensure_ascii=False))
        return 0

    if argv[0] == "--validate":
        # Same gates as the render, run WITHOUT producing output — so the shape can be
        # checked after the first student is authored instead of after the last one.
        if len(argv) < 2:
            print("usage: --validate <authoring.json>", file=sys.stderr)
            return 2
        vsrc = argv[1]
        vdata = json.load(open(vsrc))
        vbase = os.path.dirname(os.path.abspath(vsrc))
        vgt_path = os.path.join(vbase, f"{vdata.get('code','grade')}_ground_truth.json")
        vgt = json.load(open(vgt_path)) if os.path.exists(vgt_path) else {}
        issues = (coverage_issues(vdata) + groundtruth_issues(vdata, vgt)
                  + commit_tier_issues(vdata) + regrade_floor_issues(vdata))
        try:
            grades_json(vdata)          # exercises comment_render (reason + how-to-fix)
        except CommentError as e:
            issues.append(f"comment gate: {e}")
        if issues:
            print("✖ VALIDATE — would FAIL the render:", file=sys.stderr)
            for i in issues:
                print("  - " + i, file=sys.stderr)
            return 1
        print(f"✓ VALIDATE — {len(vdata.get('students', []))} student(s) pass all gates; "
              f"render will succeed.")
        return 0

    src = argv[0]
    data = json.load(open(src))
    base = os.path.dirname(os.path.abspath(src))
    # THE ROUND DECIDES THE FILENAME — NOT THE CALLER'S MEMORY (2026-08-05). This line used to
    # fall back to the BARE `{code}_grade.md` whenever argv[1] was omitted, so a round-2 render
    # overwrote round 1 in silence: <course> A61's 13-student report was replaced by a 1-student
    # file and the run reported success. The round is data — `scaffold` stamps it on the
    # skeleton from the record Stage A wrote — so the default name now carries it. argv[1] is
    # still honoured first: it stays the explicit override, and every existing call is unchanged.
    _round = str(data.get("round") or "").strip().lstrip("_")
    _rsfx_out = f"_{_round}" if _round else ""
    out = (argv[1] if len(argv) > 1
           else os.path.join(base, f"{data.get('code','grade')}_grade{_rsfx_out}.md"))

    # POSTER COORDINATES COME FROM THE GATHER, NOT FROM A HAND (2026-08-02).
    # `school` / `canvas_base_url` / `course_id` used to be copied into the authoring by the
    # AI. When the copy was forgotten the render still succeeded — with three nulls — and the
    # poster died at authentication on a finished, "post-ready" batch. There is nothing to
    # validate here: Stage A could not have fetched one submission without these, so it
    # records what it used and the render takes them. Authoring still wins if it sets them.
    _code = data.get("code", "grade")
    # ROUND-AWARE (2026-08-04). The list named only the BASE `<code>_stageA.json`, so a `--round
    # 2nd` render took its coordinates from round 1's gather — and where round 1 predates the
    # kept-gather file (chapter 5), nothing matched at all: school/canvas_base_url/course_id
    # stayed null, the render still reported success, and every post in the batch then died at
    # `CanvasSession(None)`. The round's OWN gather is the right source; its name follows the
    # report being written, so take the suffix from that.
    _orsfx = ""
    _ostem = os.path.splitext(os.path.basename(out))[0]
    if "_grade" in _ostem:
        _orsfx = _ostem.split("_grade", 1)[1]      # "" | "_2nd" | "_3rd" | "_late" | "_audit"
    if not all(data.get(k) for k in ("school", "canvas_base_url", "course_id")):
        for _sa in ([os.path.join(base, "json", f"{_code}_stageA{_orsfx}.json")] if _orsfx else []) + [
                    os.path.join(base, "json", f"{_code}_stageA.json"),
                    os.path.join(base, "json", f"{_code}_stageA_audit.json"),
                    os.path.join(base, "json", f"{_code}_grade_audit.json"),
                    os.path.join(base, "json", f"{_code}_grades.json")]:
            if not os.path.exists(_sa):
                continue
            try:
                _rec = json.load(open(_sa))
            except (OSError, ValueError):
                continue
            for _k in ("school", "canvas_base_url", "course_id"):
                if not data.get(_k) and _rec.get(_k):
                    data[_k] = _rec[_k]
            if all(data.get(k) for k in ("school", "canvas_base_url", "course_id")):
                print(f"poster coords ← {os.path.basename(_sa)} "
                      f"(school={data['school']}, course_id={data['course_id']})")
                break

    gt_path = os.path.join(base, f"{data.get('code','grade')}_ground_truth.json")
    gt = json.load(open(gt_path)) if os.path.exists(gt_path) else {}

    for n in forbidden_notes(data, gt):   # non-blocking signal — verify these are allowed for the problem
        print(n, file=sys.stderr)
    for w in commit_reason_warnings(data):  # non-blocking — commit reason vs engine commit count
        print(w, file=sys.stderr)

    cov = (coverage_issues(data) + groundtruth_issues(data, gt) + commit_tier_issues(data)
           + regrade_floor_issues(data))
    if cov:
        print("✖ RENDER FAIL — coverage/ground-truth gate; NO output written:", file=sys.stderr)
        for c in cov:
            print("  - " + c, file=sys.stderr)
        return 1

    try:
        md = generate(data)
        gj = grades_json(data)
    except CommentError as e:
        print(f"FAILED — policy violation (below-max row without a reason): {e}", file=sys.stderr)
        return 1

    # NOTHING IS WRITTEN UNTIL EVERY GATE HAS PASSED. The report used to be written here, before
    # the view-manifest was resolved, so a render that failed the manifest check still left a
    # finished-looking `<code>_grade.md` on disk next to no record — output that says the grading
    # is done when it is not. Both files are written together at the end or neither is.
    # The machine record MIRRORS the report's own filename: same stem, `.json` instead of `.md`,
    # in the report dir's `json/` subfolder (grade_result/json/). Deriving the stem from `out` is
    # what carries a round suffix across the render — a `_2nd` round then keeps its OWN postable
    # record. (This used to hardcode `<code>_grades.json`, so every round collapsed onto one file
    # and round 2's render replaced round 1's posted record. Stage A suffixed both files; the
    # render silently undid it.)
    _stem = os.path.splitext(os.path.basename(os.path.abspath(out)))[0]
    _gdir = os.path.join(os.path.dirname(os.path.abspath(out)), "json")
    os.makedirs(_gdir, exist_ok=True)
    gpath = os.path.join(_gdir, _stem + ".json")
    # CARRY THE VIEW-MANIFEST POINTER ACROSS THE OVERWRITE. This render REPLACES the
    # Stage-A file at the same path, so without this the manifest path Stage A stamped is
    # destroyed and the poster (fail-closed) blocks every post. Take it from the file being
    # replaced; fall back to the sibling manifest the naming convention puts here.
    # The manifest is a MACHINE artifact, so it lives beside the machine record
    # (`<out>/json/<code>_view_manifest.json`). The parent directory is checked too: runs made
    # before the json/ split put it next to the report, and a transition must not silently lose
    # the pointer (losing it blocks every post — fail-closed).
    _code_stem = data.get("code", "grade")
    _jdir = os.path.dirname(gpath)
    # ROUND REGISTER FIRST — ask Stage A which manifest belongs to the round being rendered,
    # instead of gluing the name together from `code`. Gluing is what broke on 2026-08-02: an
    # authoring whose `code` had been hand-set to `31_late` produced `31_late_view_manifest`,
    # a name Stage A never wrote, so the render found nothing, said so in one line, and
    # "succeeded" — while the post was already doomed. Any round in the register is fair game
    # (going back to a 2nd round must stay possible); what cannot happen is a path Stage A
    # never produced.
    _reg_mf = None
    _regp = os.path.join(_jdir, f"{_code_stem}_rounds.json")
    if os.path.exists(_regp):
        try:
            _reg = json.load(open(_regp))
            # PORTABLE (2026-08-05). Both the register's `record` and its `manifest` are
            # values written on whichever machine last gathered, so they may name a home
            # this one does not have. Re-root them on the way in (lib/paths.resolve) —
            # otherwise the record never matches and the manifest never opens.
            _me = os.path.realpath(gpath)
            for _rk, _rv in (_reg.get("rounds") or {}).items():
                if (os.path.realpath(_paths.resolve(_rv.get("record", ""))) == _me
                        and _rv.get("manifest")):
                    _reg_mf = _paths.resolve(_rv["manifest"])
                    break
        except (OSError, ValueError):
            _reg_mf = None
    # ROUND-SUFFIXED SIBLING FIRST (2026-08-05). `{Code}_view_manifest*` IS round-separated
    # (Grade-Workflow "WHICH ARTIFACTS CARRY THE SUFFIX"), but this list named only the bare
    # name — so a `--round 2nd` render could reach its own manifest ONLY through the register.
    # Where the register predates the feature (chapter 5/6 here), nothing matched. That gap was
    # harmless while `_prev_mf` swallowed everything below; closing `_prev_mf` (same day) opens
    # it, so the suffixed candidate goes in FIRST. `_orsfx` is already computed at the top.
    _sib = _reg_mf or next(
        (p for p in ([os.path.join(_jdir, f"{_code_stem}_view_manifest{_orsfx}.json")] if _orsfx else [])
                    + [os.path.join(_jdir, f"{_code_stem}_view_manifest.json"),
                       os.path.join(os.path.dirname(_jdir), f"{_code_stem}_view_manifest.json")]
         if os.path.exists(p)), os.path.join(_jdir, f"{_code_stem}_view_manifest.json"))
    _prev_mf = None
    if os.path.exists(gpath):
        try:
            _prev = json.load(open(gpath))
            # resolve: the previous record may have been written on the other machine.
            _prev_mf = _paths.resolve(_prev.get("view_manifest")) if isinstance(_prev, dict) else None
        except Exception:  # noqa: BLE001 — an unreadable previous file must not block the render
            _prev_mf = None
    # A DEAD PATH IS NOT A MANIFEST (2026-08-05). `_prev_mf` was taken UNCHECKED, so a previous
    # record carrying a path that no longer resolves — a record written on the other machine,
    # whose absolute path names a home this machine does not have — became `_mf`. It is a
    # non-empty string, so the "no manifest ⇒ RENDER FAIL" guard below did not fire: the freeze
    # threw FileNotFoundError, printed one SKIPPED line, and the render reported success on a
    # record with no proof (<course> A61, 2026-08-05). Existence is the same requirement `_sib`
    # already had; the fallback chain underneath is what should answer when it fails.
    _mf = (_prev_mf if _prev_mf and os.path.exists(_prev_mf) else None) \
        or (_sib if os.path.exists(_sib) else None)
    if _mf:
        gj["view_manifest"] = _paths.fold(_mf)   # stored `~/…` — portable across machines
        # ── FREEZE THE PROOF-OF-READING (2026-08-01) ────────────────────────────────
        # The view-gate measures reading by parsing the CURRENT session transcript, so
        # until now "post-ready" silently expired with the conversation: six assignments
        # graded on 2026-08-01 could not be posted from a later session even though the
        # record, the report and the manifest were all sitting on disk. The reading is
        # permanent; only the EVIDENCE of it was volatile.
        #
        # The render is the right moment to capture it: it runs in the same session as the
        # reading and immediately after it. Verify against the live transcript and, only if
        # nothing is unread, write `<code>_view_verified.json` beside the record and stamp
        # its path in (same DATA-not-guess rule as `view_manifest`).
        #
        # Best-effort by design: a failure here must never block a render (the poster still
        # falls back to the live transcript, which is the pre-existing behaviour). What it
        # must never do is stamp a proof for a gate that did not pass — verify_and_stamp
        # writes nothing when anything is unread, and the AI can never supply this field.
        try:
            from .lib import view_gate as _vg
            _vpath0 = os.path.join(_gdir, (_stem.replace("_grade", "_view_verified")
                                           if "_grade" in _stem else _stem + "_view_verified")
                                   + ".json")
            # CARRY THE PROOF FORWARD (2026-08-02). A re-render used to re-earn the reading from
            # the live transcript, so editing one sentence in a later session demanded that every
            # artifact be opened again — and if it wasn't, a finished grading silently lost its
            # post-readiness. The proof is bound to the GATHER (run_id), not to the conversation:
            # if the stored one still covers this manifest, the files have not changed and the
            # reading it records is still true. Re-verifying would only re-ask the same question.
            _carried = os.path.exists(_vpath0) and not _vg.check_verified(_mf, _vpath0, gpath)
            if _carried:
                gj["view_verified"] = _paths.fold(_vpath0)
                print(f"view-verified: carried forward ({os.path.basename(_vpath0)} still covers "
                      f"this gather — no re-reading needed)")
            _tr = None if _carried else _vg.find_transcript(_gdir)
            if _carried:
                pass
            elif not _tr:
                # Say so out loud. A silent no-op here is how a gate quietly stops working:
                # the render looks successful, the record carries no proof, and the failure
                # only surfaces at POST time in a session that can no longer produce one.
                print("view-verified: NOT stamped — no session transcript found; the post will "
                      "need --transcript, or a re-render from the session that read the files")
            else:
                _vpath = os.path.join(_gdir, (_stem.replace("_grade", "_view_verified")
                                              if "_grade" in _stem else _stem + "_view_verified")
                                      + ".json")
                _unread, _written = _vg.verify_and_stamp(_mf, _tr, _vpath, grades_path=gpath)
                if _written:
                    gj["view_verified"] = _paths.fold(_written)
                    print(f"view-verified: {_written} (proof frozen — postable from any session)")
                else:
                    print(f"view-verified: NOT stamped — {len(_unread)} of "
                          f"{len(json.load(open(_mf)).get('artifacts', []))} artifact(s) not read "
                          f"in this session; post falls back to the live transcript")
        except Exception as e:  # noqa: BLE001 — proof capture is additive; never block a render
            print(f"view-verified: SKIPPED ({e})")
    # NO MANIFEST ⇒ RENDER FAILS. It used to print a warning and write the record anyway, so a
    # render could report success on a batch the poster would refuse — which is what happened
    # on 2026-08-02: 25 assignments rendered "OK", and every one of them was blocked at post.
    # GRADING RULE #0P says post-ready IS a successful render; a render that knows the post
    # cannot proceed has no business succeeding. Failing here also removes the temptation to
    # repair the mismatch by hand afterwards, which is the move that turns a gate into decoration.
    if not _mf:
        print(f"✖ RENDER FAIL — no view-manifest for this record ({os.path.basename(gpath)}); "
              f"the poster would block (§0Z). NO output written.\n"
              f"  Stage A registers one manifest per round in "
              f"{os.path.basename(_regp)} — this record is not in it. Either render the record "
              f"Stage A actually produced, or re-run Stage A for this round.", file=sys.stderr)
        return 1
    # NO ROSTER GUARD HERE (tried and removed the same day, 2026-08-05). It compared the names in
    # the report already on disk against the ones about to be written and failed on a mismatch —
    # but that only ESTIMATES whether two runs are the same grading. A 3rd round is normally a
    # SUBSET of the 2nd (the same students, re-read), so the check passed and the 2nd round was
    # overwritten anyway. The round belongs upstream, where it is known as a fact: Stage A derives
    # it from disk, cross-checks it against `--round`, and stamps it onto the authoring. A guess
    # standing behind a fact is not a second line of defence, it is noise that looks like one.
    with open(out, "w") as f:
        f.write(md)
    print(f"wrote {out}")
    with open(gpath, "w") as f:
        json.dump(gj, f, indent=1, ensure_ascii=False)
    print(f"wrote {gpath} (view_manifest → {_mf})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
