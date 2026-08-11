"""NB (Colab / Jupyter) deep-read for grading — implements GRADING.md Part C §2–4.

STRUCTURAL fixes for two recurring grading failures (railings, not signs):

  1. Truncation — `load_notebook` reads the WHOLE notebook and `deep_read`
     returns VERDICTS + evidence, not a string. The grader never holds a
     truncatable blob, so it can't slice off evidence (the `[:80]` bug that hid
     a student's <img>). GRADING.md §0Z.
  2. Template noise — `deep_read` DIFFS the submission against the original
     template and judges only student-ADDED cells, so the template's own example
     <img>, the `![Description](Image Link)` placeholder, and the provided Task-1
     cell can never be miscounted as the student's work. GRADING.md Part C §4.2–4.3.

The grader calls `deep_read(student_path, template_path)` and grades from its
return value. It does NOT pattern-match the merged notebook and does NOT truncate.
"""
from __future__ import annotations

import json
import re


class NotebookError(Exception):
    """Raised when a notebook cannot be read in full — never swallowed, so a
    partial/empty read is never mistaken for 'the student did nothing'."""


def load_notebook(path):
    """Full read — the ENTIRE notebook, every cell, complete source. No slicing,
    no sampling, no `head`. Raises NotebookError if it cannot be parsed."""
    try:
        with open(path) as f:
            nb = json.load(f)
    except Exception as e:  # noqa: BLE001 — any read/parse failure is a NotebookError
        raise NotebookError(f"cannot read notebook {path}: {e}")
    if "cells" not in nb:
        raise NotebookError(f"not a notebook (no cells): {path}")
    return nb


def _norm(cell):
    return ("".join(cell.get("source", []))).strip()


def template_added_cells(student_cells, template_cells):
    """Student-added / modified cells = those whose normalized source is NOT in the
    template (GRADING Part C §4.2–4.3). Removes every instructor-template cell:
    the instruction text, the example <img>, the placeholder, the provided Task-1 cell."""
    tmpl = {_norm(c) for c in template_cells}
    return [c for c in student_cells if _norm(c) not in tmpl]


_PLACEHOLDER = "image link"  # the template's ![Description](Image Link) target


def has_real_image(cell):
    """Evidence string of a REAL image in a markdown cell, else None. Reads the
    FULL source; catches `![alt](http|data:|attachment:…)`, `<img src=…>`, and cell
    attachments; excludes the template placeholder `![Description](Image Link)`."""
    if cell.get("cell_type") != "markdown":
        return None
    if cell.get("attachments"):
        return f"attachment:{next(iter(cell['attachments']))[:30]}"
    src = "".join(cell.get("source", []))
    for alt, tgt in re.findall(r"!\[([^\]]*)\]\(([^)]+)\)", src):
        t = tgt.strip()
        if t.lower() != _PLACEHOLDER and t.startswith(("http", "data:", "attachment")):
            return f"![{alt[:15]}]({t[:40]})"
    m = re.search(r"<img[^>]+src=['\"]?([^'\">\s]+)", src)
    return f"<img {m.group(1)[:40]}>" if m else None


def deep_read(student_path, template_path):
    """The structural NB deep-read. Returns verdicts + full evidence, judging ONLY
    student-added cells (template diff). The grader calls THIS and never slices a
    string, never regexes the merged notebook, never sees template noise.

    Returns dict:
      {accessible: bool, task1_ran, task2_code, task3_image: bool,
       completeness: 0..9, evidence: [str, ...], error: str|None}
    `accessible=False` (with `error`) → apply the inaccessible rule (Part C §5),
    do NOT silently zero.
    """
    out = {"accessible": False, "task1_ran": False, "task2_code": False,
           "task3_image": False, "completeness": 0, "evidence": [], "error": None}
    try:
        student = load_notebook(student_path)
        template = load_notebook(template_path)
    except NotebookError as e:
        out["error"] = str(e)
        return out
    out["accessible"] = True
    cells = student["cells"]
    # Task 1 = a PROVIDED hello cell that the student actually RAN (has output).
    tmpl_hellos = {_norm(c) for c in template["cells"]
                   if c.get("cell_type") == "code" and "hello" in _norm(c).lower()}
    out["task1_ran"] = any(_norm(c) in tmpl_hellos and c.get("outputs") for c in cells)
    # Task 2 / Task 3 judged on ADDED cells only.
    for c in template_added_cells(cells, template["cells"]):
        src = _norm(c)
        if (c.get("cell_type") == "code" and "hello world" in src.lower()
                and c.get("outputs")):
            out["task2_code"] = True
            out["evidence"].append(f"+code:{src[:30]!r}")
        img = has_real_image(c)
        if img:
            out["task3_image"] = True
            out["evidence"].append(f"+image:{img}")
    out["completeness"] = 3 * (out["task1_ran"] + out["task2_code"] + out["task3_image"])
    return out


# --- Region-based per-problem resolution (GRADING Part C §2; GENERAL N-problem completeness) ---
# Supersedes deep_read's hardcoded task1/2/3 for any lab with a problem MANIFEST. The answer to a
# problem = the REGION from its anchor to the NEXT anchor, so any cell the student ADDED is included.

_ANCHOR_RE = re.compile(r"@anchor:(\S+)", re.I)
_PLACEHOLDER_RE = re.compile(
    r"your (code|answer|explanation) here|write your|complete your|# ?your answer|do not delete", re.I)


def _cell_src(cell):
    s = cell.get("source", [])
    return "".join(s) if isinstance(s, list) else (s or "")


def _flat(s):
    return re.sub(r"\s+", " ", s).strip().lower()


# Ground-truth forbidden-shortcut scan (GRADING §4F / quiz-exam-policy): an algorithm problem solved
# with a built-in shortcut is NOT the algorithm. Engine COMPUTES this from the actual source so a
# lazy Stage B cannot miss it — it is a fact, not a prose reminder.
_FORBIDDEN_RE = re.compile(r"(?<![\w.])(sorted|reversed|min|max)\s*\(|\.(sort|reverse)\s*\(")


def forbidden_in(src):
    """Return the sorted list of built-in shortcuts (sorted/reversed/min/max/.sort/.reverse) CALLED in
    `src` — ground truth from the actual code, ignoring comment-only lines. Empty list = clean."""
    code = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))
    hits = set()
    for m in _FORBIDDEN_RE.finditer(code):
        if m.group(1):
            hits.add(m.group(1))
        elif m.group(2):
            hits.add("." + m.group(2))
    return sorted(hits)


def _anchor_id(src):
    m = _ANCHOR_RE.search(src)
    return re.sub(r"[->\s]+$", "", m.group(1)) if m else None


def _prompt_key(task):
    if task.get("key"):
        return task["key"]
    return _flat(re.sub(r"<!--.*?-->", "", task.get("prompt", "")))[:120]


def _locate(cells, task):
    """Cell index of this task's problem in the student notebook: @anchor tag →
    instruction-text CONTAINS → (None, None). Never raises."""
    aid = task.get("anchor")
    if aid:
        for j, c in enumerate(cells):
            if _anchor_id(_cell_src(c)) == aid:
                return j, "anchor-tag"
    key = _prompt_key(task)
    if key:
        for j, c in enumerate(cells):
            if c.get("cell_type") == "markdown" and key in _flat(_cell_src(c)):
                return j, "text-contains"
    return None, None


def _region_evidence(cells, start, end):
    """Signals over the answer REGION [start,end) — BOTH code and explanation, no type gate."""
    reg = cells[start:end]
    code = [c for c in reg if c.get("cell_type") == "code"]
    md = [c for c in reg if c.get("cell_type") == "markdown"]
    executed = sum(1 for c in code if c.get("execution_count") is not None)
    good_out = sum(1 for c in code
                   if c.get("outputs") and not any(o.get("output_type") == "error" for o in c.get("outputs")))
    md_text = sum(len(_flat(_cell_src(c))) for c in md if not _PLACEHOLDER_RE.search(_flat(_cell_src(c))))
    code_src = "\n".join(_cell_src(c) for c in code)
    return {"cells": len(reg), "code": len(code), "executed": executed,
            "code_output": good_out, "md": len(md), "md_text_chars": md_text,
            "code_src": code_src,                    # GROUND TRUTH for quote-verification (report_generator)
            "forbidden": forbidden_in(code_src)}     # built-in shortcuts actually called in the answer


def resolve_tasks(cells, tasks):
    """Per-problem REGION resolution (GRADING Part C §2). `tasks` = the assignment MANIFEST
    [{anchor, type, prompt}]. Answer region = [anchor cell + 1 .. the NEXT located anchor], so any
    cell the student ADDED under a problem is included. Crash-safe: an unlocated problem →
    needs_ai_read (the AI reads it), never a silent zero, never an exception. Returns per problem
    {**task, found, method, anchor_idx, region:[start,end], evidence, needs_ai_read, flag}."""
    locs = [_locate(cells, t) for t in tasks]
    bounds = sorted(idx for idx, _ in locs if idx is not None)

    def next_after(idx):
        for p in bounds:
            if p > idx:
                return p
        return len(cells)

    out = []
    for t, (idx, method) in zip(tasks, locs):
        if idx is None:
            out.append({**t, "found": False, "needs_ai_read": True,
                        "flag": f"{t.get('anchor') or t.get('prompt', '')[:40]}: not located -> AI read"})
            continue
        start, end = idx + 1, next_after(idx)
        out.append({**t, "found": True, "method": method, "anchor_idx": idx,
                    "region": [start, end], "evidence": _region_evidence(cells, start, end)})
    return out


def build_manifest(cells):
    """CANONICAL grading-manifest builder from a TEMPLATE notebook's cells (never hand-count one).
      exec_cells     = code-cell count = the completeness denominator (GRADING Part C §2).
      sections       = distinct 'Section N' / 'Problem X.Y' headers = the pin-per-section expectation (§3).
      section_labels = those labels, for reference.
      tasks          = one entry per @anchor-tagged cell (for resolve_tasks; empty if the template is
                       un-stamped — the manifest is still valid, completeness falls back to exec_cells).
    Network-free (takes already-loaded cells). Used by nb-homework-create at CREATION (auto → zero prep)
    and to pre-count existing assignments (Ch4/5/6) before grading. Writes via the __main__ CLI below."""
    exec_cells = sum(1 for c in cells if c.get("cell_type") == "code")
    # sections = distinct TOP-LEVEL sections (the pin-per-section expectation is per top-level section,
    # NOT per sub-problem: "Problem 1.0..1.12, 2.1.." → top-level 1,2,.. ; "Section N. name" → N).
    labels = []
    for c in cells:
        if c.get("cell_type") != "markdown":
            continue
        s = _cell_src(c)
        # An EXPLICIT "Section N" heading wins — it is the plainest signal a template can give, and
        # it is what the pin note asks the student to type. Missing it meant a notebook whose last
        # section was headed "### Section 7 - Putting It Together" reported 6 sections, so that
        # section's pin looked unexpected (<course> strings lab, 2026-08-02).
        m = re.search(r"(?m)^\s*#*\s*Section\s+(\d+)\b", s)
        if not m:
            m = re.search(r"Problem\s*#?\s*(\d+)(?:\.\d+)?", s)      # top-level of Problem X.Y
        if not m:
            m = re.search(r"(?m)^\s*#*\s*(\d+)\.\s*[A-Za-z]", s)      # Section N. name
        lbl = f"Section {m.group(1)}" if m else None
        if lbl and lbl not in labels:
            labels.append(lbl)
    tasks = [{"anchor": _anchor_id(_cell_src(c)), "prompt": _flat(_cell_src(c))[:80]}
             for c in cells if _anchor_id(_cell_src(c))]
    return {"exec_cells": exec_cells, "sections": len(labels),
            "section_labels": labels, "tasks": tasks}


def _section_of(cells, idx):
    """Nearest preceding 'Problem X.Y' or numbered section header at/above cell `idx` — a human label
    for a burst cluster in the student comment ("Section 3 was run in bulk")."""
    for j in range(min(idx, len(cells) - 1), -1, -1):
        c = cells[j]
        if c.get("cell_type") != "markdown":
            continue
        s = _cell_src(c)
        m = re.search(r"Problem\s*#?\s*(\d+\.\d+)", s)
        if m:
            return f"Problem {m.group(1)}"
        m = re.search(r"(?m)^\s*#*\s*(\d+)\.\s*([A-Za-z][^\n]{0,28})", s)
        if m:
            return f"Section {m.group(1)} ({m.group(2).strip()})"
    return "?"


def _is_blank_code(src):
    """A code cell that is EMPTY or only comments/placeholder ('# complete the code', '# YOUR CODE
    HERE') — a leftover template slot, NOT a gradeable answer. These must be EXCLUDED from completeness:
    they are not 'required to run', and an unrun empty slot is not a missed problem (the student's real
    answer is a sibling cell). This is the fix for the anchor-strict mis-grade (Julian 8.4 etc.)."""
    return not any(ln.strip() and not ln.lstrip().startswith("#") for ln in src.splitlines())


def execution_analysis(cells, gap_cap_sec=180, burst_sec=2, min_cluster=3):
    """Colab per-cell `metadata.executionInfo` → the RELIABLE execution signal.

    Why this and not the alternatives (verified 2026-07-04):
      - top-level `execution_count` — Colab nulls it (a student who ran 51 cells showed 0). Unreliable.
      - cell `outputs` present — the TEMPLATE ships with outputs, so "has output" is contaminated.
      - `executionInfo.timestamp` — the cell's LAST-run time, written by Colab per run. Reliable, and
        also carries the real execution TIME. (No per-cell RUN COUNT exists — only the last run is
        kept; earlier runs are overwritten. So a cell is binary executed/not, plus its last time.)

    Returns:
      executed     : # code cells with an executionInfo timestamp (completeness numerator)
      code_cells   : total code cells (completeness denominator = should-run)
      active_min   : SUM of cell-to-cell gaps, each CAPPED at gap_cap_sec → real work time with idle
                     breaks excluded (NOT max−min, which "49 cells in 1s + 1 cell a day later" inflates
                     to a day). This is the effort/authenticity time.
      span_min     : max−min (reference only)
      burst_count / burst_frac : gaps < burst_sec (ran in rapid succession = paste / no-think). Reported
                     SEPARATELY so one large gap can't mask a majority-burst (active_min alone would).
    """
    # Exclude blank/placeholder template slots — they are not gradeable answers, so they must not
    # count in the denominator NOR be reported as "not run" (that mis-graded Julian's empty 8.4 slot).
    code = [(i, c) for i, c in enumerate(cells)
            if c.get("cell_type") == "code" and not _is_blank_code(_cell_src(c))]
    runs, unexecuted = [], []
    for i, c in code:
        ei = (c.get("metadata") or {}).get("executionInfo") or {}
        if ei.get("timestamp"):
            runs.append((i, ei["timestamp"]))            # (notebook cell index, run time)
        else:
            # cell NOT run — record its notebook index, its SECTION (so the comment can name WHICH
            # sections weren't run — GRADING Part C §2), and a code snippet. (Colab `id` too if present.)
            unexecuted.append({"cell": i, "id": (c.get("metadata") or {}).get("id"),
                               "section": _section_of(cells, i),
                               "snippet": re.sub(r"\s+", " ", _cell_src(c)).strip()[:70]})
    runs.sort(key=lambda x: x[1])                          # by execution TIME (bursts are time-adjacent)
    ts = [t for _, t in runs]
    out = {"code_cells": len(code), "executed": len(ts), "gaps": 0,
           "span_min": 0.0, "active_min": 0.0, "burst_count": 0, "burst_frac": 0.0,
           "unexecuted": unexecuted, "burst_clusters": []}
    if len(ts) >= 2:
        gaps = [(ts[k + 1] - ts[k]) / 1000.0 for k in range(len(ts) - 1)]
        out["gaps"] = len(gaps)
        out["span_min"] = round((ts[-1] - ts[0]) / 60000.0, 1)
        out["active_min"] = round(sum(min(g, gap_cap_sec) for g in gaps) / 60.0, 1)
        out["burst_count"] = sum(1 for g in gaps if g < burst_sec)
        out["burst_frac"] = round(out["burst_count"] / len(gaps), 2)
        # BURST CLUSTERS: maximal runs of ≥ min_cluster cells executed <burst_sec apart (bulk-run
        # blocks). Each → the cell RANGE + its SECTION label, so Stage B names WHERE it happened and
        # guides the fix. (Reported for ANY student with clusters, not only the fully-flagged ones.)
        clusters, k = [], 0
        while k < len(gaps):
            if gaps[k] < burst_sec:
                start = k
                while k < len(gaps) and gaps[k] < burst_sec:
                    k += 1
                idxs = [runs[j][0] for j in range(start, k + 1)]     # cells in this bulk block
                if len(idxs) >= min_cluster:
                    lo = min(idxs)
                    clusters.append({"cells": [lo, max(idxs)], "n": len(idxs),
                                     "section": _section_of(cells, lo)})
            else:
                k += 1
        out["burst_clusters"] = clusters
    return out


def _parse_iso(t):
    from datetime import datetime
    return datetime.fromisoformat(t.replace("Z", "+00:00"))


def revision_check(revisions, burst_window_min=3.0):
    """Analyze a Drive revision list (from `gws drive revisions list`).

    Input: list of {id, modifiedTime, keepForever}.
    Returns: {count, pinned, span_min, median_gap_min, gaps_min:[...], bursted}.
      - count / pinned : total revisions and keepForever-pinned count.
      - span_min       : minutes from first to last revision.
      - gaps_min       : minutes between consecutive saves (real development is
                         spread out; a burst = all saves in a tiny window).
      - bursted        : True if every save is inside `burst_window_min` minutes
                         (clustered = not real spread-out work).

    ⚠ Drive revisions reflect SAVE activity; they are NOT the Colab NAMED pins
    (Task 1/2/3), which the API does not expose. So this is a count + authenticity
    signal — NOT proof of the named-pin requirement. The named-pin check still needs
    the professor's eyes or a required revision-history screenshot. (GRADING Part C §3.3.)
    """
    revs = [r for r in (revisions or []) if r.get("modifiedTime")]
    times = sorted(_parse_iso(r["modifiedTime"]) for r in revs)
    pinned = sum(1 for r in revs if r.get("keepForever"))
    gaps = [(times[i + 1] - times[i]).total_seconds() / 60 for i in range(len(times) - 1)]
    span = (times[-1] - times[0]).total_seconds() / 60 if len(times) >= 2 else 0.0
    median_gap = sorted(gaps)[len(gaps) // 2] if gaps else 0.0
    return {
        "count": len(revs),
        "pinned": pinned,
        "span_min": round(span, 1),
        "median_gap_min": round(median_gap, 2),
        "gaps_min": [round(g, 2) for g in gaps],
        "bursted": len(times) >= 2 and span < burst_window_min,
    }


def revision_diff(nb_old, nb_new):
    """Revision-diff analysis: cell sources ADDED/changed between two notebook
    revision contents (both parsed ipynb dicts, e.g. an earlier vs a later
    revision fetched via `gws drive revisions get`). Returns the list of
    added/changed normalized cell sources — i.e. what that revision actually
    contributed (an empty list = a save that changed nothing)."""
    old = {_norm(c) for c in nb_old.get("cells", [])}
    return [_norm(c) for c in nb_new.get("cells", []) if _norm(c) not in old]


def revision_progression(revs, min_sections=3, burst_window_min=3.0):
    """SECTION-WISE revision analysis — grade the revision item by CONTENT + TIME,
    no pin names needed (names aren't in the API; this is the reliable substitute).

    `revs` = list (sorted oldest->newest) of:
        {"modifiedTime": iso, "keepForever": bool, "nb": <parsed ipynb dict>}
    The caller fetches each revision's content (`gws drive revisions get … alt=media`)
    — the lib stays network-free.

    Between consecutive revisions it computes the TIME gap and the CONTENT added
    (`revision_diff`). A "section step" = a revision that added real content (a task).

    Returns:
      {steps:[{time, gap_min, pinned, added:[src,...]}], content_steps:int,
       span_min, bursted:bool, ok:bool, evidence:str}
      - ok  = content_steps >= min_sections AND not bursted (genuine section-by-
              section build-up, spread over real time).
      - bursted = all saves inside burst_window_min (clustered = faked, not real work).
      - evidence = a comment-ready string of the build-up (put it in the student
                   comment when deducting — the time gaps + what each revision added).
    """
    # ⚠ The VERDICT is judged on PINNED (keepForever) revisions only. Colab AUTO-SAVES
    # create revisions automatically as the student edits — so an unpinned student still
    # shows a content "progression" over all revisions. Deliberate pinning ("File > Save
    # and Pin Revision", the graded skill) = keepForever=true. Judge those; auto-saves are
    # context only.
    pinned = [r for r in revs if r.get("keepForever")]
    rows = []
    prev = None
    prev_t = None
    content_steps = 0
    ptimes = [_parse_iso(r["modifiedTime"]) for r in pinned]
    span = (ptimes[-1] - ptimes[0]).total_seconds() / 60 if len(ptimes) >= 2 else 0.0
    for r in pinned:
        t = _parse_iso(r["modifiedTime"])
        gap = (t - prev_t).total_seconds() / 60 if prev_t else 0.0
        added = revision_diff(prev, r["nb"]) if prev is not None else []
        if added:
            content_steps += 1
        rows.append({"time": r["modifiedTime"][:19], "gap_min": round(gap, 2),
                     "pinned": True, "added": added})
        prev = r["nb"]
        prev_t = t
    n_pins = len(pinned)
    bursted = len(ptimes) >= 2 and span < burst_window_min
    # genuine: enough PINS, each pin spread over real time (not burst), and the pins
    # actually grow content (auto-save-only / static pins fail this).
    ok = n_pins >= min_sections and content_steps >= (min_sections - 1) and not bursted
    ev = [f"{r['time']} (+{r['gap_min']}m){'[pin]' if r['pinned'] else ''}: "
          + (", ".join(a[:25] for a in r["added"][:2]) if r["added"] else "no change")
          for r in rows if r["added"] or r["pinned"]]
    evidence = (f"revision build-up: {content_steps} content step(s) over {round(span, 1)} min"
                + (" — BURST/too fast" if bursted else "")
                + (("; " + " | ".join(ev[:6])) if ev else ""))
    return {"steps": rows, "content_steps": content_steps, "span_min": round(span, 1),
            "bursted": bursted, "ok": ok, "evidence": evidence}


def score_revision(progression, full_points=9, partial_points=6):
    """Map a `revision_progression` result to {score, reason} for an intro NB
    (LENIENT / educational — warning-level, generous on time):
        genuine (ok)                          -> full_points (9)
        attempted but insufficient (>=1 pin   -> partial_points (6)
          that added content; burst, too few
          pins, only partial — all unified to 6)
        nothing real (no pins / no content)   -> 0

    The reason is FACTUAL evidence ONLY — exact pin times, gaps, what each pin
    added, burst, missing task (GRADING SKILL §3b: no threats, instructor tone;
    the detail itself shows the work was reviewed in full). reason='' at full marks.
    """
    p = progression
    ev = []
    for s in p.get("steps", []):
        if s["added"]:
            # collapse each added cell's source to ONE line (newlines -> space) so the
            # evidence never breaks the comment mid-line.
            snips = "; ".join(" ".join(a.split())[:45] for a in s["added"][:2])
            ev.append(f"pin {s['time']} (+{s['gap_min']} min) added: {snips}")
        else:
            ev.append(f"pin {s['time']} (+{s['gap_min']} min): no new content")
    facts = (f"{len(p.get('steps', []))} pinned revision(s); {p['content_steps']} added new "
             f"content; total span {p['span_min']} min"
             + (" (all pins fall inside a short burst)" if p["bursted"] else "")
             + ((". " + " | ".join(ev)) if ev else "."))
    fix = (" For full marks: File > Save and Pin Revision named Task 1, Task 2, Task 3 after "
           "completing each task, spread across your working time, each pin adding that task's content.")
    if p["ok"]:
        return {"score": full_points, "reason": ""}
    if p["content_steps"] >= 1:
        return {"score": partial_points, "reason": "Revision history incomplete. " + facts + fix}
    return {"score": 0, "reason": "No genuine pinned revision history. " + facts + fix}


def _build_manifest_cli(argv):
    """CLI: build the grading manifest from a LOCAL template .ipynb → grade_engine/manifests/<code>.json.
    Network-free — fetch the template to a local file first (gh / attachments), then run this."""
    import argparse
    import json
    import os
    ap = argparse.ArgumentParser(prog="nb_inspect --build-manifest",
                                 description="Build grade_engine/manifests/<code>.json from a template notebook.")
    ap.add_argument("template", help="local path to the template .ipynb")
    ap.add_argument("code", help="assignment code (→ manifests/<code>.json)")
    ap.add_argument("--note", default="", help="optional provenance note stored in the manifest")
    a = ap.parse_args(argv)
    man = build_manifest((load_notebook(a.template) or {}).get("cells") or [])
    if a.note:
        man["note"] = a.note
    mdir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "manifests")
    os.makedirs(mdir, exist_ok=True)
    path = os.path.join(mdir, f"{a.code}.json")
    # AUTHORED fields survive a rebuild. `expected_active_min` (E) is hand-rated per grade-nb Step
    # A0 #3 and is MANDATORY — without it the time-plausibility ramp is skipped entirely. A rebuild
    # (every template edit is one) silently wiped it three times on 2026-08-02 before this.
    kept = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                old = json.load(f)
            kept = {k: v for k, v in old.items()
                    if k not in man and (k.startswith("expected_active_min") or k == "note")}
        except (OSError, ValueError):
            kept = {}
    if kept:
        man = {**{k: v for k, v in man.items() if k != "tasks"}, **kept, "tasks": man["tasks"]}
    with open(path, "w") as f:
        json.dump(man, f, indent=2, ensure_ascii=False)
    print(f"wrote {path}" + (f"  (kept authored: {', '.join(sorted(kept))})" if kept else ""))
    print(f"  exec_cells={man['exec_cells']} · sections={man['sections']} "
          f"({', '.join(man['section_labels']) or 'no section headers found'}) · tasks={len(man['tasks'])}")


if __name__ == "__main__":
    import sys
    if sys.argv[1:2] == ["--build-manifest"]:
        _build_manifest_cli(sys.argv[2:])
    else:
        print("usage: python3 -m grade_engine.lib.nb_inspect --build-manifest "
              "<template.ipynb> <code> [--note ...]", file=sys.stderr)
