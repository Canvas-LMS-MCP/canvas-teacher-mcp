#!/usr/bin/env python3
"""nb_create — build + anchor-stamp an NB (Colab/Jupyter) homework template for `nb-homework-create`.

ONE creation-side driver (mirror of grading's single `grade-nb/grade_nb_skill.py`). Two subcommands:

  build <spec.json> -o out.ipynb     assemble AI-authored cells (optionally onto a base notebook),
                                     then anchor them via stamp_manifest. THE path for new templates.
  enrich <spec.json> -o out.ipynb    rewrite an EXISTING template's problem instructions/answer slots
                                     IN PLACE and insert practice/challenge problems after them
                                     (`build` can only APPEND, which is useless mid-chapter).
  stamp <in.ipynb> [--manifest m]    anchor an EXISTING template's problem cells (retrofit, e.g. ch03):
                                     --manifest = reliable AI-judged path; no manifest = keyword auto.

Makes a template gradeable by the `grade-nb` sub-skill (mirror):
  - every TASK instruction (markdown) gets a hidden `<!-- @anchor:<id> type=code|explain|reflect -->` in its
    SOURCE (invisible in Colab render, preserved across "Save a copy") + a `grade_id` in cell metadata;
  - the following cell (the answer slot) is tagged `# @answer:<id>` / `<!-- @answer:<id> -->`, or an
    answer cell is INSERTED if none follows;
  - reflection + "Save and pin — Section N" cells build the graded revision/reflection process
    (auto in `stamp`; authored per-section in `build`).
IDEMPOTENT stamping: skips already-anchored cells.

build spec.json schema:
  {"base": "<path to base .ipynb or null>", "banner": true,
   "append": [ {"section": "Section 11 — ..."},
               {"markdown": "..."},
               {"code": "<pre-filled runnable code>"},
               {"problem": {"anchor":"P1-T1","instr":"<md>","answer":"<code>","type":"code"}},
               {"reflection": {"anchor":"P1-R11","prompt":"...","title":"Section 1: Selection",
                               "pin":"Section 1"}} ]}

  `reflection` -> 3 cells: an anchored prompt, an answer cell, and a Save-and-pin note.
  `title` names the section in the heading ("### Reflection — Section 1: Selection"); `pin` is the
  exact revision name the student must type ("name it `Section 1`"). Both optional — omit and the
  heading is a bare "### Reflection" and the note says "name it for this section" (vaguer; the
  grader matches pins per section, so PASS them).

  `code` = a pre-filled EXAMPLE cell (the answer is given; the student only RUNS it). NOT
  anchored -> never graded for correctness; counts only toward completeness ("did they run
  every cell", from Colab executionInfo). This is §1's "a pre-filled example / run cell needs
  NO anchor". A cell the STUDENT must fill is a `problem`, not a `code`.

Usage:
  nb_create.py build spec.json -o out.ipynb [--dry]
  nb_create.py stamp in.ipynb [-o out.ipynb] [--manifest m.json] [--no-pins-essays] [--dry]
"""
import argparse
import json
import re
import sys

_ANCHOR_RE = re.compile(r'@anchor:(\S+)', re.I)
_ANSWER_RE = re.compile(r'@answer:(\S+)', re.I)
_HEADER_RE = re.compile(r'^\s*#{1,3}\s+\S', re.M)
_TASK_KW = re.compile(r'\b(explain|describe|why|complete|write|implement|run|task|problem|fill in|answer)', re.I)
_EXPLAIN_KW = re.compile(r'\b(explain|describe|why|difference|discuss|reflect|summar)', re.I)


def _src(c):
    s = c.get("source")
    return "".join(s) if isinstance(s, list) else (s or "")


def _set_src(c, text):
    c["source"] = text
    return c


def _is_task(src):
    return bool(_TASK_KW.search(src))


def _is_header_only(src):
    # a section header that is NOT itself a task prompt
    return bool(_HEADER_RE.search(src)) and not _is_task(src)


def _gtype(src):
    return "explain" if _EXPLAIN_KW.search(src) else "code"


def _with_anchor(cell, aid, typ):
    src = _src(cell)
    cell = _set_src(cell, f"<!-- @anchor:{aid} type={typ} -->\n{src}")
    cell.setdefault("metadata", {})["grade_id"] = aid
    return cell


def _tag_answer(cell, aid):
    src = _src(cell)
    if _ANSWER_RE.search(src):
        return cell
    tag = f"# @answer:{aid}" if cell.get("cell_type") == "code" else f"<!-- @answer:{aid} -->"
    cell = _set_src(cell, f"{tag}\n{src}")
    cell.setdefault("metadata", {})["grade_id"] = f"{aid}-answer"
    return cell


def _make_answer(aid, typ):
    if typ in ("explain", "reflect"):
        return {"cell_type": "markdown", "metadata": {"grade_id": f"{aid}-answer"},
                "source": f"<!-- @answer:{aid} -->\n*(write your answer here — do not delete this cell)*"}
    return {"cell_type": "code", "execution_count": None, "outputs": [],
            "metadata": {"grade_id": f"{aid}-answer"},
            "source": f"# @answer:{aid}\n# YOUR CODE HERE  (do not delete this cell)"}


def _essay_pin(sec):
    aid = f"S{sec}R"     # R = reflection
    return [
        {"cell_type": "markdown", "metadata": {"grade_id": aid},
         "source": f"<!-- @anchor:{aid} type=reflect -->\n### Reflection — Section {sec}\n"
                   f"Before you continue: in a sentence or two, what was the key idea / lesson of this section?"},
        {"cell_type": "markdown", "metadata": {"grade_id": f"{aid}-answer"},
         "source": f"<!-- @answer:{aid} -->\n*(write your takeaway here — do not delete this cell)*"},
        {"cell_type": "markdown", "metadata": {},
         "source": f"> 💾 **Save and pin a revision now** (File → Save and pin revision), and name it "
                   f"**\"Section {sec}\"**. Do not delete the cells above."},
    ]


BANNER = ("> ⚠ **Do not delete or recreate the provided cells** (instructions and answer cells). Write "
          "your answers ONLY inside the provided answer cells. If a provided cell is deleted or replaced, "
          "your work in that part **may be excluded from grading**. Deleted a cell by accident? Open a "
          "FRESH copy of the template from the assignment link and paste your work into the matching "
          "answer cells, or use **File → Revision history** to restore. **Save and pin a revision at the "
          "end of each section.**")


def stamp(nb, pins_essays=True):
    cells = nb.get("cells", [])
    out = []
    # top banner (once)
    if not (cells and "may be excluded from grading" in _src(cells[0])):
        out.append({"cell_type": "markdown", "metadata": {"grade_id": "banner"}, "source": BANNER})
    sec, q, n_anchor, n_answer_ins, n_sec_pins = 0, 0, 0, 0, 0
    i = 0
    while i < len(cells):
        c = cells[i]; src = _src(c); ct = c.get("cell_type")
        if ct == "markdown" and _is_header_only(src):
            if pins_essays and sec >= 1 and q >= 1:     # close previous section with essay+pin
                out.extend(_essay_pin(sec)); n_sec_pins += 1
            sec += 1; q = 0
            out.append(c); i += 1; continue
        if ct == "markdown" and _is_task(src) and not _ANCHOR_RE.search(src):
            if sec == 0:
                sec = 1
            q += 1; aid = f"S{sec}Q{q}"; typ = _gtype(src)
            out.append(_with_anchor(c, aid, typ))
            nxt = cells[i + 1] if i + 1 < len(cells) else None
            if nxt is not None and not _is_header_only(_src(nxt)) and not _ANSWER_RE.search(_src(nxt)):
                out.append(_tag_answer(nxt, aid)); n_anchor += 1; i += 2; continue
            if nxt is None or _is_header_only(_src(nxt)):
                out.append(_make_answer(aid, typ)); n_answer_ins += 1
            n_anchor += 1; i += 1; continue
        out.append(c); i += 1
    if pins_essays and sec >= 1 and q >= 1:             # close the last section
        out.extend(_essay_pin(sec)); n_sec_pins += 1
    nb["cells"] = out
    return nb, {"sections": sec, "anchored": n_anchor, "answers_inserted": n_answer_ins, "section_pins": n_sec_pins}


def stamp_manifest(nb, manifest):
    """Stamp anchors per an AI-authored manifest — the RELIABLE path (the AI judged which cells are
    problems by READING them; no brittle keyword auto-detect, no code-vs-explain gate). Each entry:
    {anchor, instr (cell idx), answer (existing cell idx to tag @answer, or "insert"), type?}.
    The anchor just marks "grade HERE"; `type` is a soft hint. No essay/pin insertion (templates
    already carry their own section/pin notes)."""
    cells = nb["cells"]
    inserts = []
    for m in manifest:
        _with_anchor(cells[m["instr"]], m["anchor"], m.get("type", "task"))
        ans = m.get("answer")
        if ans == "insert":
            inserts.append((m["instr"] + 1, _make_answer(m["anchor"], m.get("type", "explain"))))
        elif isinstance(ans, int):
            _tag_answer(cells[ans], m["anchor"])
    for pos, cell in sorted(inserts, key=lambda x: x[0], reverse=True):
        cells.insert(pos, cell)
    nb["cells"] = cells
    return nb, {"anchored": len(manifest), "answers_inserted": len(inserts)}


def build(spec):
    """Assemble AI-authored cells onto an optional base notebook, then anchor via stamp_manifest.
    The reliable path for NEW templates: the AI authors problem/answer/reflection content (data);
    this splices it in and stamps. spec schema is in the module docstring."""
    if spec.get("base"):
        nb = json.load(open(spec["base"]))
    else:
        nb = {"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}
    cells = nb["cells"]
    if spec.get("banner") and not (cells and "may be excluded from grading" in _src(cells[0])):
        cells.insert(0, {"cell_type": "markdown", "metadata": {"grade_id": "banner"}, "source": BANNER})
    manifest = []

    def _md(t):
        cells.append({"cell_type": "markdown", "metadata": {}, "source": t})

    def _code(t):
        cells.append({"cell_type": "code", "execution_count": None, "outputs": [], "metadata": {}, "source": t})

    for item in spec["append"]:
        if "section" in item:
            _md("## " + item["section"])
        elif "markdown" in item:
            _md(item["markdown"])
        elif "code" in item:
            _code(item["code"])          # pre-filled example: run-only, never anchored (completeness)
        elif "problem" in item:
            p = item["problem"]
            _md(p["instr"]); ii = len(cells) - 1
            _code(p["answer"]); ai = len(cells) - 1
            manifest.append({"anchor": p["anchor"], "instr": ii, "answer": ai, "type": p.get("type", "code")})
        elif "reflection" in item:
            r = item["reflection"]
            prompt = r.get("prompt", "In a sentence or two: what was the key idea / lesson of this section?")
            title = r.get("title")            # e.g. "Section 3: Missing Data" -> heading names the section
            head = f"### Reflection — {title}" if title else "### Reflection"
            _md(f"{head}\n{prompt}"); ii = len(cells) - 1
            _md("*(write your takeaway here — do not delete this cell)*"); ai = len(cells) - 1
            manifest.append({"anchor": r["anchor"], "instr": ii, "answer": ai, "type": "reflect"})
            pin = r.get("pin")                # e.g. "Section 3" -> the exact revision name to type
            named = f"and name it **`{pin}`**" if pin else "and name it for this section"
            _md(f"> **Save and pin a revision now** — `File` → `Save and pin revision` — {named}. "
                "Do not delete the cells above.")
    nb, stats = stamp_manifest(nb, manifest)
    return nb, {**stats, "total_cells": len(nb["cells"])}


def enrich(spec):
    """Improve an EXISTING template IN PLACE: rewrite a problem's instruction + answer slot, and
    insert extra practice / challenge problems right after it. `build` can only APPEND to the end,
    which is useless for an existing chapter notebook whose problems are already interleaved.

    spec = {"base": "<in.ipynb>", "banner": true,
            "enrich": [ {"find": "Problem #1.1",      # substring of the instruction cell (unique)
                         "anchor": "P1.1", "type": "code",
                         "instr":  "<rewritten markdown — goal + steps + expected output>",
                         "answer": "<rewritten answer-slot source>",
                         "add": [ {"problem": {...}}, {"reflection": {...}}, {"code": "..."} ]}, ...]}

    Every key except `find` is optional: give `instr` alone to only fix wording, `add` alone to only
    append practice. Each `problem` (the original and every added one) is anchored, so an added
    exercise is a GRADED item — that is the point (nb-homework-create SKILL §1b)."""
    nb = json.load(open(spec["base"]))
    cells = nb["cells"]
    if spec.get("banner") and not (cells and "may be excluded from grading" in _src(cells[0])):
        cells.insert(0, {"cell_type": "markdown", "metadata": {"grade_id": "banner"}, "source": BANNER})
    manifest, report = [], []

    def _mk_md(t):
        return {"cell_type": "markdown", "metadata": {}, "source": t}

    def _mk_code(t):
        return {"cell_type": "code", "execution_count": None, "outputs": [], "metadata": {}, "source": t}

    def _expand(item):
        """One `add` item -> (cells, manifest-entries relative to the first cell)."""
        if "section" in item:
            return [_mk_md("## " + item["section"])], []
        if "markdown" in item:
            return [_mk_md(item["markdown"])], []
        if "code" in item:
            return [_mk_code(item["code"])], []          # example: run-only, never anchored
        if "problem" in item:
            p = item["problem"]
            typ = p.get("type", "code")
            # The answer slot must MATCH the type: an explain answer is prose, and prose in a code
            # cell is a SyntaxError the student cannot run (caught by the syntax gate, 2026-08-02).
            slot = _mk_md(p["answer"]) if typ in ("explain", "reflect") else _mk_code(p["answer"])
            return ([_mk_md(p["instr"]), slot],
                    [{"anchor": p["anchor"], "instr": 0, "answer": 1, "type": typ}])
        if "reflection" in item:
            r = item["reflection"]
            head = "### Reflection — %s" % r["title"] if r.get("title") else "### Reflection"
            prompt = r.get("prompt", "In a sentence or two: what was the key idea of this section?")
            pin = r.get("pin")
            named = "and name it **`%s`**" % pin if pin else "and name it for this section"
            return ([_mk_md("%s\n%s" % (head, prompt)),
                     _mk_md("*(write your takeaway here — do not delete this cell)*"),
                     _mk_md("> **Save and pin a revision now** — `File` -> `Save and pin revision` — "
                            "%s. Do not delete the cells above." % named)],
                    [{"anchor": r["anchor"], "instr": 0, "answer": 1, "type": "reflect"}])
        raise SystemExit("enrich: unknown add item %r" % (item,))

    for e in spec.get("enrich", []):
        find = e["find"]
        hits = [i for i, c in enumerate(cells) if find in _src(c)]
        if len(hits) != 1:
            raise SystemExit("enrich: %r matched %d cells (need exactly 1) — make `find` unique"
                             % (find, len(hits)))
        ii = hits[0]
        if e.get("instr"):
            _set_src(cells[ii], e["instr"])
        # A chapter notebook often splits ONE problem over several markdown cells (a `Problem #1.3`
        # header, then a separate "Let's divide 100 by 20 ..." line). Rewriting only the header
        # leaves the OLD wording sitting between the anchor and the answer slot, so the student
        # reads two conflicting instructions. `absorb: N` deletes the N markdown cells that follow —
        # their content belongs in the rewritten `instr`. (Found probing ch02 §1b, 2026-08-02.)
        for _ in range(e.get("absorb", 0)):
            if ii + 1 < len(cells) and cells[ii + 1]["cell_type"] == "markdown":
                del cells[ii + 1]
            else:
                raise SystemExit("enrich: absorb after %r hit a non-markdown cell — check the count"
                                 % find)
        # the answer slot = the next cell of the expected kind (code, or markdown for an explain task)
        want = "markdown" if e.get("type") in ("explain", "reflect") else "code"
        ai = next((j for j in range(ii + 1, min(ii + 4, len(cells)))
                   if cells[j]["cell_type"] == want), None)
        if ai is None:                                   # no slot present -> insert one
            cells.insert(ii + 1, _mk_code(e.get("answer", "# your code here\n"))
                         if want == "code" else _mk_md(e.get("answer", "*your answer here*")))
            ai = ii + 1
        elif e.get("answer"):
            _set_src(cells[ai], e["answer"])
        # Record the CELL OBJECTS, never the index: every later insert shifts indices, and a spec
        # whose entries are not in notebook order would then stamp the wrong cells.
        if e.get("anchor"):
            manifest.append({"anchor": e["anchor"], "instr": cells[ii], "answer": cells[ai],
                             "type": e.get("type", "code")})
        at = ai + 1                                      # insert additions right after the answer
        for item in e.get("add", []):
            new, ments = _expand(item)
            cells[at:at] = new
            for m in ments:
                manifest.append({"anchor": m["anchor"], "instr": new[m["instr"]],
                                 "answer": new[m["answer"]], "type": m["type"]})
            at += len(new)
        report.append("%s: +%d cells" % (find, at - (ai + 1)))

    pos = {id(c): i for i, c in enumerate(cells)}        # objects -> final indices
    resolved = sorted(({"anchor": m["anchor"], "type": m["type"],
                        "instr": pos[id(m["instr"])], "answer": pos[id(m["answer"])]}
                       for m in manifest), key=lambda m: m["instr"])
    nb, stats = stamp_manifest(nb, resolved)
    return nb, {**stats, "total_cells": len(nb["cells"]),
                "anchored": len(resolved), "enriched": report}


def syntax_gate(nb):
    """Every CODE cell must parse. A slot that raises SyntaxError on the student's first run cannot
    be completed and cannot be graded (no run -> no output to judge). The two shapes that keep
    shipping — `x =   # your expression here` and `x = # complete this code` — both look like helpful
    placeholders and neither is Python. Use `x = 0   # <-- replace 0 ...` instead (SKILL.md §1b).
    Colab magics (`!pip`, `%cd`) are skipped, not flagged."""
    import ast
    bad = []
    for i, c in enumerate(nb["cells"]):
        if c.get("cell_type") != "code":
            continue
        src = _src(c)
        if not src.strip() or any(l.lstrip().startswith(("!", "%")) for l in src.splitlines()):
            continue
        try:
            ast.parse(src)
        except SyntaxError as e:
            first = next((l for l in src.splitlines() if l.strip()), "")
            bad.append((i, e.msg, first[:70]))
    return bad


def clean_outputs(nb):
    """Strip every cell's outputs + execution_count. RUNNING the cells is a GRADED item — grade-nb
    scores a pre-filled example cell on completeness ("did they run it"). A template shipped with
    outputs hands the student the results AND destroys that signal. Always ship clean."""
    n = 0
    for c in nb["cells"]:
        if c.get("cell_type") == "code" and (c.get("outputs") or c.get("execution_count") is not None):
            c["outputs"], c["execution_count"] = [], None
            n += 1
    return n


def prune(nb, match, cell_type="markdown"):
    """Remove cells whose source contains `match`. Returns (nb, [(index, preview)]).

    WHY. `build`, `enrich` and `stamp` can insert and rewrite; none of them can delete. A
    template rewritten from an older base therefore keeps the older base's instruction cells
    sitting alongside the new ones, and the two can contradict each other. `01-strings_1`
    came out of its 2026-08-02 rewrite carrying BOTH the new per-section pin prompts
    (`rename it to Section N`, one at the end of each of seven sections) AND three leftovers
    from the January notebook (`Rename the current pinned revision to "Section 1/2/3"`)
    sitting in the MIDDLE of sections 4, 6 and 7. A student in section 4 was told to name the
    same pin two different things — and it was a student, not us, who noticed.

    Deleting the cell by hand in the JSON is what this replaces, so the removal is auditable:
    every dropped cell is printed, and `--dry` shows them without writing.

    MARKDOWN ONLY by default. A stray instruction is prose; a stray code cell may be an answer
    slot a student has already filled, and losing one is unrecoverable. Pass cell_type=None
    only deliberately.
    """
    kept, removed = [], []
    for i, c in enumerate(nb["cells"]):
        if (cell_type is None or c.get("cell_type") == cell_type) and match in _src(c):
            removed.append((i, " ".join(_src(c).split())[:90]))
            continue
        kept.append(c)
    nb["cells"] = kept
    return nb, removed


def _write(nb, out):
    stripped = clean_outputs(nb)
    if stripped:
        print(f"clean: stripped outputs from {stripped} cell(s) — templates ship unexecuted")
    bad = syntax_gate(nb)
    if bad:
        print("⛔ SYNTAX GATE — %d code cell(s) do not parse (SKILL.md §1b):" % len(bad))
        for i, msg, line in bad:
            print("   cell %-4d %-22s %s" % (i, msg, line))
        raise SystemExit("not written — fix the answer slots (use `x = 0   # <-- replace 0 ...`)")
    json.dump(nb, open(out, "w"), ensure_ascii=False, indent=1)
    print(f"wrote {out}")


def main(argv):
    ap = argparse.ArgumentParser(prog="nb_create.py")
    sub = ap.add_subparsers(dest="cmd")

    b = sub.add_parser("build", help="assemble authored cells (+optional base) then anchor")
    b.add_argument("spec")
    b.add_argument("-o", "--out", required=True)
    b.add_argument("--dry", action="store_true")

    e = sub.add_parser("enrich", help="rewrite an existing template's problem cells + add practice")
    e.add_argument("spec")
    e.add_argument("-o", "--out", required=True)
    e.add_argument("--dry", action="store_true")

    p_ = sub.add_parser("prune", help="remove template cells matching a string (leftovers from an older base)")
    p_.add_argument("infile")
    p_.add_argument("--match", required=True, help="substring; every MARKDOWN cell containing it is dropped")
    p_.add_argument("--any-type", action="store_true", help="also prune code cells (deliberate; they may hold student work)")
    p_.add_argument("-o", "--out", default=None)
    p_.add_argument("--dry", action="store_true")

    s = sub.add_parser("stamp", help="anchor an existing template's problem cells")
    s.add_argument("infile")
    s.add_argument("-o", "--out", default=None)
    s.add_argument("--manifest", default=None, help="AI-authored anchor manifest (JSON) — reliable path")
    s.add_argument("--pins-essays", action="store_true", default=True)
    s.add_argument("--no-pins-essays", dest="pins_essays", action="store_false")
    s.add_argument("--dry", action="store_true")

    a = ap.parse_args(argv)
    if a.cmd == "build":
        nb, stats = build(json.load(open(a.spec)))
        print(f"build: {stats}")
        if a.dry:
            print("--dry: not written"); return 0
        _write(nb, a.out); return 0

    if a.cmd == "enrich":
        nb, stats = enrich(json.load(open(a.spec)))
        print(f"enrich: {stats}")
        if a.dry:
            print("--dry: not written"); return 0
        _write(nb, a.out); return 0

    if a.cmd == "prune":
        nb = json.load(open(a.infile))
        nb, removed = prune(nb, a.match, cell_type=(None if a.any_type else "markdown"))
        print(f"prune: {len(removed)} cell(s) matched {a.match!r}")
        for i, preview in removed:
            print(f"   cell {i:<4} {preview}")
        if not removed:
            print("nothing matched — not written"); return 0
        if a.dry:
            print("--dry: not written"); return 0
        _write(nb, a.out or a.infile); return 0

    if a.cmd == "stamp":
        nb = json.load(open(a.infile))
        if a.manifest:
            nb, stats = stamp_manifest(nb, json.load(open(a.manifest)))
        else:
            nb, stats = stamp(nb, pins_essays=a.pins_essays)
        print(f"stamp: {stats}")
        if a.dry:
            print("--dry: not written"); return 0
        _write(nb, a.out or (a.infile.rsplit(".ipynb", 1)[0] + ".stamped.ipynb")); return 0

    ap.print_help(); return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
