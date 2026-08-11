"""GitHub-based grader (A/L/W with autograder, any language: Python/C++/ASM).

Repo lookup is NOT done here. Caller (core.py) resolves `repo` via the roster
CSV bridge and passes it in. If repo is None → engine treats as Section 0 case.
"""
import re
import os
import json
import zipfile
import datetime

from ..lib import attachments as att_mod
from ..lib import github as gh
from ..lib import commit_inspect


# ============================================================================
# CONSTANTS — all tunable magic numbers live here; edit in one place.
# Test/commit scoring is proportional to autograder max + rubric max.
# Elaboration thresholds are character counts (text-length nature).
# ============================================================================

# What this grader emits on EVERY normal grade (lib/contract.py). Declared, not inferred.
# `authenticity` and `oversized_log` are deliberately NOT here: both are exceptional (a repo
# that resolved / a log that was too big), so declaring them flagged all 15 A511 students for
# a correctly-empty field — noise that buries a real miss.
# `needs_review` is absent for a different reason, a genuine gap: this grader returns the RAW
# signals (`ag_penalty`, `commit_flags`, `recommit_after_pass`, `authenticity`) and quiz.py is
# what turns them into instructor-facing lines. On the ASSIGNMENT path nothing does, so those
# signals never reach report Section 0. Recorded here rather than papered over.
PRODUCES = frozenset({"review_content", "rubric_items"})

# Default rubric ratios (sum must be 1.0 — elab takes whatever remains)
RUBRIC_RATIO_TEST = 0.5
RUBRIC_RATIO_COMMIT = 0.2
# RUBRIC_RATIO_ELAB = 1 - test - commit (computed)

# Commit-history quality fractions (proportion of commit_max)
COMMIT_FRAC_ZERO = 0.0                 # 0 student commits
COMMIT_FRAC_ONE = 2.0 / 3.0            # 1 commit (no debug history)
COMMIT_FRAC_THIN = 5.0 / 6.0           # 2 commits OR compressed in time
COMMIT_FRAC_HEALTHY = 1.0              # 3+ spread-out commits

# Elaboration length thresholds (chars)
ELAB_EMPTY_CHARS = 10                  # below → 0
ELAB_SHORT_CHARS = 30                  # below on 2-pt → 0
ELAB_MEDIUM_CHARS = 50                 # below on 3-pt → 1
ELAB_LONG_CHARS = 100                  # 2-pt: above → 1 or 2
ELAB_FULL_CHARS = 200                  # 3-pt: above → 2 or 3
ELAB_MIN_FOR_1PT = 20                  # 1-pt rubric threshold

# Score snap grid (final scores rounded to nearest)
SCORE_SNAP = 0.25

# Minimum-credit floor for any non-empty submission (per GRADING.md §3b)
MINIMUM_SCORE_RATIO = 0.10

# Run-log MONITOR threshold — UNCOMPRESSED bytes (repetitive floods compress tiny, so
# measure unzipped, not the zip). Over this, the report raises a LOUD top alert so we
# gather real size data — but grading PROCEEDS; it is NOT a block. The hard download
# ceiling (500 MB zip) lives in github_access.actions.LOG_HARD_CAP_BYTES.
LOG_ALERT_BYTES = 5 * 1024 * 1024  # 5 MB


def _snap(value, grid=SCORE_SNAP):
    """Snap a score to a clean grid (default 0.25)."""
    return round(value / grid) * grid


def _parse_iso(s):
    """ISO-8601 UTC ('...Z') → datetime; None on failure."""
    if not s:
        return None
    try:
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


# Due-date penalty — AUTOGRADER item ONLY (GRADING.md Part B §2). Anchor = the graded
# (passing) run's SERVER created_at vs due_at (author/commit dates are forgeable, never
# used). Homework and quiz use different HOURS tiers. A late SUBMISSION whole-score
# penalty is separate (Canvas). Per-course WAIVERS are separate. For quizzes there is
# ALSO a timeout penalty (_timeout_penalty), applied STACKED with this one.
def _due_penalty(completion_at, due_at, is_quiz):
    c = _parse_iso(completion_at)
    d = _parse_iso(due_at)
    if not c or not d or c <= d:
        return 0.0
    h = (c - d).total_seconds() / 3600.0
    if is_quiz:                          # quiz / exam — no grace
        if h < 1:   return 0.10          # < 1h   10%
        if h < 2:   return 0.20          # < 2h   20%
        if h < 3:   return 0.30          # < 3h   30%
        if h < 6:   return 0.50          # < 6h   50%
        return 0.90                      # else   90%
    if h < 1:   return 0.0               # homework — 1h grace
    if h < 6:   return 0.10              # < 6h   10%
    if h < 12:  return 0.20             # < 12h  20%
    if h < 24:  return 0.30             # < 24h  30%
    return 0.50                          # else   50%


# Quiz/exam TIMEOUT penalty — AUTOGRADER item ONLY. An exam has a time limit; the window
# from repo creation (git-init, SERVER time) to the passing run must fit within it.
# Overage past the timeout is penalised on the same HOURS tiers, STACKED with _due_penalty.
# Homework has no timeout (timeout_min falsy → 0.0).
def _timeout_penalty(repo_created_at, completion_at, timeout_min):
    if not timeout_min or timeout_min <= 0:
        return 0.0
    r = _parse_iso(repo_created_at)
    c = _parse_iso(completion_at)
    if not r or not c:
        return 0.0
    over_h = ((c - r).total_seconds() - timeout_min * 60.0) / 3600.0
    if over_h <= 0:
        return 0.0
    if over_h < 1:   return 0.10
    if over_h < 2:   return 0.20
    if over_h < 3:   return 0.30
    if over_h < 6:   return 0.50
    return 0.90


def default_rubric(points_possible):
    """Scale the default ratios to whatever points_possible is.
    Items: test, commit, elab. Elab = remainder so the sum equals points_possible.
    """
    if points_possible <= 0:
        return {"test": 0, "commit": 0, "elab": 0}
    test = round(points_possible * RUBRIC_RATIO_TEST)
    commit = round(points_possible * RUBRIC_RATIO_COMMIT)
    elab = points_possible - test - commit
    return {"test": test, "commit": commit, "elab": elab}


def _score_test(tp, mp, max_pts):
    """Score the autograder test proportionally.

    pct = tp / mp (autograder fraction passed, regardless of mp's actual value)
    score = max_pts * pct  (then snapped to SCORE_SNAP grid)

    No hardcoded cutoffs. Works for any autograder max (60, 100, 120, etc).
    """
    if tp is None or mp is None or mp <= 0 or max_pts <= 0:
        return 0
    if tp == 0:
        return 0
    pct = tp / mp
    return _snap(max_pts * pct)


_MANIFEST_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "manifests")


def _manifest_difficulty(code):
    """`commit_difficulty` for this assignment, from `manifests/<code>.json`.

    Authored per assignment and read every run, so the §4.4/§4.8 carve-out survives a re-grade
    in a later session — a value passed on the command line would not, and a rule that has to be
    remembered is a rule that gets dropped. Absent is fine and is NOT a default: `commit_quality`
    then computes the tier with no floor and marks `needs_difficulty` (§4b.1 — surface the missing
    threshold, never invent one).
    """
    try:
        with open(os.path.join(_MANIFEST_DIR, f"{code}.json")) as f:
            return (json.load(f) or {}).get("commit_difficulty")
    except Exception:  # noqa: BLE001 — no manifest is fine
        return None


def _score_commits(insp, max_pts, quality=None):
    """Score commit history from a commit_inspect.inspect() result.

    PREFERS the commit-quality tier (content x time-filtered count x the passing commit,
    GRADING §4F.6) when the patch text was available. Falls back to the count-only ladder
    when it was not — that fallback is what this function used to be, and on its own it
    could return only two values for a whole class, because it can see neither WHAT a commit
    changed nor that twelve commits one minute apart are one cycle's worth of evidence.

    Still ADVISORY: Stage B sets the final score and `report_generator` records any departure
    as `commit_vs_engine` (§4F.5.1 — the engine surfaces, the human decides).
    """
    if max_pts <= 0:
        return 0
    tier = (quality or {}).get("tier")
    if tier is not None:
        return _snap(max_pts * tier)
    n = (insp or {}).get("n", 0)
    if n == 0:
        frac = COMMIT_FRAC_ZERO
    elif n == 1:
        frac = COMMIT_FRAC_ONE
    elif n == 2 or (insp or {}).get("compressed"):
        frac = COMMIT_FRAC_THIN
    else:
        frac = COMMIT_FRAC_HEALTHY
    return _snap(max_pts * frac)


def _engine_notes(repo, tp, ag_penalty, due_frac, timeout_frac, rdata,
                  recommit_after_pass, asmt):
    """Instructor-facing lines for report Section 0 — things the ENGINE did or noticed that
    are NOT the student's fault and must not be read as a judgement.

    Owned by this grader because this grader owns the signals. Until 2026-07-28 quiz.py
    composed these from the raw return fields, so they appeared on quizzes and were missing
    entirely from assignments — the same repo, the same late autograder run, reported in one
    context and silent in the other.

    Returns [] when nothing is off; the field is exceptional by nature, which is why it is
    NOT in PRODUCES (a declared-always field that is usually empty flags every clean student).
    """
    notes = []
    if not repo:
        # NO REPO AT ALL — distinct from a repo whose autograder never ran, and the two must
        # not share wording: "repo None has no autograder run on record" reads as a grading
        # result when it is really an unresolved link (student pasted none / the org-hub bot
        # failed to issue one). Section 0 is where the instructor decides which it was.
        notes.append("no repo resolved for this submission — nothing to run the autograder on "
                     "(check the submitted link and the org-hub issue log)")
    elif tp is None:
        notes.append(f"repo {repo} has no autograder run on record")
    if ag_penalty:
        notes.append(
            f"autograder TIME penalty −{int(ag_penalty * 100)}% ALREADY APPLIED "
            f"(due −{int((due_frac or 0) * 100)}%, timeout −{int((timeout_frac or 0) * 100)}%; "
            f"pass={rdata.get('run_created_at')}, repo={rdata.get('repo_created_at')}, "
            f"due={asmt.get('due_at')}, limit={asmt.get('time_limit')}min)")
    if recommit_after_pass:
        notes.append(
            f"{len(recommit_after_pass)} run(s) AFTER first pass — possible re-commit of "
            f"already-passed code (Stage B judge): "
            f"{[x.get('created_at') for x in recommit_after_pass]}")
    notes.extend(rdata.get("commit_flags") or [])
    return notes


def _score_elab(text, max_pts):
    if not text or len(text.strip()) < ELAB_EMPTY_CHARS or max_pts <= 0:
        return 0
    L = len(text)
    t = text.lower()
    has_var = bool(re.search(r"variable|input|output|param", t))
    has_alg = bool(re.search(r"algorithm|loop|condition|step|approach|how", t))
    has_err = bool(re.search(r"error|fix|debug|bug|mistake|lesson|learned", t))
    sig = sum([has_var, has_alg, has_err])
    if max_pts == 3:
        if L < ELAB_MEDIUM_CHARS: return 1
        if L < ELAB_FULL_CHARS: return 2 if sig else 1
        return min(3, max(2, sig))
    if max_pts == 2:
        if L < ELAB_SHORT_CHARS: return 0
        if L < ELAB_LONG_CHARS: return 1
        return 2 if sig else 1
    if max_pts == 1:
        return 1 if L >= ELAB_MIN_FOR_1PT else 0
    return min(max_pts, max(1, sig))


def _fetch_repo_data(token, repo, cache_dir, student_login=None, as_of=None,
                     instructor_logins=None, difficulty=None):
    """Fetch autograder result + commit history for a repo.

    as_of — ISO-8601 UTC timestamp (e.g. "2026-05-04T08:36:03Z") for COMMIT-TIME
    grading (GRADING.md Part B §2 / Part D §2): score the repo AS IT STOOD at that
    moment. The autograder result = the LAST push run created at or before `as_of`
    (none before then → tp=None → 0, i.e. no passing code yet at that time); commit
    history is likewise limited to commits authored at or before `as_of`. When
    as_of is None → latest run / all commits (default single-submission behavior)."""
    if not repo:
        return {}
    # Repo metadata for SERVER-TIME authenticity (commit_inspect.authenticity): the repo
    # `created_at` is the trusted clock start; `pushed_at` = last server push. Commit dates
    # are client-set/forgeable, so this server anchor is what the online-exam proctor check
    # (repo-created -> passing run) runs on. One extra un-paginated GET.
    repo_meta = gh.get(token, f"/repos/{repo}", paginate=False) or {}
    repo_created_at = repo_meta.get("created_at")
    repo_pushed_at = repo_meta.get("pushed_at")
    runs = gh.list_runs(token, repo)
    runs_list = (runs or {}).get("workflow_runs", [])      # newest-first
    push_runs = [r for r in runs_list if r.get("event") == "push"]
    first_run_created_at = push_runs[-1].get("created_at") if push_runs else None
    if as_of is not None:
        eligible = [r for r in push_runs if (r.get("created_at") or "") <= as_of]
        chosen = eligible[0] if eligible else None         # newest push run at/before as_of
    else:
        chosen = (push_runs[0] if push_runs else (runs_list[0] if runs_list else None))
    tp, mp = None, None
    oversized_log = None
    if chosen:
        log_path = f"{cache_dir}/runlog_{repo.replace('/','_')}_{chosen['id']}.zip"
        gh.get_run_log(token, repo, chosen["id"], log_path)
        tp, mp = gh.parse_total_points_from_log_zip(log_path)
        # MONITOR (not a block): measure UNCOMPRESSED log size; flag if over threshold.
        try:
            if os.path.exists(log_path):
                zbytes = os.path.getsize(log_path)
                with zipfile.ZipFile(log_path) as zf:
                    ubytes = sum(i.file_size for i in zf.infolist())
                if ubytes > LOG_ALERT_BYTES:
                    oversized_log = {"uncompressed_mb": round(ubytes / 1048576, 1),
                                     "zip_kb": round(zbytes / 1024, 1)}
        except Exception:  # noqa: BLE001
            pass
    commits = gh.list_commits(token, repo) or []
    student, commit_flags = gh.filter_student_commits(
        commits, repo=repo, student_login=student_login, instructor_logins=instructor_logins)
    if as_of is not None:
        student = [c for c in student
                   if (((c.get("commit") or {}).get("author") or {}).get("date") or "") <= as_of]
    detailed = []
    commit_diffs = []   # actual per-commit patch CONTENT for the Stage-B substance read (§4F.6)
    for c in student:
        sha = c.get("sha")
        det = gh.get_commit(token, repo, sha) if sha else None
        stats = (det or {}).get("stats") or {}
        msg = (c.get("commit") or {}).get("message") or ""
        detailed.append({
            "date": ((c.get("commit") or {}).get("author") or {}).get("date"),
            "message": msg,
            "additions": stats.get("additions"),
            "deletions": stats.get("deletions"),
        })
        # Text patches only — GitHub omits `patch` for binary/oversized files, so this stays small
        # for a coding assignment. This is the DIFF the AI must READ to judge substance (semicolon
        # fix vs a real error fix) — Stage-A gathers it; Stage-B judges it.
        patches = [{"filename": f.get("filename"), "patch": f.get("patch")}
                   for f in ((det or {}).get("files") or []) if f.get("patch")]
        commit_diffs.append({"sha": (sha or "")[:7],
                             "message": msg.splitlines()[0][:100] if msg else "",
                             "patches": patches})
    # Pass the patch text: `inspect` then classifies each commit by WHAT it changed (semicolon
    # vs a fixed loop bound) and computes time-filtered `effective_cycles` — the two axes the
    # count-only score could not see (GRADING §4F.6).
    insp = commit_inspect.inspect(detailed, commit_diffs)
    # SERVER-TIME authenticity (online-exam proctor): repo-created -> the graded run's
    # created_at, plus single/all-at-once and backdating signals. Instructor-only surfacing.
    auth = commit_inspect.authenticity(
        insp, repo_created_at=repo_created_at,
        graded_run_created_at=(chosen or {}).get("created_at"),
        first_run_created_at=first_run_created_at)
    # PUSH-RUN HISTORY (oldest→newest) — ZERO extra API calls: `push_runs` is already
    # fetched above to pick the graded run. A FAILING run authored by the student is
    # POSITIVE, server-side proof of a real error→fix cycle (stronger than commit-message
    # regex). Its ABSENCE proves nothing: a run only exists per PUSH, so a student who
    # debugs locally and pushes once leaves no failing run. Read it as a one-way signal.
    # `head_sha` ties each run to the COMMIT that produced it — that is what makes the
    # passing commit identifiable (§4F.6.4). Without it the history says "it went green"
    # but not "green on WHAT change".
    run_history = [{"created_at": r.get("created_at"),
                    "conclusion": r.get("conclusion"),
                    "head_sha": r.get("head_sha"),
                    "actor": ((r.get("actor") or {}).get("login"))}
                   for r in reversed(push_runs)]
    # THE PASSING COMMIT: did the algorithm ever fail before it passed? (bulk-arrives-and-
    # passes, or a one-line flip on already-correct code = no visible error→fix cycle).
    pass_commit = commit_inspect.pass_commit_analysis(commit_diffs, run_history, insp)
    # COMMIT-QUALITY TIER (advisory). Combines content x time-filtered count x the passing
    # commit, and applies the §4.4/§4.8 carve-out through `commit_difficulty`. It does NOT set
    # the score: Stage B decides and any departure is recorded as `commit_vs_engine`.
    cquality = commit_inspect.commit_quality(insp, pass_commit, difficulty, run_history)
    return {
        "repo": repo,
        "tp": tp, "mp": mp,
        "commit_count": insp["n"],
        "commit_inspect": insp,
        "commit_flags": commit_flags,
        "run_id": (chosen or {}).get("id"),
        "run_created_at": (chosen or {}).get("created_at"),
        "run_history": run_history,
        "pass_commit": pass_commit,
        "commit_quality": cquality,
        "repo_created_at": repo_created_at,
        "repo_pushed_at": repo_pushed_at,
        "authenticity": auth,
        "commit_diffs": commit_diffs,
        "oversized_log": oversized_log,
    }


# `_dedu_test` / `_dedu_commits` / `_dedu_not_accepted` / `_dedu_elab` lived here until
# 2026-08-04. Each produced the `{why, how_to_fix}` dict that was the 4th element of
# `rubric_rows` — student-facing deduction text generated OUTSIDE `comment_render`, and read
# by nothing (both consumers destructure with `*_`). Removed with that element; the full
# reason is on `rubric_rows` below.
def _decide_as_of(submitted_at, due_at):
    """Which point in time to read the autograder result for a SINGLE submission:
      - on-time (submitted ≤ due) → None = the LATEST run. The student's eventual
        passing work is credited; lateness is handled by the commit-late TEST tier
        (_commit_late_frac), NOT by cutting the result off at due.
      - late (submitted > due)    → the SUBMISSION time (their state when they
        submitted; the whole-score Canvas penalty applies on top, in core.py).
      - missing due/submitted     → None (latest; legacy).
    Quizzes do NOT use this — each attempt passes as_of = its OWN submission time."""
    if not due_at or not submitted_at:
        return None
    return None if submitted_at <= due_at else submitted_at


def prepare(*, submissions, course, code, canvas, base_url, canvas_token, course_id, **kwargs):
    """CLASS-WIDE pre-pass (2026-07-28). Resolve EVERY student's repo in one shot, before
    any single submission is graded. Moved verbatim out of core.py, which had it inline
    behind `if grader_name == "gh"` — a grader type named inside the orchestrator.

    Why this is a separate entry point and NOT part of grade():
      · it is BATCH — one org-hub log listing + one roster fetch serve the whole class
        (per-student it re-fetched the log once per student: "17× on A21");
      · its output is not just a repo. `flags` (link≠log) and `unmapped` (no repo at all)
        drive Section 0 and decide who is SKIPPED before grading. That is eligibility,
        not scoring, so it cannot live in a per-submission scorer.

    So gh is 2-tier: prepare() = class-wide, grade() = one submission. Any other grader
    that needs a class-wide pre-pass adds its own prepare(); core.py just calls it when
    present and stays type-agnostic.

    Returns {"repo_by_uid": {uid: repo}, "source_by_uid": {uid: src}, "flags": [...],
             "unmapped": [...], "gh_token": str|None}
    """
    from ..lib import github as gh_lib
    from ..lib import repo_resolve

    gh_token = gh_lib.get_token()
    org = course["github_org"]
    repo_prefix = course.get("repo_prefix")   # e.g. "<course>-su26"; None → Step-2 skipped

    # Log-listing CACHE: reconcile runs for EVERY student, so the un-cached
    # `contents/log` listing would be re-fetched once per student. Memoize per path —
    # the log cannot change mid-run.
    #
    # `paginate=False` is SAFE for this endpoint, measured 2026-07-29: the Contents API
    # returns a directory whole — 666 log files came back in one response with NO
    # `rel="next"` Link header, even with `per_page=100` on the URL. (Checked while
    # chasing a false "unregistered" flag; pagination was not the cause and this flag is
    # not the bug. Do not "fix" it without re-measuring.)
    _gh_cache = {}

    def _gh_get_cached(path):
        if path not in _gh_cache:
            _gh_cache[path] = gh_lib.get(gh_token, path, paginate=False)
        return _gh_cache[path]

    gh_get = _gh_get_cached if gh_token else None

    # EMAIL BRIDGE (GRADING Part B §0: "Bridge key = email; name = fallback").
    # fetch_submissions does NOT include email/login_id, so log matching degraded silently
    # to NAME-only — and a Canvas name longer than the registered one ("DANIEL MUNOZ
    # BARRETO" vs log "Daniel Munoz") then produced a FALSE "unregistered" flag.
    uid_email = {}
    try:
        for _u in (canvas.fetch_users(base_url, canvas_token, course_id) or []):
            _em = _u.get("login_id") or _u.get("email")
            if _u.get("id") and _em:
                uid_email[_u["id"]] = _em
    except Exception:  # noqa: BLE001 — email is an optimization; name-match still applies
        pass

    repo_by_uid, source_by_uid, flags, unmapped = {}, {}, [], []
    for sub in submissions:
        u = sub.get("user") or {}
        uid = u.get("id")
        if uid is None:
            continue
        repo_link = repo_resolve.extract_repo_from_body(sub.get("body") or "", org)
        res = repo_resolve.resolve_reconciled(
            repo_link, u.get("name"),
            u.get("login_id") or u.get("email") or uid_email.get(uid),
            org=org, repo_prefix=repo_prefix, code=code, gh_get=gh_get)
        repo, src = res["repo"], res["source"]
        if res.get("flag"):
            # Part B §0 step 3: a link-vs-log disagreement is never resolved silently.
            flags.append({"uid": uid, "name": u.get("name", "?"),
                          "source": src, "note": res["flag"]})
        if not repo:
            unmapped.append({"uid": uid, "name": u.get("name", "?"),
                             "note": res.get("flag") or "no repo link in submission and not "
                                     "found in org-hub log → 0 (submit the repo link)"})
            continue
        repo_by_uid[uid] = repo
        source_by_uid[uid] = src

    return {"repo_by_uid": repo_by_uid, "source_by_uid": source_by_uid,
            "flags": flags, "unmapped": unmapped, "gh_token": gh_token}


def grade(*, submission, asmt, course, repo=None, download_dir, gh_token,
          browser_fetcher=None, student_login=None, att_result=None, **kwargs):
    """Grade one submission using the GitHub autograder + Canvas elaboration.

    `repo` is the repo full_name resolved by `prepare()` (org-hub log + submitted link).
    If None, the student had no resolvable repo — core.py lists them in Section 0 and
    skips them; a repo=None call still scores the elaboration they did write.

    `student_login` is unused (commits are counted by the closed write-set rule);
    kept for signature compatibility.

    `**kwargs` (2026-07-28) — THE UNIFORM CONTRACT. Every other grader already accepted
    `**kwargs`; gh was the only one without it, and that was the ONE reason core.py wrapped
    the call in `if grader_name == "gh"`. Accepting-and-ignoring the extras collapses that
    into a single call site for every grader, and lets quiz.py reuse the SAME contract
    per question instead of re-implementing gh internally (the duplication that left
    `review_content` unset → empty ground_truth → no evidence → view-gate blind on quizzes).
    """
    body = submission.get("body") or ""
    user = submission.get("user") or {}
    first_name = (user.get("name") or "Student").split()[0]
    code = asmt["code"]
    asmt_name = asmt.get("name", "")
    pmax = asmt["points_possible"]
    rubric_dict = dict(asmt.get("rubric") or [])
    if not rubric_dict:
        rubric_dict = default_rubric(pmax)

    # READ ONCE (2026-07-28). Normally this grader reads the submission itself. But a quiz
    # ANSWER is not a Canvas submission — it is raw content (HTML + resolved attachment
    # URLs) living in submission_data, and `attachments.read()`'s own docstring says such a
    # caller must use `read_content` "instead of faking a {"body": ...} submission".
    # quiz.py already did that read, so it hands the result in and we do NOT re-read.
    #
    # Faking it cost a whole run: a synthetic {"body": html} carries no `attachments`, so
    # read() saw expected_n = (images referenced in the HTML) but read_n = 0 →
    # AttachmentReadError → every answer WITH an image failed, and only the single student
    # whose answer had zero images was graded (11 of 12 lost).
    att_result = att_result or att_mod.read(
        submission, download_dir=download_dir, browser_fetcher=browser_fetcher)

    submitted_at = submission.get("submitted_at")
    due_at = asmt.get("due_at")
    # Time-based test judgment (GRADING.md Part B §2): on-time → latest run (credit
    # eventual pass; commit-late tier below handles lateness); late → as of
    # submission time (whole-score Canvas penalty applies in core.py).
    as_of = _decide_as_of(submitted_at, due_at)
    # Instructor logins to exclude from the commit count (closed write-set: student
    # commits = ALL − bots − instructor). org-hub model: the ONLY non-bot, non-student
    # committer is the grading token's owner → instructor_logins(token) = {owner}.
    instr_logins = gh.instructor_logins(gh_token) if gh_token else set()
    # `commit_difficulty` decides whether the §4.4/§4.8 carve-outs apply (a <10-line trivial
    # assignment must not be docked for having no debugging cycle). Authored per assignment;
    # when absent the tier is still computed but carries `needs_difficulty` and gets no floor.
    difficulty = ((asmt or {}).get("commit_difficulty") or kwargs.get("commit_difficulty")
                  or _manifest_difficulty(code))
    rdata = _fetch_repo_data(gh_token, repo, download_dir,
                             student_login=student_login, as_of=as_of,
                             instructor_logins=instr_logins,
                             difficulty=difficulty) if repo else {}
    tp = rdata.get("tp")
    mp = rdata.get("mp") or 100
    commit_count = rdata.get("commit_count", 0)
    commit_insp = rdata.get("commit_inspect") or commit_inspect.inspect([])

    elab_text = att_result["all_text"]

    # KEY VOCABULARY. `core._RUBRIC_LABEL_MAP` normalises a page label to a canonical key, but it
    # emits the NOTEBOOK spellings (`refl`, `rev`) while this grader had only ever read `elab`
    # and `commit`. So a rubric parsed correctly from the page still arrived unreadable here and
    # silently became the literals below — the page said 15 and 8, the student was scored out of
    # 3 and 2, and nothing said a word. Accept both spellings rather than make one module's
    # vocabulary the other's problem.
    test_max = rubric_dict.get("test", 5)
    commit_max = rubric_dict.get("commit", rubric_dict.get("rev", 2))
    elab_max = rubric_dict.get("elab", rubric_dict.get("refl", 3))
    # FAIL LOUDLY WHEN A RUBRIC WAS SUPPLIED AND NONE OF IT REACHED US. Falling back to the
    # literals above is legitimate ONLY when nobody stated a rubric at all (§0: grader default is
    # the last resort). If a rubric IS present but carries no key this grader consumes, the
    # scoring that follows is not "a default" — it is a stated rubric being thrown away in
    # silence, which is the single most expensive failure mode this engine has.
    if rubric_dict and not ({"test", "commit", "rev", "elab", "refl", "link"} & set(rubric_dict)):
        raise ValueError(
            f"rubric supplied for {code!r} but none of its keys are readable by the gh grader: "
            f"{sorted(rubric_dict)}. Expected any of test / commit (or rev) / elab (or refl) / "
            f"link. Refusing to score on the built-in defaults while a rubric is stated "
            f"(GRADING §0 — a stated rubric outranks any grader default).")

    s_test = _score_test(tp, mp, test_max)
    # Due-date penalty on the AUTOGRADER item (GRADING.md Part B §2 + §3.3). The two late
    # cases NEVER stack (§3.3): a LATE SUBMISSION takes the whole-score Canvas penalty
    # (core.py, Case 1) — so the commit-late TEST tier (Case 2) applies ONLY to an ON-TIME
    # submission whose passing run landed after due. Guard: skip the tier when the submission
    # itself was late. Lateness is judged from the FIRST submission (§3.5). (Tiers in
    # _due_penalty are UNCHANGED; homework: no timeout.)
    # TIME PENALTIES live HERE, in one place (2026-07-28). The caller supplies CONTEXT via
    # `asmt`, never a second copy of the tier logic:
    #   asmt["is_quiz"]    → HOURS tiers, no grace (Part D §2.4). Absent ⇒ homework tiers.
    #   asmt["time_limit"] → exam timeout on (repo-created → passing run). Absent ⇒ 0.0.
    # Assignments pass neither, so their behaviour is unchanged. quiz.py passes both when it
    # grades a question, instead of recomputing the fractions itself as it used to.
    _is_quiz = bool(asmt.get("is_quiz"))
    _sub_ts = submission.get("initial_submitted_at") or submitted_at
    _st, _du = _parse_iso(_sub_ts), _parse_iso(due_at)
    # Homework: a LATE submission takes the whole-score Canvas penalty instead, so the
    # commit-late tier must NOT stack (§3.3). A quiz attempt has no such exemption — each
    # attempt is judged at its OWN time (Part D §2.4), so the tier always applies.
    submission_late = bool(_st and _du and _st > _du) and not _is_quiz
    due_frac = 0.0 if submission_late else _due_penalty(rdata.get("run_created_at"), due_at,
                                                        is_quiz=_is_quiz)
    timeout_frac = _timeout_penalty(rdata.get("repo_created_at"), rdata.get("run_created_at"),
                                    asmt.get("time_limit"))
    ag_penalty = round(1 - (1 - due_frac) * (1 - timeout_frac), 4)
    clate_note = None
    if ag_penalty:
        _before = s_test
        s_test = _snap(s_test * (1 - ag_penalty))
        _bits = []
        if due_frac:
            _bits.append(f"passing run {rdata.get('run_created_at')} is past due {due_at} "
                         f"(−{int(due_frac * 100)}%)")
        if timeout_frac:
            _bits.append(f"repo→passing-run exceeded the {asmt.get('time_limit')}-minute limit "
                         f"(−{int(timeout_frac * 100)}%)")
        clate_note = {
            "why": "your code reached its passing state outside the allowed window: "
                   + "; ".join(_bits) + f"; autograder {_before}→{s_test}",
            "how_to_fix": "push your passing code before the due date, within the time limit"}
    s_commit = _score_commits(commit_insp, commit_max, rdata.get("commit_quality"))
    # SERVER-TIME AUTHENTICITY = A SIGNAL, NOT A SENTENCE (2026-07-30). This used to set
    # `s_commit = 0` outright on any NOT-ACCEPTED verdict (instant / single-all-at-once /
    # backdated). Two things were wrong with that:
    #   · §4F.4.2 says so itself — the instant window is a HEURISTIC, "not a hard gate; the
    #     engine only SURFACES the signal, Stage B / the instructor decides." An automatic 0
    #     is exactly the hard gate that sentence rules out.
    #   · §4F is scoped to EXAMS AND ADVANCED work, but the zero applied to every gh
    #     assignment, silently overriding the beginner carve-out (§4.4: a single commit with
    #     "no errors" is acceptable on the simplest ch2–3 work) and the lab/trivial carve-out
    #     (§4.8: <10 lines, single commit graded softly). A <course> A2 student who wrote five
    #     correct lines in one commit lost the whole commit item.
    # The verdict still reaches the grader: `review_content.authenticity` + the Stage-A
    # report's Section 0 flags. Stage B applies the §4F 5-group judgment where it belongs.
    _auth = rdata.get("authenticity") or {}
    commit_not_accepted = _auth.get("accepted") is False
    s_elab = _score_elab(elab_text, elab_max)
    raw = s_test + s_commit + s_elab

    if "link" in rubric_dict:
        link_present = bool(re.search(r"github\.com/[A-Za-z0-9_\-]+/", body))
        s_link = rubric_dict["link"] if link_present else 0
        raw += s_link
    else:
        s_link = None
        link_present = None

    if raw < pmax * MINIMUM_SCORE_RATIO and (att_result["body_text"] or att_result["read_n"] > 1):
        raw = max(1, int(pmax * MINIMUM_SCORE_RATIO))

    # 3-TUPLES, NOT 4 (2026-08-04). Each row used to carry a 4th element — a
    # `{why, how_to_fix}` dict written by `_dedu_test` / `_dedu_commits` / `_dedu_elab` /
    # `_dedu_not_accepted`. NOTHING ever read it: both consumers below destructure with `*_`.
    # It was a SECOND source of student-facing deduction text living beside `comment_render`,
    # the same shape as the Section-3 `comment_html` dump deleted the same day. Worse, what it
    # generated was either redundant or a proxy: the commit wording is already surfaced to
    # Stage B as `commit_quality.reasons` (recomputed from the diffs, so it stays current),
    # and the test/elab wording encoded char-count guesses at judgments GRADING requires
    # Stage B to make from the evidence itself. Deleted with its four generators.
    rubric_rows = [
        ("Program Efficiency & Test Result Correctness", test_max, s_test),
        ("Commit History on Errors", commit_max, s_commit),
        ("Elaboration on Errors and Lessons", elab_max, s_elab),
    ]
    if "link" in rubric_dict:
        rubric_rows.append(("Submission link present (formality)", rubric_dict["link"], s_link))

    # Rule B (re-commit of already-passed code): runs that CONTINUE after the first
    # passing run. Non-empty = the student kept pushing after already passing → Stage B
    # judges whether it is a fabricated "development" history on an already-solved problem.
    _rh = rdata.get("run_history") or []
    _fp = next((i for i, r in enumerate(_rh) if r.get("conclusion") == "success"), None)
    recommit_after_pass = _rh[_fp + 1:] if _fp is not None else []

    return {
        "scores": {"test": s_test, "commit": s_commit, "elab": s_elab,
                   **({"link": s_link} if s_link is not None else {})},
        "raw": raw, "posted": raw,
        "rubric_items": [(lbl, mx) for lbl, mx, *_ in rubric_rows],
        # Stage-B review content (skills/grade/SKILL.md Step 4 packet): the AI reads
        # this to judge what Stage A scored only by proxy — elaboration QUALITY
        # (engine counted chars only) and commit-history legitimacy.
        "review_content": {
            "elaboration": elab_text,
            # RAW elaboration HTML (tags intact) — Stage B checks paste artifacts:
            # inline code tokens as color/font <span>s = pasted from a rendered markdown
            # source (≈ AI chat). Signal only; combine with commit↔narrative + server-time.
            "elaboration_raw_html": att_result.get("raw", "") or body,
            "commits": commit_insp,
            "autograder_tests": f"{tp}/{mp}",
            "repo": rdata.get("repo"),
            # Push-run conclusions oldest→newest. A student-authored `failure` is proof of a
            # real error→fix cycle; NO failure proves nothing (local debugging leaves no run).
            "run_history": rdata.get("run_history"),
            "recommit_after_pass": recommit_after_pass,
            # SERVER-TIME authenticity (online-exam proctor) — instructor-only; Stage B reads
            # this to judge commit legitimacy, and NEVER puts the suspicion in a student comment.
            "authenticity": rdata.get("authenticity"),
            # THE PASSING COMMIT (§4F.6.4) — which change turned the autograder green, and
            # whether the algorithm had ever failed before it. Stage B must describe THIS in
            # the student comment ("what passed, when, and what that commit changed").
            "pass_commit": rdata.get("pass_commit"),
            # COMMIT-QUALITY TIER (§4F.6) — content x time-filtered count x passing commit,
            # with the §4.4/§4.8 carve-out applied. ADVISORY: Stage B may depart from it, and
            # `report_generator` then requires a written `commit_vs_engine` reason. Read
            # `reasons[]` — they are written to be quoted straight into the student comment.
            "commit_quality": rdata.get("commit_quality"),
            "repo_created_at": rdata.get("repo_created_at"),
            "graded_run_created_at": rdata.get("run_created_at"),
            # Stage-B: READ these. The actual diff CONTENT per commit + the screenshot URLs to VIEW
            # (Canvas verifier URLs from the submission body) — so judging needs no side-trip.
            "commit_diffs": rdata.get("commit_diffs"),
            "screenshot_urls": re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', body),
        },
        "authenticity": rdata.get("authenticity"),
        "repo": repo,
        # Instructor-facing lines for report Section 0 — WRITTEN HERE, by the grader that owns
        # the signals (2026-07-28). They used to be composed inside quiz.py from the raw fields
        # below, which had two consequences: the ITERATOR held interpretation logic that belongs
        # to the type grader, and the ASSIGNMENT path — which has no iterator — surfaced none of
        # it. A late autograder penalty or a commit from another account showed up on a quiz and
        # was invisible on the identical repo submitted as homework.
        "needs_review": _engine_notes(repo, tp, ag_penalty, due_frac, timeout_frac,
                                      rdata, recommit_after_pass, asmt),
        # Time penalties ALREADY APPLIED to the test slice above — exposed so callers can
        # report them without recomputing (quiz.py used to recompute its own copy).
        "due_frac": due_frac, "timeout_frac": timeout_frac, "ag_penalty": ag_penalty,
        "run_created_at": rdata.get("run_created_at"),
        "repo_created_at": rdata.get("repo_created_at"),
        "run_history": rdata.get("run_history") or [],
        "commit_flags": rdata.get("commit_flags") or [],
        "recommit_after_pass": recommit_after_pass,
        "oversized_log": rdata.get("oversized_log"),
        "link_present": link_present,
        "tp": tp, "mp": mp,
        "commit_count": commit_count, "commit_inspect": commit_insp,
        "elab_chars": len(elab_text),
        "att_result": {k: att_result[k] for k in ("expected_n", "read_n", "errors")},
    }
