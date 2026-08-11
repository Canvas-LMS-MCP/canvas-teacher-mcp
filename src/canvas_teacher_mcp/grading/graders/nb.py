"""Jupyter Notebook / Colab grader — the GATHERER (GRADING.md Part C).

The engine GATHERS structured NB evidence; the AI (Stage B) SCORES it — like general.py, and NEVER
auto-scores by mere link/screenshot presence (the old crude nb.py is removed). Per student, via
attachments.read():
  - att["notebook"]{cells, revisions(pinned)}  -> nb_inspect.resolve_tasks (per-problem REGION
    completeness, GRADING Part C §2) + revision_progression/score_revision (process, §3)
  - att["all_text"] (body)                     -> reflection text (§4; location per the page)
  - att["has_visual"]                          -> revision-history screenshot evidence
It emits `review_content` (per-problem region evidence + revision metrics + reflection) + a
PROVISIONAL raw; `needs_review` tells the AI to finalize comp (per-problem 1/N) / rev / refl.

Rubric keys: comp / rev / refl. The MANIFEST `grade_engine/manifests/<code>.json`
(`[{anchor, type, prompt}]`, built once by reading the template — skills/nb-homework-create) drives
resolve_tasks; no manifest -> the AI reads the cells directly for completeness.
"""
import json
import os

from ..lib import attachments as att_mod
from ..lib import nb_inspect

# What this grader emits on EVERY normal grade (lib/contract.py). Declared, not inferred.
#
# `needs_review` was BUILT here all along under the name `review_notes` — 15+ instructor lines
# (wrong submit format, shared as Viewer, BURST paste check, unexecuted cells, notebook not
# accessible) — and NOTHING anywhere read that name. Every NB assignment ever graded discarded
# them silently. Renamed to the contract's name 2026-07-28; the content was already right.
# Unconditional: the gatherer always writes a base "NB GATHERER: …" line.
PRODUCES = frozenset({"review_content", "rubric_items", "earned", "needs_review"})

_MANIFEST_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "manifests")

# NB authenticity / effort thresholds (executionInfo model — GRADING Part C §4b). NAMED + surfaced in
# review_content["params"] and needs_review so every grade is explainable later ("with THIS threshold,
# the value was X"). Tune here, in ONE place; policy references these names.
NB_BURST_SEC = 2            # a cell-to-cell gap < this (seconds) = "instant" run (no think time)
NB_BURST_THRESHOLD = 0.50   # ≥ this FRACTION of gaps instant (and ≥ NB_BURST_MIN_CELLS run) → paste flag
                            # (default 0.50 from 2026-07-04; LabCh3 was graded at 0.60 and left as-is —
                            #  no student was near either value: max observed burst was 28%.)
NB_BURST_MIN_CELLS = 10     # fewer executed cells → the burst fraction is not meaningful, so no flag
NB_GAP_CAP_SEC = 300        # each cell-to-cell gap is capped here in active_min (idle > 5min excluded)
NB_ACTIVE_FULL_MIN = 45     # (legacy, informational) active work minutes for full effort — superseded by T-ramp
# TIME-PLAUSIBILITY RAMP (GRADING §4b.1). T = 0.4 × E, E = expected genuine active-min for THIS lab
# (authored per-lab in the manifest `expected_active_min` — content-based, NOT the class median). A
# fast student ramps DOWN smoothly on both comp+rev; nothing snaps to 0 (that would double-count time).
NB_T_COEF = 0.4             # T = NB_T_COEF × E  (below T + high completion = implausibly fast)
NB_COMP_FLOOR = 0.5         # completeness ramp floor (objective cells → lightly time-adjusted)
NB_REV_FLOOR = 0.3          # revision ramp floor (primary process/time item → drops more, never to 0)
NB_RAMP_TRIGGER_FRAC = 0.8  # ramp applies only when completion ≥ this (few-cells-so-fast = honest incomplete)


def _load_manifest(code):
    p = os.path.join(_MANIFEST_DIR, f"{code}.json")
    try:
        with open(p) as f:
            return json.load(f), p
    except Exception:  # noqa: BLE001 — no manifest is fine (the AI reads cells directly)
        return None, p


def _extract_reflections(cells):
    """The student's IN-NOTEBOOK per-section reflection answers — the real reflection work
    that the submission body (a bare Colab link) does NOT contain. A reflection PROMPT is a
    markdown cell carrying an `@anchor:S<n>R` marker; the student's ANSWER is the paired
    `@answer:S<n>R` cell (or the next non-anchor markdown cell when they typed under the
    prompt). Returns {section_int: answer_str}; EMPTY when the notebook has no @anchor
    reflection prompts (older labs put reflections in the body → fall back to all_text).
    Without this the engine scored Reflection off the body length (a 85-char link) and the
    quote-gate had nothing to enforce — the recurring 'engine never read the reflection' gap.

    TWO ANCHOR CONVENTIONS, both matched (2026-08-08). The original one is per-section —
    `@anchor:S3R`, a reflection at the end of every section. `nb-homework-create` now stamps a
    SINGLE end-of-notebook reflection instead, `@anchor:r6 type=reflect`, and this function's
    regex only knew the first shape: on <course> NB21 and NB22 it therefore returned {} for all
    23 submissions, the code fell through to `all_text`, and `all_text` on those labs is the
    bare Colab link — so a 10-point rubric item had no text behind it and every reflection had
    to be pulled out of the notebooks by hand. Matching both shapes costs one alternation.
    A lab with NO reflection anchor of either kind still returns {} and still falls back, which
    is the correct behaviour for the eight manifests here that declare no reflect task at all."""
    import re as _re
    out = {}
    for i, c in enumerate(cells):
        if c.get("cell_type") != "markdown":
            continue
        src = "".join(c.get("source") or []) if isinstance(c.get("source"), list) else str(c.get("source") or "")
        #  legacy  @anchor:S3R            -> section 3's reflection
        #  current @anchor:r6 type=reflect -> the notebook's single reflection (section 6)
        m = _re.search(r"@anchor:S(\d+)R", src) or _re.search(r"@anchor:[rR](\d+)\b", src)
        if not m:
            continue
        ans = ""
        for j in range(i + 1, min(i + 3, len(cells))):
            raw = "".join(cells[j].get("source") or []) if isinstance(cells[j].get("source"), list) else str(cells[j].get("source") or "")
            if "@anchor" in raw:
                break
            cleaned = _re.sub(r"<!--.*?-->", "", raw).strip()
            # Strip the template's own placeholder so an untouched cell reads as EMPTY rather
            # than as an answer. The wording differs per lab — "write your answer here" on the
            # older ones, "write your takeaway here — do not delete this cell" on the current
            # reflection cell — and a student may leave it sitting under a real answer.
            cleaned = _re.sub(r"\*?\(\s*write your (?:answer|takeaway)[^)]*\)\*?", "", cleaned).strip()
            if cleaned:
                ans = cleaned
                break
        out[int(m.group(1))] = ans
    return out


def default_rubric(points_possible):
    """Lab Ch3 instruction rubric — 4 items: Link&access + Completeness + Revision + Reflection.
    Proportions 20/30/30/20 (mirrors the instructor's NB rubric, e.g. 03NB's 6/9/9/6)."""
    if points_possible <= 0:
        return {"link": 0, "comp": 0, "rev": 0, "refl": 0}
    link = round(points_possible * 0.2)
    comp = round(points_possible * 0.3)
    rev = round(points_possible * 0.3)
    refl = points_possible - link - comp - rev
    return {"link": link, "comp": comp, "rev": rev, "refl": refl}


def grade(*, submission, asmt, course, download_dir, browser_fetcher=None,
          canvas_token=None, **kwargs):
    user = submission.get("user") or {}
    first_name = (user.get("name") or "Student").split()[0]
    code = asmt["code"]
    asmt_name = asmt.get("name", "")
    pmax = asmt["points_possible"]
    rubric_dict = dict(asmt.get("rubric") or [])
    if not rubric_dict:
        rubric_dict = default_rubric(pmax)

    link_max = rubric_dict.get("link", round(pmax * 0.2))
    comp_max = rubric_dict.get("comp", round(pmax * 0.3))
    rev_max = rubric_dict.get("rev", round(pmax * 0.3))
    refl_max = rubric_dict.get("refl", pmax - link_max - comp_max - rev_max)

    # FILE-FIRST: grade from the notebook cells + the ACTUAL revision pins. Do NOT download the
    # revision-history screenshots (formality only, grade-nb §B) — that was the gather bottleneck.
    att = att_mod.read(submission, download_dir=download_dir,
                       github_org=course.get("github_org"), canvas_token=canvas_token,
                       browser_fetcher=browser_fetcher, fetch_visual=False)

    # STOP gate — engine couldn't read materials. Refuse to score.
    if att.get("status") == "stop":
        return {"scores": {"link": 0, "comp": 0, "rev": 0, "refl": 0}, "raw": 0, "posted": 0, "stop": True,
                "stop_reason": "; ".join((att.get("errors") or [])[:3]),
                "att_result": att}

    nb = att.get("notebook") or {}
    accessible = bool(nb.get("accessible")) if nb else False
    # A notebook link exists but the engine could not READ it → STOP, never a silent 0. The engine's
    # fetch failing is NOT proof the student did nothing (this session: a fully-completed notebook the
    # instructor could open via gws scored 0 because the engine's fetch failed). Section-0 the case so
    # the instructor verifies (private-link → quality-0 with a re-share comment; fetch glitch → re-run).
    # (A truly ABSENT link → nb is empty/falsy → skipped here, handled below as Link 0.)
    if nb and not accessible:
        return {"scores": {"link": 0, "comp": 0, "rev": 0, "refl": 0}, "raw": 0, "posted": 0, "stop": True,
                "stop_reason": "notebook link present but engine could not read it (not shared / fetch "
                               "failed) — VERIFY by opening it yourself before scoring; a fetch failure is "
                               "NOT a 0 (Part C §5, no silent 0)",
                "att_result": att}
    editor = bool(nb.get("editor")) if nb else False              # shared as Editor? (capabilities.canEdit)
    wrong_format = bool(nb.get("wrong_format")) if nb else False   # a Drive FILE link, not a Colab share
    cells = (nb.get("cells") or []) if nb else []
    revisions = (nb.get("revisions") or []) if nb else []          # keepForever PINS the caller can SEE
    pins = len(revisions)
    all_text = att.get("all_text", "") or ""
    L = len(all_text)
    has_visual = att.get("has_visual", False)
    # image files the AI must VIEW (§0Z) — revision-history screenshots, diagrams — via the raw download
    # If images ARE fetched (a diagram lab), use the DOWNSCALED view_path (Lanczos ≤1400px, cheap
    # vision; §0Z holds — same image smaller). Falls back to the full path.
    image_paths = [(it.get("view_path") or it["path"]) for it in (att.get("items") or [])
                   if it.get("path") and it.get("is_visual")]

    manifest_raw, mpath = _load_manifest(code)
    if isinstance(manifest_raw, dict):
        exec_expected = manifest_raw.get("exec_cells")           # FIXED must-run cell count (template)
        sections = manifest_raw.get("sections")                  # pins expected (1 per section)
        tasks_src = manifest_raw.get("tasks") or []
        E_active = manifest_raw.get("expected_active_min")       # E = genuine active-min for THIS lab (T-ramp)
    else:
        exec_expected, sections, tasks_src = None, None, (manifest_raw or [])
        E_active = None
    exa = nb_inspect.execution_analysis(cells, gap_cap_sec=NB_GAP_CAP_SEC, burst_sec=NB_BURST_SEC)
    # REVISION-BASED active time — the AUTHENTIC time signal. Cell executionInfo (exa.active_min)
    # is OVERWRITTEN to one instant by a final "Run all cells" (collapses to ~0), falsely failing a
    # student who worked section-by-section over days (Akhil LabCh7P2: 6-day dev read as 0-min burst).
    # Drive revisions are append-only saves a Run-all cannot touch. Use the FULL save list when the
    # gather kept it, else the pins. Same capped-gap sum as execution_analysis (idle >cap excluded).
    _rev_times = nb.get("all_revisions") if nb else None
    _rc = nb_inspect.revision_check(_rev_times if _rev_times else revisions)
    rev_active_min = round(sum(min(g, NB_GAP_CAP_SEC / 60.0) for g in _rc.get("gaps_min", [])), 1)
    # The ramp trigger uses whichever signal shows MORE real time — a genuine student is protected
    # if EITHER the cell timeline OR the revision timeline shows the work.
    eff_active_min = max(exa["active_min"], rev_active_min)

    # --- 1) Link & access: shared as EDITOR? Viewer / no-access → 0. The lab REQUIRES Editor so the
    #        revision history is verifiable (`capabilities.canEdit`, attachments.py). ---
    link = link_max if editor else 0

    # --- 2) Completeness: EXECUTED cells (executionInfo) / should-run count. Reliable — NOT outputs
    #        (template ships them) NOR top-level execution_count (Colab nulls it). Denominator = template's
    #        fixed exec_cells (student can't inflate by deleting cells); fallback = student code cells. ---
    denom = exec_expected or exa["code_cells"]
    comp = round(comp_max * min(1.0, (exa["executed"] / denom) if denom else (1.0 if accessible else 0.0)))

    # --- 3) Revision history: keepForever PINS the file shows (Editor needed). Instruction REQUIRES a
    #        pin per section; fewer = deduct. rev = pins / expected sections; 1 pin → 0. PROVISIONAL — the
    #        AI FINALIZES: file 1-pin → 0; a Viewer student whose SCREENSHOT shows genuine pins (a sharing
    #        mistake) → ~50% + "share as Editor & resubmit". executionInfo (active_min/burst) is the
    #        authenticity cross-check, NOT the pin count (validated 2026-07-04: genuine students = 8 pins,
    #        Miechelle/Cullen = 2). ---
    exp_pins = sections or 7
    rev = round(rev_max * min(1.0, pins / exp_pins)) if pins >= 2 else 0
    burst = exa["burst_frac"] >= NB_BURST_THRESHOLD and exa["executed"] >= NB_BURST_MIN_CELLS

    # --- TIME-PLAUSIBILITY RAMP (GRADING §4b.1) — graduated, no hard 0, no double-count. ---
    # T = 0.4×E (E = manifest expected_active_min, content-authored). Trigger = HIGH completion but
    # active < T (a student who did FEW cells took little time = honest incomplete, comp already low → NOT
    # ramped). Both comp+rev slide down by the same time factor F, each with a floor. E missing → do NOT
    # fabricate a threshold: skip the ramp and FLAG so the grade is not silently mis-timed.
    completion_frac = (exa["executed"] / denom) if denom else 0.0
    T = round(NB_T_COEF * E_active, 1) if E_active else None
    ramp_F = None
    if T and completion_frac >= NB_RAMP_TRIGGER_FRAC and eff_active_min < T:
        ramp_F = min(1.0, eff_active_min / T) if T else 1.0
        comp = round(comp * (NB_COMP_FLOOR + (1 - NB_COMP_FLOOR) * ramp_F))
        rev = round(rev * (NB_REV_FLOOR + (1 - NB_REV_FLOOR) * ramp_F))

    tasks = nb_inspect.resolve_tasks(cells, tasks_src) if (tasks_src and cells) else []

    # --- 4) Reflection / Elaboration. PREFERRED source = the IN-NOTEBOOK per-section answers
    #        (@anchor/@answer cells) — the real work; the submission body is often just a link.
    #        Score by answered-section coverage. FALL BACK to the body-length floor only when the
    #        notebook carries no @anchor reflection prompts (older labs). Either way the answers are
    #        surfaced in reflection_text so Stage B reads them and the quote-gate can enforce it. ---
    refl_answers = _extract_reflections(cells)          # {section: answer}; {} when none in-notebook
    if refl_answers:
        _nsec = len(refl_answers)
        _nans = sum(1 for v in refl_answers.values() if len(v.strip()) > 25)
        refl = round(refl_max * _nans / _nsec) if _nsec else 0
        refl_why = f"{_nans} of {_nsec} section reflections answered in the notebook"
    else:
        if L < 30:
            refl = 0
        elif L < 100:
            refl = max(1, refl_max // 3)
        elif L < 300:
            refl = max(2, refl_max * 2 // 3)
        else:
            refl = refl_max
        refl_why = f"reflection text was {L} chars"
    refl = min(refl, refl_max)

    raw = link + comp + rev + refl
    if raw < pmax * 0.1 and (att.get("read_n", 0) > 0 or L > 0):
        raw = max(1, int(pmax * 0.1))

    needs_review = [f"NB GATHERER: share={'Editor' if editor else 'VIEWER/none→Link0'} · "
                    f"executed {exa['executed']}/{denom} cells · pins {pins} (expected {exp_pins}) · "
                    f"active(cell) {exa['active_min']}min · active(revisions) {rev_active_min}min "
                    f"[rev span {_rc.get('span_min')}min, {_rc.get('count')} saves] → effective {eff_active_min}min · "
                    f"burst {int(exa['burst_frac']*100)}%. AI Stage B FINALIZES (Part C §2–4b + resubmit rule). raw provisional."]
    # TIME-RAMP status (GRADING §4b.1) — always visible so the grade is explainable / not silently mis-timed.
    if E_active is None:
        needs_review.append(f"⚠ TIME-RAMP NOT APPLIED — no `expected_active_min` (E) in manifests/{code}.json. "
                            f"Author E (content-based genuine active-min) so T=0.4×E ramps implausibly-fast work.")
    elif ramp_F is not None:
        needs_review.append(f"TIME-RAMP APPLIED: effective active {eff_active_min}min "
                            f"(cell {exa['active_min']} / revisions {rev_active_min}) < T={T}min (E={E_active}, "
                            f"completion {int(completion_frac*100)}%≥{int(NB_RAMP_TRIGGER_FRAC*100)}%) → F={round(ramp_F,2)} "
                            f"→ comp×{round(NB_COMP_FLOOR+(1-NB_COMP_FLOOR)*ramp_F,2)} rev×{round(NB_REV_FLOOR+(1-NB_REV_FLOOR)*ramp_F,2)}.")
    else:
        needs_review.append(f"time OK: active {exa['active_min']}min ≥ T={T}min (E={E_active}) — no ramp.")
    if wrong_format:
        needs_review.append("★WRONG SUBMIT FORMAT: a Drive FILE link (drive.google.com/file/d/…), NOT a "
                            "Colab notebook share → Link 0; execution/revisions not verifiable (comp/rev ~0). "
                            "Comment: resubmit as a Colab notebook shared as Editor (colab.research.google.com/drive/…).")
    if not editor and accessible:
        needs_review.append("★NOT shared as Editor (Viewer) → Link=0, and the revision history isn't fully "
                            "verifiable. If the submitted SCREENSHOT shows genuine pins (a sharing mistake) → "
                            "award revision ~50% + comment 'share as Editor and resubmit'. VIEW image_paths.")
    if pins < exp_pins:
        needs_review.append(f"revision: {pins} pins < {exp_pins} expected (1/section) → deduct per instruction "
                            "(pin-per-section is REQUIRED; 1 pin → 0). Cross-check executionInfo for real work.")
    if burst:
        needs_review.append(f"★BURST: {int(exa['burst_frac']*100)}% of cells <2s apart → paste / no-think check (§4b)")
    if image_paths:
        needs_review.append(f"IMAGE files to VIEW (§0Z, Stage B reads each): {image_paths}")
    if comp < comp_max and exa.get("unexecuted"):
        _ux = "; ".join(f"cell {u['cell']}: {u['snippet']}" for u in exa["unexecuted"][:15])
        needs_review.append(f"UNEXECUTED cells — NAME THESE in the comment: {_ux}")
    if exa.get("burst_clusters"):
        _bc = "; ".join(f"{b['section']} (cells {b['cells'][0]}-{b['cells'][1]}, {b['n']} cells)"
                        for b in exa["burst_clusters"])
        needs_review.append(f"BULK-RUN blocks — name the section, guide step-by-step: {_bc}")
    if not manifest_raw:
        needs_review.append(f"no manifest at manifests/{code}.json — AI reads cells directly for completeness")
    for t in tasks:
        if t.get("needs_ai_read"):
            needs_review.append(f"{t.get('anchor', '?')}: {t.get('flag', 'not located')}")
    for qf in (att.get("quality_failures") or []):
        needs_review.append(f"{qf.get('kind', '?')}: {qf.get('reason', '')[:120]}")
    if nb and not accessible:
        needs_review.append("notebook NOT accessible (not shared / deleted) — inaccessible rule (Part C §5), no silent 0")

    # 3-TUPLES, NOT 4 (2026-08-04) — same cut as gh.py. Every row used to carry a
    # `{why, how_to_fix}` dict that NOTHING read: both consumers below destructure with `*_`.
    # It was student-facing deduction text produced outside `comment_render`, which owns that
    # job and enforces the reason + how-to-fix gate. The FACTS those strings were built from
    # are already in `review_content` below (share state, unexecuted cells, pin count,
    # reflection), so Stage B still has everything it needs — and writes the wording itself.
    rubric_rows = [
        ("Link & access", link_max, link),
        ("Completeness (cells executed)", comp_max, comp),
        ("Revision history (pin per section)", rev_max, rev),
        ("Reflection / Elaboration", refl_max, refl),
    ]
    return {
        "scores": {"link": link, "comp": comp, "rev": rev, "refl": refl},
        "rubric_items": [(lbl, mx) for lbl, mx, *_ in rubric_rows],
        "earned": {lbl: sc for lbl, mx, sc, *_ in rubric_rows},   # per-item, for report_generator columns
        "review_content": {
            "share": {"editor": editor, "accessible": accessible},
            "execution": exa,
            "revision": {"pins": pins, "expected": exp_pins},
            "params": {"burst_sec": NB_BURST_SEC, "burst_threshold": NB_BURST_THRESHOLD,
                       "burst_min_cells": NB_BURST_MIN_CELLS, "gap_cap_sec": NB_GAP_CAP_SEC,
                       "active_full_min": NB_ACTIVE_FULL_MIN, "burst_flagged": burst,
                       # time-plausibility ramp (GRADING §4b.1) — every knob surfaced for explainability
                       "E_expected_active_min": E_active, "T_threshold_min": T,
                       "ramp_F": (round(ramp_F, 3) if ramp_F is not None else None),
                       "comp_floor": NB_COMP_FLOOR, "rev_floor": NB_REV_FLOOR,
                       "ramp_trigger_frac": NB_RAMP_TRIGGER_FRAC, "completion_frac": round(completion_frac, 3)},
            "image_paths": image_paths,
            "tasks": [{k: t.get(k) for k in
                       ("anchor", "type", "prompt", "found", "method", "region", "evidence", "needs_ai_read", "flag")}
                      for t in tasks],
            # body text PLUS the extracted in-notebook per-section answers, so Stage B reads the
            # REAL reflections and the report_generator quote-gate can require a verbatim reflection
            # quote (enforces 'the engine/AI actually read the reflection', not just the link).
            "reflection_text": all_text + (
                "\n\n[IN-NOTEBOOK REFLECTIONS]\n"
                + "\n\n".join(f"S{k}: {refl_answers[k]}" for k in sorted(refl_answers))
                if refl_answers else ""),
            # code-cell source concatenated → the student's OWN notebook work, so the ground-truth
            # QUOTE GATE (report_generator) can verify a completeness `evidence.quote` is a real
            # substring of the cells (NB has no `code_src` from tasks unless a task manifest exists).
            "cells_src": "\n".join(
                ("".join(c.get("source") or []) if isinstance(c.get("source"), list)
                 else str(c.get("source") or ""))
                for c in cells if c.get("cell_type") == "code"),
            "has_visual": has_visual,
        },
        "raw": raw, "posted": raw,
        "needs_review": needs_review,
        "att_result": {k: att.get(k) for k in ("expected_n", "read_n", "errors", "quality_failures", "status")},
    }
