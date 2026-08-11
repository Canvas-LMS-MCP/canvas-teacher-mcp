"""Selftest — runs before any grading session.

Two parts:
1. grep enforcement: forbid raw HTTP / pdftotext / OCR / gws calls outside lib/attachments.py.
2. positive selftest: load one known-good submission, verify attachments.read()
   returns expected_n == read_n. (Caller supplies the fixture path + expected_n.)
"""
import os
import re
import sys


FORBIDDEN_PATTERNS = [
    r"urllib\.request\.urlopen",
    r"requests\.get",
    r"http\.client",
    r"subprocess.*pdftotext",
    r"subprocess.*tesseract",
    r"from\s+ocrmac",
    r"subprocess.*\bgws\s+(drive|docs|slides)\s+(export|get)",
    # Browser automation must NEVER appear in engine code (per BrowserFetcher.md):
    r"from\s+playwright",
    r"import\s+playwright",
    r"import\s+selenium",
    r"from\s+selenium",
    r"import\s+pyppeteer",
    r"from\s+pyppeteer",
]


def _walk_py(root):
    for d, _, files in os.walk(root):
        for fn in files:
            if fn.endswith(".py"):
                yield os.path.join(d, fn)


def grep_forbidden(project_root, allow_files=None):
    """Return list of (file, pattern, line) violations.

    `allow_files` defaults to lib/attachments.py and selftest.py itself.
    """
    if allow_files is None:
        allow_files = ("lib/attachments.py", "selftest.py")
    violations = []
    for path in _walk_py(project_root):
        if any(path.endswith(a) for a in allow_files):
            continue
        try:
            content = open(path, "r", errors="replace").read()
        except Exception:  # noqa: BLE001
            continue
        for pat in FORBIDDEN_PATTERNS:
            for m in re.finditer(pat, content):
                # Find line number
                line_no = content[: m.start()].count("\n") + 1
                violations.append((path, pat, line_no))
    return violations


def positive_test(submission_fixture, expected_n, download_dir):
    """Run attachments.read on a known-good submission. Verify count check."""
    from .lib import attachments

    result = attachments.read(submission_fixture, download_dir=download_dir)
    if result["expected_n"] != expected_n:
        return False, f"expected_n={result['expected_n']} != fixture says {expected_n}"
    if result["read_n"] != result["expected_n"]:
        return False, f"read_n={result['read_n']} < expected_n={result['expected_n']}"
    return True, "ok"


def grader_contract():
    """Every registered grader must expose `grade` and DECLARE a `PRODUCES` set
    (lib/contract.py). Returns (ok, lines) — lines are printed either way so the
    declaration table is visible, not just its failures.

    Static check on purpose: it needs no Canvas, no submission and no network, so it runs
    at session start. It cannot catch a grader that declares a field and then returns it
    empty — that is caught live, per student, by contract.check() at core.py's call site.
    """
    from . import graders
    from .lib import contract

    lines, ok = [], True
    for name in graders.names():
        mod = graders.get(name)
        if not callable(getattr(mod, "grade", None)):
            lines.append(f"  ✗ {name}: no callable grade()")
            ok = False
            continue
        p = contract.produces(mod)
        if p is contract.UNDECLARED:
            lines.append(f"  ✗ {name}: no PRODUCES — cannot tell an intentionally-empty "
                         f"field from a dropped one")
            ok = False
            continue
        unknown = sorted(p - contract.DECLARABLE)
        if unknown:
            lines.append(f"  ✗ {name}: declares unknown field(s) {unknown}")
            ok = False
            continue
        lines.append(f"  ✓ {name}: {', '.join(sorted(p)) or '(nothing)'}")
    return ok, lines


# A field that ONE module owns as internal reference data, plus where it is allowed to appear.
# The point is not the field — it is that a claim about it stays TRUE by being re-checked.
# `code_data`/`code_breakdown` are gh-shaped extras quiz.py hands to Stage B; nothing in the
# engine reads them, which is why a non-gh sub-grader leaving them empty is harmless. Written
# as a comment that would rot the day someone wired a consumer, so it is a test instead.
_REFERENCE_ONLY = {
    "code_data": "graders/quiz.py",
    "code_breakdown": "graders/quiz.py",
}


def reference_only_fields(engine_root):
    """Fail if a REFERENCE-ONLY field gained a consumer outside its owning module.

    Returns (ok, lines). Not a style rule: quiz.py's `code_data` note tells a reader that a
    non-gh sub-grader leaving it empty breaks nothing. The moment core.py / report_generator /
    the poster starts reading it, that stops being true and the empty dict becomes a real bug —
    so the claim is verified on every run instead of being trusted.
    """
    lines, ok = [], True
    for field, owner in sorted(_REFERENCE_ONLY.items()):
        hits = []
        for path in _walk_py(engine_root):
            rel = os.path.relpath(path, engine_root)
            if rel.replace(os.sep, "/") == owner or rel.endswith("selftest.py"):
                continue
            try:
                with open(path, encoding="utf-8") as fh:
                    for i, line in enumerate(fh, 1):
                        if field in line and not line.lstrip().startswith("#"):
                            hits.append(f"{rel}:{i}")
            except OSError:
                continue
        if hits:
            ok = False
            lines.append(f"  ✗ '{field}' is documented as reference-only (owner {owner}) but is "
                         f"now read at: {', '.join(hits)} — either revert that, or update the "
                         f"note in {owner} and this table, because a non-gh sub-grader leaves "
                         f"this field EMPTY.")
        else:
            lines.append(f"  ✓ {field}: reference-only, owner {owner}")
    return ok, lines


def commit_quality_contract():
    """COMMIT QUALITY (GRADING §4F.6): diff CONTENT must separate a semicolon from a logic fix,
    and a burst of micro-commits must not buy `wide` on count alone.

    These are the two failures that made the commit item collapse to two values (7 or 8) across
    a whole chapter: size-only classification cannot see WHAT changed, and raw commit count
    cannot see that twelve commits one minute apart are one cycle's worth of evidence.
    """
    from .lib.commit_inspect import classify_diff, inspect, commit_quality

    def P(text):
        return [{"filename": "src/Main.java", "patch": text}] if text else []

    cases = [
        ("semicolon added", "-        sc.close()\n+        sc.close();", "syntax_fix"),
        ("import uncommented",
         "-// import java.util.InputMismatchException;\n+import java.util.InputMismatchException;",
         "syntax_fix"),
        ("i = 0 -> i = -1", "-        int i = 0;\n+        int i = -1;", "logic_fix"),
        ("&& -> ||",
         "-        if (b >= e && b < 2 && e >= 100) {\n+        if (b >= e || b < 2 || e >= 100) {",
         "logic_fix"),
        ("index i-1 -> i-2",
         "-            seq[i] = seq[i-1] + seq[i-1];\n+            seq[i] = seq[i-1] + seq[i-2];",
         "logic_fix"),
        ("swap operand fixed",
         "-                numbers[right] = numbers[left];\n+                numbers[right] = temp;",
         "logic_fix"),
        ("one line inserted", "+        System.out.print(numbers[i]);", "assembly"),
        ("empty commit", "", "empty"),
    ]
    ok, lines = True, []
    for name, patch, want in cases:
        got = classify_diff(P(patch))
        good = got == want
        ok = ok and good
        lines.append(f"  {'OK ' if good else 'FAIL'}  classify_diff {name:<22} -> {got} "
                     f"(expected {want})")

    def hist(offsets):
        commits = [{"date": "2026-07-26T00:%02d:%02dZ" % (int(m), int(m % 1 * 60)),
                    "additions": 1, "deletions": 0, "message": "x"} for m in offsets]
        diffs = [{"sha": "c%d" % i, "message": "x", "patches": P("+   int x = 1;")}
                 for i in range(len(offsets))]
        return inspect(commits, diffs)

    # A burst must NOT reach `wide`; a spread-out history must.
    for name, offsets, want_wide in [
            ("spread 8 commits / 13.7 min", [0, 2, 3.5, 6, 6.5, 9, 11, 13.7], True),
            ("burst 3 commits / 0.7 min", [0, 0.3, 0.7], False),
            ("micro-burst 12 commits / 4.4 min", [i * 0.4 for i in range(12)], False)]:
        r = hist(offsets)
        good = bool(r["wide"]) is want_wide
        ok = ok and good
        lines.append(f"  {'OK ' if good else 'FAIL'}  effective_cycles {name:<28} "
                     f"n={r['n']} cycles={r['effective_cycles']} wide={r['wide']}")

    # The grid must not reward a purely-additive history, and `trivial` must waive it (§4.8).
    asm = hist([0, 2, 4, 6])
    q_norm = commit_quality(asm, None, "normal")
    q_triv = commit_quality(asm, None, "trivial")
    # Every below-full tier must carry a fix clause, or comment_render refuses to render it
    # (§4.5.3). The `logic` row reached below-full via the passing-commit override with no fix
    # clause at all, which only surfaced as a failed render mid-batch.
    # "The autograder was red" is NOT debugging on its own: an INCOMPLETE program is red on
    # every push too. A history that never deletes a line never took anything back, so it
    # cannot be repairing — otherwise a line-by-line assembler scores as a debugger.
    red = [{"created_at": "2026-07-26T00:0%d:00Z" % i, "conclusion": "failure",
            "head_sha": "c%d" % i} for i in range(4)]
    assembler = hist([0, 2, 4, 6])                       # all commits +1/-0
    q_asm_red = commit_quality(assembler, None, "normal", red)
    revised = hist([0, 2, 4, 6])
    revised["commits"][2]["deletions"] = 3               # something was actually taken back
    q_rev_red = commit_quality(revised, None, "normal", red)
    for label, cond in [("no deletion ever => red runs do NOT prove repair",
                         q_asm_red["row"] == "assembly"),
                        ("a revised line + red runs => repair credited",
                         q_rev_red["row"] == "logic")]:
        ok = ok and cond
        lines.append(f"  {'OK ' if cond else 'FAIL'}  repair-after-failure {label}")

    logic_hist = hist([0, 2, 4, 6])
    logic_hist["n_logic_fix"], logic_hist["n_assembly"] = 1, 3
    q_oneshot = commit_quality(logic_hist, {"verdict": "oneshot_bulk", "note": "x"}, "normal")
    for label, cond in [("assembly capped below full", q_norm["tier"] < 1.0),
                        ("trivial waives the grid", q_triv.get("waived") is True),
                        ("every below-full tier carries a 'For full marks' fix",
                         all(any("full marks" in r.lower() for r in q["reasons"])
                             for q in (q_norm, q_oneshot) if q["tier"] < 1.0)),
                        ("unknown difficulty is flagged, not invented",
                         commit_quality(asm, None, None)["needs_difficulty"] is True),
                        ("assembly row opens the match slot for a reader",
                         "match_slot" in q_asm_red)]:
        ok = ok and cond
        lines.append(f"  {'OK ' if cond else 'FAIL'}  grid {label}")

    # THE MISSING-STATEMENT REPAIR (real history, PRUTHA VARUDE A50, verified 2026-08-02).
    # She pushed a while loop with no increment — an infinite loop — the run went red, and the
    # next commit added `count++` inside that same block. Nothing was ever deleted, so the
    # deletion prerequisite alone scored this as assembly: the exact behaviour the comment asks
    # students for, marked down. The brace is what separates the two commits.
    from .lib.commit_inspect import _inserts_into_existing_block as _ins
    new_block = [{"patch": "@@ -14,6 +14,9 @@\n \n         result = 1.0;\n         int count = 0;\n"
                           "+        while (count < absPower) {\n+            result = result * base;\n"
                           "+        }\n \n         // TODO"}]
    inside = [{"patch": "@@ -16,6 +16,7 @@\n         int count = 0;\n         while (count < absPower) {\n"
                        "             result = result * base;\n+            count++;\n         }\n \n         // TODO"}]
    red4 = [{"created_at": "2026-07-26T00:0%d:00Z" % i, "conclusion": "failure"} for i in range(4)]
    adder = hist([0, 2, 4, 6])                            # every commit +1/-0, no deletions
    for r in adder["commits"]:
        r["interior_insert"] = True                       # …but each edits an existing block
    q_ins = commit_quality(adder, None, "normal", red4)
    for label, cond in [
            ("a commit that brings its own braces is NEW structure", _ins(new_block) is False),
            ("a braceless line between existing lines is an EDIT", _ins(inside) is True),
            ("insert-into-existing-block + red runs => repair credited, no deletion needed",
             q_ins["row"] == "logic")]:
        ok = ok and cond
        lines.append(f"  {'OK ' if cond else 'FAIL'}  missing-statement repair {label}")

    # POST-PASS COMMITS ARE OUT OF SCOPE. Tidying up after the autograder went green did not
    # build the passing program, and counting it inflates exactly the axis the grid rewards:
    # the three commits after the pass below turn a 2-cycle history into a 5-cycle `wide` one.
    spread = hist([0, 2, 4, 6, 8, 10])                   # c0..c5, all spaced > 1 min
    q_all = commit_quality(spread, {"sha": "c5"}, "normal")      # pass = LAST commit: nothing cut
    q_cut = commit_quality(spread, {"sha": "c2"}, "normal")      # pass = 3rd: c3,c4,c5 excluded
    q_miss = commit_quality(spread, {"sha": "zz9"}, "normal")    # boundary unlocatable
    for label, cond in [
            ("pass on the last commit trims nothing",
             q_all["n_excluded_after_pass"] == 0 and q_all["effective_cycles"] == 5),
            ("commits after the pass are dropped from the count",
             q_cut["n_excluded_after_pass"] == 3),
            ("dropping them re-narrows the window (5 cycles -> 2)",
             q_cut["effective_cycles"] == 2 and q_cut["wide"] is False),
            ("an unlocatable passing commit trims NOTHING and says so",
             q_miss["n_excluded_after_pass"] == 0 and q_miss["pass_boundary_found"] is False)]:
        ok = ok and cond
        lines.append(f"  {'OK ' if cond else 'FAIL'}  post-pass scope {label}")

    # A RE-GRADE MAY NOT LOWER A POSTED SCORE. The rule lived only in prose, so it held only
    # while someone compared every row by hand — and the failure is invisible: the student who
    # resubmitted and did slightly worse quietly loses marks for having resubmitted at all.
    import json as _json
    import os as _os
    import tempfile
    from .report_generator import regrade_floor_issues
    _posted = {"students": [{"uid": 1, "score": 45}, {"uid": 2, "score": 30}]}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as _fh:
        _json.dump(_posted, _fh)
        _pp = _fh.name
    _mk = lambda uid, tot, **kw: dict({"uid": uid, "name": "T", "earned": {"x": tot}}, **kw)
    for label, cond in [
            ("a lower re-grade BLOCKS",
             bool(regrade_floor_issues({"students": [_mk(1, 44)]}, _pp))),
            ("an equal or higher re-grade passes",
             not regrade_floor_issues({"students": [_mk(1, 45), _mk(2, 31)]}, _pp)),
            ("bonus counts toward the floor",
             not regrade_floor_issues({"students": [_mk(1, 40, bonus=5)]}, _pp)),
            ("allow_lower is the deliberate escape hatch",
             not regrade_floor_issues({"students": [_mk(1, 20, allow_lower=True)]}, _pp)),
            ("no prior record => first grading, gate silent",
             not regrade_floor_issues({"students": [_mk(1, 1)]}, "/nonexistent.json"))]:
        ok = ok and cond
        lines.append(f"  {'OK ' if cond else 'FAIL'}  re-grade floor {label}")
    _os.unlink(_pp)

    # THE AMBIGUOUS CASE: commits look like assembly, the write-up describes debugging. It is
    # neither full marks nor the floor, and the render must refuse to let it pass undecided.
    from .report_generator import commit_tier_issues
    base = {"commit_gate": True,
            "rubric": [{"item": "Commit history", "max": 8}],
            "students": [{"uid": 1, "name": "T", "earned": {"Commit history": 8},
                          "reasons": {"Commit history": "x"},
                          "commit_quality": {"engine_score": 5, "row": "assembly",
                                             "effective_cycles": 0}}]}
    import copy
    undecided = commit_tier_issues(copy.deepcopy(base))
    d_full = copy.deepcopy(base); d_full["students"][0]["elab_commit_match"] = "claimed_only"
    claimed_at_full = commit_tier_issues(d_full)
    d_ok = copy.deepcopy(base); d_ok["students"][0]["elab_commit_match"] = "claimed_only"
    d_ok["students"][0]["earned"]["Commit history"] = 7
    claimed_docked = commit_tier_issues(d_ok)
    for label, cond in [("undecided match on an assembly row BLOCKS", bool(undecided)),
                        ("claimed_only at full marks BLOCKS", bool(claimed_at_full)),
                        ("claimed_only docked by 1 passes", not claimed_docked)]:
        ok = ok and cond
        lines.append(f"  {'OK ' if cond else 'FAIL'}  elab-vs-commit {label}")
    return ok, lines


def main(project_root):
    print(f"=== selftest in {project_root} ===")
    violations = grep_forbidden(project_root)
    if violations:
        print("FORBIDDEN PATTERNS FOUND:")
        for path, pat, line in violations:
            print(f"  {path}:{line}  matches  {pat}")
        return 1
    print("✓ grep enforcement passed (no raw HTTP/PDF/OCR outside attachments.py)")

    ok, lines = grader_contract()
    print("grader contract (PRODUCES declarations):")
    for ln in lines:
        print(ln)
    if not ok:
        return 1
    print("✓ grader contract passed")

    ok2, lines2 = reference_only_fields(project_root)
    print("reference-only fields (claims re-verified, not trusted):")
    for ln in lines2:
        print(ln)
    if not ok2:
        return 1

    ok3, lines3 = commit_quality_contract()
    print("commit quality (diff CONTENT + time-filtered COUNT, GRADING §4F.6):")
    for ln in lines3:
        print(ln)
    if not ok3:
        return 1
    print("✓ commit quality contract passed")
    return 0


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
    sys.exit(main(root))
