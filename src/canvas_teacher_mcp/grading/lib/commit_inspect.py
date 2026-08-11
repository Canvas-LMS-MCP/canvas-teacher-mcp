"""Commit-history inspection for GitHub Classroom student repos.

Assesses whether a student's commit history reflects real iterative
development (GRADING.md Part B section 4): commit count, per-commit diff
size classification (debug edit vs bulk dump vs wholesale rewrite), and
the time span / spacing of commits.

Pure analysis — no network. The caller (graders/gh.py) supplies the list
of student-authored commits, each already carrying date + diff stats.
"""
import difflib
import re
from datetime import datetime, timezone


# RUNTIME/logic/test-failure error markers in commit messages (GRADING.md Part B §4F.6).
# This is an ADVANCED course: genuine development hits runtime errors (IndexError, wrong
# output, failing tests, …), and fixing one costs real minutes — so a real history leaves
# several such commits. A history with commits but NO runtime-error signal (only syntax
# typos, or a clean forward build) cannot earn full commit-quality marks. SyntaxError /
# indentation are EXCLUDED on purpose — a syntax-only fix is not a runtime debug cycle.
_RUNTIME_ERR_RE = re.compile(
    r"index\s*error|type\s*error|name\s*error|value\s*error|key\s*error|attribute\s*error|"
    r"zero\s*division|recursion\s*error|assertion|traceback|out of range|not defined|"
    r"infinite\s*loop|wrong\s+(output|list|result|order|number)|"
    r"still\s+(failing|failed|broken|wrong)|test.{0,12}fail|fail(ing|ed)|"
    r"didn.?t\s+work|doesn.?t\s+work|not\s+working|no\s+output|only\s+print|out of bound",
    re.I)


_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)   # sort fallback for an unparsable stamp


def _parse_dt(s):
    try:
        return datetime.fromisoformat((s or "").replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        return None


def classify_commit(additions, deletions):
    """Classify one commit by its diff size.

    - trivial  : negligible change (<= 3 lines touched)
    - bulk     : large chunk added with little/no deletion (whole-solution dump)
    - rewrite  : large delete AND large add (the file swapped out wholesale)
    - debug    : small/medium targeted edit (the healthy debugging signal)
    """
    a, d = additions or 0, deletions or 0
    if a + d <= 3:
        return "trivial"
    if a >= 25 and d <= 6:
        return "bulk"
    if a >= 15 and d >= 15:
        return "rewrite"
    return "debug"


SIM_THRESHOLD = 0.55     # a -/+ pair this similar is "the SAME line, edited" (not a replacement)
GAP_COUNTABLE = 1.0      # a commit closer than this to the previous one is NOT a separate cycle
CYCLES_WIDE = 3          # this many effective cycles = the process is wide enough to see

# Residual tokens that mean the edit was SYNTAX ONLY. If everything that changed between the
# old and the new line is in here, the LOGIC did not change — a semicolon, a brace, a comma,
# uncommenting an import. §4F.6.4: "the only failures that ever occurred were syntax".
_SYNTAX_ONLY_RE = re.compile(r"^[\s;{}()\[\],]*$")
_IMPORT_RE = re.compile(r"^\s*(//\s*)?import\b")
# What makes an edit LOGIC: an operator, a numeric literal, or an index expression changed.
# `i = 0` -> `i = -1` (literal), `&&` -> `||` (operator), `seq[i-1]` -> `seq[i-2]` (index).
_LOGIC_TOKEN_RE = re.compile(r"(<=|>=|==|!=|&&|\|\||[<>+\-*/%]|\b\d+\b)")


def _strip_code(line):
    """Normalize a source line for comparison: drop leading +/-, collapse whitespace."""
    return re.sub(r"\s+", " ", (line or "")[1:]).strip()


def _is_comment(s):
    return s.startswith("//") or s.startswith("*") or s.startswith("/*")


def _uncomment(s):
    """The code a commented-out line would become: `// import x;` -> `import x;`."""
    return re.sub(r"^\s*(//+|/\*+|\*+)\s*", "", s or "").strip()


def classify_diff(patches):
    """Classify ONE commit by what its diff actually CHANGED (GRADING §4F.6.4).

    Diff SIZE (classify_commit) cannot tell a semicolon from a fixed loop bound: both are
    "+1/-1". This reads the content instead, which is what the gh.py collector gathers the
    patch text FOR ("the DIFF the AI must READ to judge substance — semicolon fix vs a real
    error fix"). No network, no heuristics about the message (messages are gameable; the
    diff is what the student actually did).

    `patches`: [{filename, patch}] as fetched per commit. Returns one of:
      empty       — nothing changed (or whitespace/comments only). Count-padding, not work.
      assembly    — additions only, no line was replaced. The file GREW; nothing was fixed.
                    A run of these ending in a pass is the one-shot shape (§4F.6.4).
      syntax_fix  — a line was edited, but everything that changed is punctuation/import.
                    The logic never failed; only the compiler complained.
      logic_fix   — a line was edited and an operator / literal / index changed.
                    THIS is the shape that proves the algorithm itself failed and was fixed,
                    and it counts even when the edit is one character (`i = 0` -> `i = -1`).
      rewrite     — lines replaced wholesale (low similarity): a different approach, not an edit.
    """
    minus, plus = [], []
    for p in (patches or []):
        for raw in ((p or {}).get("patch") or "").splitlines():
            if raw.startswith("---") or raw.startswith("+++") or raw.startswith("@@"):
                continue
            if raw.startswith("-"):
                minus.append(raw)
            elif raw.startswith("+"):
                plus.append(raw)
    raw_dels = [s for s in (_strip_code(x) for x in minus) if s]
    raw_adds = [s for s in (_strip_code(x) for x in plus) if s]
    dels = [s for s in raw_dels if not _is_comment(s)]
    adds = [s for s in raw_adds if not _is_comment(s)]

    if not raw_dels and not raw_adds:
        return "empty"
    if not dels and not adds:
        return "empty"          # whitespace / comment churn only — count-padding, not work
    if not dels:
        # No CODE line was replaced. One case still counts as an edit rather than growth:
        # a commented-out line being uncommented (the starter ships `// import …`), which is
        # a deletion of a comment plus an addition of its own body.
        bodies = [_uncomment(s) for s in raw_dels if _is_comment(s)]
        if any(difflib.SequenceMatcher(None, b, a).ratio() >= SIM_THRESHOLD
               for b in bodies for a in adds):
            return "syntax_fix"
        return "assembly"

    # Pair each deleted line with its most similar added line — that pair is "one edited line".
    verdicts, used = [], set()
    for d in dels:
        best_i, best_r = None, 0.0
        for i, a in enumerate(adds):
            if i in used:
                continue
            r = difflib.SequenceMatcher(None, d, a).ratio()
            if r > best_r:
                best_i, best_r = i, r
        if best_i is None or best_r < SIM_THRESHOLD:
            verdicts.append("rewrite")
            continue
        used.add(best_i)
        a = adds[best_i]
        # The residual = exactly the CHARACTERS that differ. Token-level comparison misses a
        # change inside a token: `sc.close()` and `sc.close();` share no whitespace token at
        # all, so a semicolon would look like a wholesale replacement.
        sm = difflib.SequenceMatcher(None, d, a)
        residual = "".join(d[i1:i2] + a[j1:j2]
                           for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != "equal")
        if _IMPORT_RE.match(d) or _IMPORT_RE.match(a):
            verdicts.append("syntax_fix")
        elif _SYNTAX_ONLY_RE.match(residual):
            verdicts.append("syntax_fix")
        elif _LOGIC_TOKEN_RE.search(residual):
            verdicts.append("logic_fix")
        else:
            # An identifier was swapped inside an expression (numbers[left] -> temp): logic.
            verdicts.append("logic_fix")

    for v in ("logic_fix", "rewrite", "syntax_fix"):
        if v in verdicts:
            return v
    return "assembly"


def inspect(commits, commit_diffs=None):
    """`commits`: list of dicts with keys date, additions, deletions, message
    — already filtered to student-authored commits. Returns an assessment.

    `commit_diffs` (optional, same order as `commits`): [{sha, message, patches}] — when
    given, each commit is ALSO classified by diff CONTENT (classify_diff) and the per-commit
    time GAPS are computed, which together yield `effective_cycles`: the number of commits
    that both carry real content and sit at least GAP_COUNTABLE minutes after the previous
    one. Twelve commits fired one minute apart are ONE cycle's worth of evidence, not twelve
    — count without the time filter is exactly what a burst of micro-commits games.
    """
    diffs = list(commit_diffs or [])
    rows = []
    for i, c in enumerate(commits or []):
        dt = _parse_dt(c.get("date"))
        row = {
            "dt": dt,
            "additions": c.get("additions") or 0,
            "deletions": c.get("deletions") or 0,
            "message": (c.get("message") or "").splitlines()[0][:100] if c.get("message") else "",
            "kind": classify_commit(c.get("additions"), c.get("deletions")),
        }
        if i < len(diffs):
            row["sha"] = (diffs[i] or {}).get("sha")
            row["content"] = classify_diff((diffs[i] or {}).get("patches"))
            row["interior_insert"] = _inserts_into_existing_block((diffs[i] or {}).get("patches"))
        rows.append(row)
    dated = sorted([r for r in rows if r["dt"]], key=lambda r: r["dt"])

    # PER-COMMIT GAPS + EFFECTIVE CYCLES. The first commit has no predecessor (it is the repo
    # being seeded), so it is never a cycle. A commit counts only if it is BOTH separated in
    # time AND carries real content — that is the combination `count alone` misses.
    for k, r in enumerate(dated):
        r["gap_min"] = (round((r["dt"] - dated[k - 1]["dt"]).total_seconds() / 60.0, 2)
                        if k else None)
    effective_cycles = sum(
        1 for r in dated
        if r.get("gap_min") is not None and r["gap_min"] >= GAP_COUNTABLE
        and r.get("content") not in ("empty",))
    contents = [r.get("content") for r in rows if r.get("content")]
    n = len(rows)
    span_min = ((dated[-1]["dt"] - dated[0]["dt"]).total_seconds() / 60.0
                if len(dated) >= 2 else 0.0)
    kinds = [r["kind"] for r in rows]
    # Commit QUALITY (§4F.6): how many commit messages reference a RUNTIME/logic/test error.
    n_runtime_err = sum(1 for r in rows if _RUNTIME_ERR_RE.search(r["message"] or ""))
    return {
        "n": n,
        "span_minutes": round(span_min, 1),
        "kinds": kinds,
        "n_debug": kinds.count("debug"),
        "n_bulk": kinds.count("bulk"),
        "n_rewrite": kinds.count("rewrite"),
        "n_runtime_err": n_runtime_err,
        "has_runtime_err": n_runtime_err > 0,
        "compressed": n >= 2 and span_min < 10.0,
        "first_is_bulk": bool(dated) and dated[0]["kind"] == "bulk",
        # CONTENT axis (only when commit_diffs was supplied — else all zero and `wide` is None)
        "n_logic_fix": contents.count("logic_fix"),
        "n_syntax_fix": contents.count("syntax_fix"),
        "n_assembly": contents.count("assembly"),
        "n_rewrite_diff": contents.count("rewrite"),
        "n_empty_commits": contents.count("empty"),
        "has_content": bool(contents),
        # TIME x COUNT axis
        "gaps_min": [r.get("gap_min") for r in dated if r.get("gap_min") is not None],
        "effective_cycles": effective_cycles,
        "wide": (effective_cycles >= CYCLES_WIDE) if contents else None,
        "commits": rows,
    }


_TRIVIAL_FLIP_LINES = 3      # a passing commit this small changed nothing of substance
_BULK_SHARE = 0.60           # this much of ALL added lines arriving in the passing commit


def pass_commit_analysis(commit_diffs, run_history, insp=None):
    """THE PASSING COMMIT — what actually flipped the autograder to green (GRADING §4F.6.4).

    The decisive question is not "how many commits" but **did the passing algorithm ever
    fail?** So look at the commit whose run first went green:

      · it carries the BULK of the solution  → the algorithm was never run before it passed.
        One shot, first try, on a problem the student had never executed. (A61: "Second
        Commit" +24/-3, green 3 minutes after "First Commit".)
      · it is a one-line / semicolon TRIVIALITY → everything else was already correct, so the
        only failures that ever happened were syntax; the LOGIC never failed either.

    Both shapes mean the same thing: no visible error→fix cycle on the real algorithm. Nobody
    writes a correct algorithm first try on a problem they never ran, so this is the shape to
    catch — commit COUNT does not catch it (three commits three minutes apart look "fine").

    `commit_diffs` = [{sha (short), message, patches}]; `run_history` = [{created_at,
    conclusion, head_sha}] oldest→newest; `insp` = inspect() result (per-commit add/del).
    Returns {} when the data isn't there (no runs, no head_sha) — it never guesses.
    """
    runs = [r for r in (run_history or []) if r.get("head_sha")]
    first_pass = next((r for r in runs if r.get("conclusion") == "success"), None)
    if not first_pass:
        return {}
    sha = (first_pass.get("head_sha") or "")[:7]
    rows = (insp or {}).get("commits") or []
    idx = next((i for i, d in enumerate(commit_diffs or [])
                if (d.get("sha") or "")[:7] == sha), None)
    if idx is None:
        return {}          # the passing run belongs to a commit we did not read (e.g. bot)
    row = rows[idx] if idx < len(rows) else {}
    add, dele = row.get("additions") or 0, row.get("deletions") or 0
    total_add = sum((r.get("additions") or 0) for r in rows) or 0
    share = round(add / total_add, 2) if total_add else None
    prior_fail = sum(1 for r in runs
                     if (r.get("created_at") or "") < (first_pass.get("created_at") or "")
                     and r.get("conclusion") == "failure")
    # WHAT the passing commit changed (not just how much). A "+1/-1" that flips `&&` to `||`
    # is the end of a real debugging cycle; a "+1/-1" that adds a semicolon means the LOGIC
    # never failed, only the compiler complained — and diff SIZE cannot tell them apart.
    content = classify_diff((commit_diffs[idx] or {}).get("patches"))
    if share is not None and share >= _BULK_SHARE:
        verdict = "oneshot_bulk"
        note = (f"the passing commit carries {int(share * 100)}% of all the code added "
                f"(+{add}/-{dele}) — the algorithm passed the first time it was ever run")
    elif content == "empty":
        # A commit that changes nothing cannot be the fix. (Seen live: an empty "Trigger
        # autograder" commit was scored `real_fix: substantive change (+0/-0)` because the
        # trivial branch below is guarded on prior_fail and this one had a failing run.)
        verdict = "oneshot_trivial"
        note = ("the passing commit changed NOTHING (+0/-0) — it re-ran the autograder on code "
                "that was already complete; the fix is in an earlier commit")
    elif content == "syntax_fix" and (add + dele) <= _TRIVIAL_FLIP_LINES:
        # Trivial AND syntax-only. Prior failing runs do not rescue this: if the only edit that
        # ever flipped it green was punctuation, every failure before it was the compiler, so
        # the ALGORITHM was never observed to fail (§4F.6.4 oneshot_trivial).
        verdict = "oneshot_trivial"
        note = (f"the passing commit changed only {add + dele} line(s) (+{add}/-{dele}) and the "
                f"edit is punctuation/import only — the logic itself never failed, only the "
                f"compiler ({prior_fail} failing run(s) before it)")
    elif (add + dele) <= _TRIVIAL_FLIP_LINES and prior_fail == 0:
        # A one-line flip is only damning when NOTHING ever failed before it: the code was
        # already correct and was never run. The SAME one-line flip AFTER failing runs is the
        # opposite — it is the fix at the end of a real debugging cycle, which is exactly what
        # we want to see. (Measured on A61: a "+1/-1" pass after 4 and 9 failing runs — the two
        # most diligent students in the class — which the first cut of this rule mislabelled.)
        verdict = "oneshot_trivial"
        note = (f"the passing commit changed only {add + dele} line(s) (+{add}/-{dele}) and no "
                f"run had ever failed before it — the code was already correct and was never "
                f"executed until it passed")
    else:
        verdict = "real_fix"
        note = (f"the passing commit is a substantive change (+{add}/-{dele}) after "
                f"{prior_fail} failing run(s)")
    return {"sha": sha,
            "message": (commit_diffs[idx] or {}).get("message") or row.get("message") or "",
            "additions": add, "deletions": dele, "added_share": share,
            "content": content,
            "passed_at": first_pass.get("created_at"), "prior_failing_runs": prior_fail,
            "verdict": verdict, "note": note, "oneshot": verdict.startswith("oneshot")}


# The grid (GRADING §4F.6, agreed 2026-08-01). CONTENT decides the row, COUNT-filtered-by-TIME
# decides the column. Time never decides alone: a one-minute gap that flips `i = 0` to `i = -1`
# IS debugging, and a fast student must not be punished for being fast. Time only separates the
# rows where nothing was ever fixed.
_TIER_GRID = {                 # (row, wide) -> fraction of the commit item
    ("logic", True): 1.00, ("logic", False): 0.875,     # 8 / 7  of 8
    ("syntax", True): 0.75, ("syntax", False): 0.625,   # 6 / 5
    ("assembly", True): 0.625, ("assembly", False): 0.50,  # 5 / 4
}
_DIFFICULTY_FLOOR = {"trivial": None, "normal": 0.625, "advanced": 0.50}


def _inserts_into_existing_block(patches):
    """True when a commit adds a statement INSIDE a block that already existed.

    This is the second way to prove a repair, and it exists because the deletion test alone
    convicts the honest case. Measured on a real history (PRUTHA VARUDE, A50):

        95ede5f "while loop"            + while (count < absPower) {
                                        +     result = result * base;
                                        + }                    <- no increment: infinite loop
        2cd2e7c "forgot to add the count"   + count++;         <- pure +1 line, INSIDE that block

    She pushed a hanging program, the run went red, and the next commit fixed it — exactly the
    behaviour the comment asks students for — yet nothing was ever deleted, so the deletion
    prerequisite scored her as an assembler.

    The distinction that separates the two commits is the BRACE. A commit that brings its own
    `{`/`}` is introducing new structure (assembling); a commit whose added lines carry no brace
    and sit between two lines of untouched code is editing structure that was already there. The
    latter, landing on a red build, is a repair.
    """
    for p in patches or []:
        lines = ((p or {}).get("patch") or "").splitlines()
        run, prev_ctx = [], False
        for ln in lines + [" "]:                       # sentinel closes a trailing run
            if ln.startswith("+") and not ln.startswith("+++"):
                run.append(ln[1:])
                continue
            is_ctx = ln.startswith(" ") and ln.strip()
            if run:
                body = "".join(run)
                # Braces => new block. Context on BOTH sides => it landed between existing code,
                # not appended past the end of what was written before.
                if "{" not in body and "}" not in body and body.strip() and prev_ctx and is_ctx:
                    return True
                run = []
            prev_ctx = bool(is_ctx)
    return False


def _repairs_after_failure(insp, run_history):
    """Commits that landed while the autograder was RED — i.e. repairs, whatever their shape.

    Diff shape alone has a systematic blind spot: a logic bug fixed by ADDING the missing
    statement (`count = 0;`, `prev = current;`, `left++;`) is a pure addition and classifies as
    `assembly`, indistinguishable from assembling new code. Whether the program was BROKEN at
    that moment is not visible in the diff — but it is visible on the server, because the run
    on the previous commit failed. That conclusion is GitHub's, not the student's, so it cannot
    be written to look better than it was.
    """
    # Compare DATETIMES, never the raw strings. The two sides arrive in different shapes and a
    # lexicographic compare silently answers "no run preceded this commit" for every commit:
    #   commit dt   "2026-07-27 00:38:41+00:00"   (json.dump(default=str) -> SPACE separator)
    #   run created "2026-07-27T00:25:12Z"        (GitHub -> 'T' separator, 'Z' zone)
    # ' ' < 'T', so every run sorts after every commit and the repair count comes out 0 for the
    # whole class — a real signal, silently zeroed. (Measured 2026-08-02.)
    rows = sorted([(_parse_dt(str(r["dt"])), r) for r in (insp or {}).get("commits") or []
                   if r.get("dt") and _parse_dt(str(r["dt"]))], key=lambda p: p[0])
    runs = sorted([(_parse_dt(r["created_at"]), r) for r in (run_history or [])
                   if r.get("created_at") and r.get("conclusion") and _parse_dt(r["created_at"])],
                  key=lambda p: p[0])
    if not rows or not runs:
        return 0
    # PREREQUISITE: something must have been REVISED. "The autograder was red" does not by
    # itself mean debugging — an incomplete program is red on every push too, so a student
    # assembling one line at a time would score every commit as a repair. Repairing means
    # taking something back; a history that never deletes a single line never took anything
    # back. (Measured: a 12-commit, 0-deletion history was promoted to the top row by the
    # red-run signal alone until this was added.)
    # …but taking something back is not the ONLY way to repair. A statement inserted into a
    # block that already existed edits earlier work just as much as a deleted line does, and
    # that is how a missing `count++` / `prev = current` gets fixed. Either proof will do.
    if not (any((r.get("deletions") or 0) > 0 for _, r in rows)
            or any(r.get("interior_insert") for _, r in rows)):
        return 0
    n = 0
    for when, _r in rows:
        prior = [run for t, run in runs if t < when]
        if prior and prior[-1]["conclusion"] == "failure":
            n += 1
    return n


def _trim_to_pass(insp, pass_commit):
    """Drop every commit that landed AFTER the one that turned the autograder green.

    Grading measures the work that PRODUCED the passing program. What comes after it did not
    contribute to that program, and counting it is not neutral — it inflates the very axes the
    grid rewards: three tidy-up commits pushed after the green run add three effective cycles
    and can lift a narrow history into the `wide` column. A student who cleans up afterwards
    and one who does not would then be graded differently for identical debugging work.

    Suffix-only trim, so each retained commit keeps the `gap_min` it already had (its
    predecessor is untouched). If the passing commit cannot be located among the rows, NOTHING
    is trimmed and `trimmed` comes back False — an unlocatable boundary must not silently
    delete evidence (§4b.1: surface the gap, do not invent one).
    """
    rows = list((insp or {}).get("commits") or [])
    sha = (pass_commit or {}).get("sha")
    idx = next((i for i, r in enumerate(sorted(
        [r for r in rows if r.get("dt")], key=lambda r: _parse_dt(str(r["dt"])) or _EPOCH))
        if r.get("sha") and sha and str(r["sha"]).startswith(str(sha)[:7])), None)
    if idx is None:
        return insp, 0, False
    dated = sorted([r for r in rows if r.get("dt")],
                   key=lambda r: _parse_dt(str(r["dt"])) or _EPOCH)
    kept_dated = dated[:idx + 1]
    kept = [r for r in rows if r in kept_dated] or kept_dated
    n_dropped = len(rows) - len(kept)
    if not n_dropped:
        return insp, 0, True

    contents = [r.get("content") for r in kept if r.get("content")]
    cycles = sum(1 for r in kept_dated
                 if r.get("gap_min") is not None and r["gap_min"] >= GAP_COUNTABLE
                 and r.get("content") not in ("empty",))
    out = dict(insp)
    out.update({
        "n": len(kept),
        "n_logic_fix": contents.count("logic_fix"),
        "n_syntax_fix": contents.count("syntax_fix"),
        "n_assembly": contents.count("assembly"),
        "n_rewrite_diff": contents.count("rewrite"),
        "n_empty_commits": contents.count("empty"),
        "has_content": bool(contents),
        "gaps_min": [r.get("gap_min") for r in kept_dated if r.get("gap_min") is not None],
        "effective_cycles": cycles,
        "wide": (cycles >= CYCLES_WIDE) if contents else None,
        "commits": kept,
    })
    return out, n_dropped, True


def commit_quality(insp, pass_commit=None, difficulty=None, run_history=None):
    """Combine COUNT x TIME x CONTENT into one tier (GRADING §4F.6). ADVISORY ONLY.

    Returns a tier + the reasons behind it; it does NOT set the score. Stage B decides and may
    depart from it, which `report_generator` then records as `commit_vs_engine` — the engine
    surfaces, the human judges (§4F.5.1, which deliberately removed the engine's auto-zero).

    Why a tier and not a number: the shapes this catches have honest counter-examples. A
    student who debugs locally and pushes in one burst looks identical to a copier here, and
    only the write-up can separate them. So the grid is the default, and departing from it
    costs a written reason rather than being impossible.

    `difficulty`: 'trivial' waives the grid entirely (§4.8 — a <10-line assignment does not
    require a debugging cycle and must not be docked for lacking one), 'normal' floors at
    5/8, 'advanced' allows the full range. UNKNOWN difficulty => no floor is invented and the
    result is marked `needs_difficulty` for the instructor (the §4b.1 rule: never fabricate a
    threshold; surface that it is missing).
    """
    insp = insp or {}
    pc = pass_commit or {}
    if not insp.get("has_content"):
        return {"tier": None, "reasons": ["no commit diffs supplied — content axis unavailable"],
                "needs_difficulty": False}

    # SCOPE: only the commits that built the passing program are graded (see _trim_to_pass).
    insp, n_after_pass, trim_ok = _trim_to_pass(insp, pc)
    n_logic, n_syntax = insp.get("n_logic_fix", 0), insp.get("n_syntax_fix", 0)
    cycles, wide = insp.get("effective_cycles", 0), bool(insp.get("wide"))
    n_total = insp.get("n", 0)
    n_repair = _repairs_after_failure(insp, run_history)
    row = ("logic" if (n_logic >= 1 or n_repair >= 1)
           else ("syntax" if n_syntax >= 1 else "assembly"))
    frac = _TIER_GRID[(row, wide)]

    # DEFENSIBLE FACTS, not a verdict. Any commit deduction must survive the student's reply,
    # so every line below is one of the FIVE things §4F.3.1 requires: their own commit count
    # and shape, one of their own messages quoted, the real timing, what a correct history for
    # THIS task would have looked like, and the passing commit said out loud. None of it is an
    # accusation — a student who genuinely wrote it right the first time is described exactly
    # as accurately as one who pasted it, and the difference is stated as a requirement.
    rows_dt = [r for r in (insp.get("commits") or []) if r.get("dt")]
    rows_dt.sort(key=lambda r: r["dt"])
    burst = [r for r in rows_dt if r.get("gap_min") is not None and r["gap_min"] < GAP_COUNTABLE]
    gaps = [g for g in (insp.get("gaps_min") or []) if g is not None]
    quoted = next((r.get("message") for r in rows_dt if r.get("message")), "")
    reasons = [
        f"your history, by the SHAPE of each diff: {n_total} commit(s) — {n_logic} that rewrote "
        f"an existing line, {n_syntax} that fixed only punctuation/import, "
        f"{insp.get('n_assembly', 0)} that only added new lines, "
        f"{insp.get('n_empty_commits', 0)} that changed nothing."
    ]
    if n_after_pass:
        reasons.append(
            f"({n_after_pass} further commit(s) came AFTER the autograder was already green and "
            f"are not counted either way — this item measures the work that produced the passing "
            f"program, so tidying up afterwards neither helps nor hurts.)")
    if quoted:
        reasons.append(f'e.g. your commit "{quoted}".')
    if gaps:
        reasons.append(
            f"timing: gaps between commits ran {min(gaps):.1f}–{max(gaps):.1f} min"
            + (f"; {len(burst)} commit(s) landed under {GAP_COUNTABLE:.0f} min after the previous "
               f"one, which is less time than compiling and reading the output takes, so those "
               f"are not separate attempts. {cycles} of {n_total} count as distinct work."
               if burst else f"; {cycles} of {n_total} are distinct pieces of work."))
    if row == "logic":
        how = (f"{n_logic} commit(s) change an operator, a bound or an index"
               if n_logic else "")
        if n_repair:
            how = ((how + " and ") if how else "") + (
                f"{n_repair} commit(s) landed while the autograder was already failing")
        reasons.append(f"CREDITED: {how} — the code visibly failed and you repaired it. That is "
                       "what this row rewards, and it counts even when the edit is one "
                       "character or a single added line.")
        if not n_logic and n_repair:
            # Without this the same comment reads as a contradiction — the shape line says
            # "only added new lines" and the credit line says "you repaired it". Both are true
            # and they are measured on different axes; say which, or the student writes in.
            reasons.append("(Those two lines do not disagree: the shape count above is the diff "
                           "alone, and a logic bug fixed by ADDING the missing statement looks "
                           "like new code there. The server run is what shows the program was "
                           "broken at that moment, and you get the credit for it.)")
    elif row == "syntax":
        reasons.append("For full marks: every repair in this history is punctuation, a brace or "
                       "an import — the compiler complained, but the ALGORITHM is never seen "
                       "failing. Commit once while the logic is still wrong, then commit the fix.")
    else:
        reasons.append("For full marks: every commit adds new lines and none repairs an earlier "
                       "one, so the history shows the program being assembled rather than "
                       "debugged. If you truly hit no errors, say so in the write-up and show "
                       "the runs you used to check it (§4.3) — an unexplained clean build cannot "
                       "be told apart from code written elsewhere.")

    if pc.get("verdict") in ("oneshot_bulk", "oneshot_trivial"):
        frac = min(frac, 0.50)
        reasons.append(f"the passing commit {pc.get('sha','')} \"{pc.get('message','')}\" "
                       f"(+{pc.get('additions')}/-{pc.get('deletions')}): {pc.get('note', '')}")
    elif pc.get("sha"):
        reasons.append(f"passing commit {pc['sha']} \"{pc.get('message','')}\" "
                       f"(+{pc.get('additions')}/-{pc.get('deletions')}, {pc.get('content')}) "
                       f"after {pc.get('prior_failing_runs')} failing run(s).")

    floor_known = difficulty in _DIFFICULTY_FLOOR
    if difficulty == "trivial":
        return {"tier": 1.00, "row": row, "wide": wide, "effective_cycles": cycles,
                "waived": True, "needs_difficulty": False,
                "reasons": ["§4.8 carve-out: assignment marked trivial — commit history graded "
                            "softly, a clean single-pass history is acceptable"],
                "params": {"GAP_COUNTABLE": GAP_COUNTABLE, "CYCLES_WIDE": CYCLES_WIDE,
                           "SIM_THRESHOLD": SIM_THRESHOLD, "difficulty": difficulty}}
    if floor_known and _DIFFICULTY_FLOOR[difficulty] is not None:
        floored = max(frac, _DIFFICULTY_FLOOR[difficulty])
        if floored != frac:
            # PLAIN ENGLISH — this line goes into the STUDENT's comment. It used to read
            # "floored at 0.625 by difficulty='normal'", which tells a student nothing and
            # invites a reply asking what 0.625 means. The content is in their FAVOUR (the
            # score was held up, not pushed down), so it must read that way.
            # No arithmetic on the item max — commit_quality works in fractions and does not
            # know the rubric's point value, so naming a number here would be a guess.
            reasons.append(
                "(The deduction on this item was limited: this assignment is not one where a "
                "long debugging history is expected, so the lowest bands are held back for "
                "harder work and your score was raised to the minimum for this one.)")
        frac = floored
    elif not floor_known:
        reasons.append("⚠ NO `commit_difficulty` for this assignment — no floor applied and no "
                       "threshold invented; confirm whether §4.4/§4.8 carve-outs apply")

    # Any score below full is a DEDUCTION, and §4.5.3 requires WHAT + EVIDENCE + HOW TO FIX on
    # every one of them — `comment_render` refuses to render otherwise. The row-specific lines
    # above carry a fix for the syntax/assembly rows, but a `logic` row can still land below
    # full via the passing-commit override or a narrow window, and those paths had none. Rather
    # than let the render fail (or, worse, let a fix-less deduction through), close it here.
    if frac < 1.0 and not any("full marks" in r.lower() for r in reasons):
        if not wide:
            reasons.append(
                f"For full marks: commit while the work is happening. Only {cycles} of "
                f"{n_total} commits are more than {GAP_COUNTABLE:.0f} minute apart, so the "
                f"history reads as one sitting rather than a sequence of attempts — commit "
                f"each time you run it and learn something, not at the end.")
        else:
            reasons.append(
                "For full marks: the commit that turned it green has to be a repair of code "
                "that had visibly failed. Push the broken state first, then the fix, so the "
                "history shows the problem as well as the answer.")

    return {"tier": frac, "row": row, "wide": wide, "effective_cycles": cycles,
            "n_repair_after_failure": n_repair,
            "n_excluded_after_pass": n_after_pass, "pass_boundary_found": trim_ok,
            "waived": False, "needs_difficulty": not floor_known, "reasons": reasons,
            # THE SLOT ONLY A READER CAN FILL (GRADING §4F.6). The engine sees the commits;
            # it cannot see whether the write-up's account of debugging is TRUE. The ambiguous
            # case is real and common: commits look like plain assembly, yet the elaboration
            # describes real errors. That is neither full marks nor the assembly floor —
            # a student who debugged locally deserves credit, and a student who only WROTE
            # about debugging must not get the same as one whose history proves it.
            #   corroborated — the errors described are visible in the commits => full marks
            #                  allowed. Nothing beats this: the two records agree.
            #   claimed_only — described but not visible. −1 when the write-up quotes something
            #                  only a real run produces (exception text, the actual wrong
            #                  output); −2 when it is general debugging talk. The comment
            #                  ADVISES rather than accuses: commit the broken state, then the
            #                  fix, and the two records will agree.
            #   absent       — no error account at all => the engine tier stands.
            # Stage B writes `elab_commit_match` into the authoring; the render refuses without it.
            "match_slot": None,
            "params": {"GAP_COUNTABLE": GAP_COUNTABLE, "CYCLES_WIDE": CYCLES_WIDE,
                       "SIM_THRESHOLD": SIM_THRESHOLD, "difficulty": difficulty}}


def _min_between(a_iso, b_iso):
    """Minutes from a_iso to b_iso (server ISO-8601), or None if either is missing/bad."""
    a, b = _parse_dt(a_iso), _parse_dt(b_iso)
    if not a or not b:
        return None
    return round((b - a).total_seconds() / 60.0, 1)


def authenticity(insp, repo_created_at=None, graded_run_created_at=None,
                 first_run_created_at=None, instant_minutes=10.0):
    """SERVER-TIME authenticity of a git-coding submission — the online-exam PROCTOR.

    This course is FULLY ONLINE and its exams are online, so the commit history IS the
    proctoring / anti-plagiarism signal: a genuine solve of a small test-and-fix task
    leaves several commits spread across the working window. Two shapes are NOT accepted
    for full commit credit and are always flagged for the instructor:
      - a single / all-at-once commit (no visible process to proctor), and
      - a passing autograder run that appears within minutes of the repo being created.

    Trusted clock = SERVER timestamps ONLY: repo `created_at` and the graded run's
    `created_at`. Commit author/committer dates are client-set and forgeable, so they are
    used solely to DETECT backdating (claimed author span >> the real server window),
    never as the clock.

    `instant_minutes` (default 10) is a HEURISTIC window, not a hard gate — difficulty and
    size vary by assignment, so the engine only SURFACES the signal; Stage B / the
    instructor decides the score. INSTRUCTOR-ONLY: the verdict/flags are never shown to the
    student verbatim (a student comment states the process requirement, not the suspicion).

    Returns dict:
      repo_to_pass_min : server minutes repo-created -> graded run (None if unknown)
      single           : bool — one commit, or an all-at-once first-bulk with <=2 commits
      backdated        : bool — author span >> server window (commit dates look padded)
      verdict          : clean | single-all-at-once | instant | no-commits-in-window | backdated
      accepted         : bool — False whenever the history is not proctorable (single/instant)
      flags            : list[str] — human, instructor-facing
    """
    insp = insp or {}
    n = insp.get("n", 0)
    n_debug = insp.get("n_debug", 0)
    author_span = insp.get("span_minutes")
    first_is_bulk = insp.get("first_is_bulk", False)
    compressed = insp.get("compressed", False)
    has_runtime_err = insp.get("has_runtime_err", None)

    repo_to_pass = _min_between(repo_created_at, graded_run_created_at)
    single = (n <= 1) or (first_is_bulk and n <= 2)
    # Backdating: the commit author dates claim a much longer span than the repo actually
    # existed on the server before it passed (server window can't be shorter than a real solve).
    backdated = bool(author_span is not None and repo_to_pass is not None
                     and author_span > (repo_to_pass * 3 + 15))

    flags = []
    verdict = "clean"
    accepted = True

    if single:
        accepted = False
        if repo_to_pass is not None and repo_to_pass < instant_minutes:
            verdict = "instant"
            flags.append(
                f"INSTANT: repo->passing-run = {repo_to_pass} min with a single/all-at-once "
                f"commit (< {instant_minutes} min) — no iterative process; paste / pre-written "
                f"suspect. Not proctorable.")
        else:
            verdict = "no-commits-in-window"
            gap = f"{repo_to_pass} min" if repo_to_pass is not None else "the working window"
            flags.append(
                f"SINGLE COMMIT: only one all-at-once commit over {gap} — the process is not "
                f"visible in git (likely worked locally without committing). Online-exam policy: "
                f"the commit history is the proctor; a single commit is not accepted for full "
                f"commit credit even if the tests pass.")
    elif repo_to_pass is not None and repo_to_pass < instant_minutes and n_debug <= 1:
        verdict = "instant"
        accepted = False
        flags.append(
            f"INSTANT: repo->passing-run = {repo_to_pass} min with little error-fix history "
            f"(n_debug={n_debug}) — faster than a real iterative solve. Not proctorable.")
    elif compressed:
        flags.append(
            f"COMPRESSED: {n} commits within {author_span} min — thin debugging window; verify "
            f"against server time (repo->pass = "
            f"{repo_to_pass if repo_to_pass is not None else '?'} min).")

    if backdated:
        # Backdating is a hard integrity signal regardless of count.
        verdict = "backdated" if verdict == "clean" else verdict
        accepted = False
        flags.append(
            f"BACKDATED?: commit author span {author_span} min >> server window "
            f"{repo_to_pass} min (repo-created -> passing run) — commit dates look padded; "
            f"trust server time, not the commit timeline.")

    # QUALITY (§4F.6): a multi-commit history with NO runtime-error signal in any message
    # (a clean forward build / syntax-only fixes) cannot earn full commit marks on an advanced
    # task. Message-based ⇒ a FLAG for Stage B (not an auto-reject like the server-time verdicts).
    no_runtime_errors = has_runtime_err is False and n >= 2
    if no_runtime_errors:
        flags.append(
            f"NO RUNTIME-ERROR FIX IN COMMIT MESSAGES: {n} commits, none whose MESSAGE names a "
            f"runtime/logic/test error. This is a message-text signal, NOT proof that no error was "
            f"hit — a student who fixes an error and writes 'done' looks identical. Before docking "
            f"(§4F.6), CHECK `review_content.run_history`: a student-authored `failure` run is "
            f"server-side proof of a real error→fix cycle. Advanced tasks only; the beginner "
            f"carve-outs (GRADING §4.4 chapters 2-3, §4.8 <10-line trivial) override this. "
            f"Stage B decides — the engine only surfaces it.")

    return {
        "repo_to_pass_min": repo_to_pass,
        "single": single,
        "backdated": backdated,
        "no_runtime_errors": no_runtime_errors,
        "verdict": verdict,
        "accepted": accepted,
        "flags": flags,
    }
