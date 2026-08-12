"""Grade engine orchestrator.

Public API (two-step):
    propose_rubric(config_path, code, canvas_module=None) → {rubric, points_possible, name, asmt_id, source}
    grade(config_path, code, rubric=None, browser_fetcher=None, canvas_module=None) → {report_md, grades_json, ...}

The split lets the caller (90-grade.md agent) show the rubric to the instructor
and accept / modify before grading begins. If `rubric` is None, the grader's
documented defaults are used (scaled to points_possible).

Design rules honored here:
- Repo lookup = org-hub request LOG (`<org>/classroom-admin/log/*.json`) by email,
  submitted link primary (lib/repo_resolve). GitHub Classroom + roster CSV REMOVED 2026-06-25.
- Canvas asmt id = LIVE (caller passes it, or live name-match). SQLite `assignments.canvas_id`
  + `Canvas_asmt_links.md` are RETIRED.
- Rubric = Canvas (Rubric API → fall back to grader default). Never from config.
- Browser fetcher = optional callback injected by the caller; engine never imports playwright.
- Canvas transport = REST via lib/canvas.py (canvas_rest) for EVERY school. The
  credential is resolved by `_credential()`: the school's token, or a CanvasSession
  (cookies + CSRF + auto-relogin) when it has none — canvas_rest accepts either.
  `canvas_module` remains only as a test seam. (WHICH schools is derived from token
  presence, never hardcoded here — see CourseGlobalWorkflow/Access/CanvasAuth.md.)
  Engine source never imports playwright; the shim lives outside engine code.
- Section 0 of report lists: repo-resolution flags (submitted-vs-log discrepancy,
  unregistered, no repo) + STOP cases. Instructor sees and decides manually.
"""
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta

from . import __version__
from .lib import canvas as _default_canvas
from .lib import classify
from .lib import sqlite_db as db_mod
from .lib import late_policy as late_mod
from .lib import contract
from .lib import paths as _paths
from .lib.attachments import AttachmentReadError, read_content
from . import graders          # the REGISTRY — core.py names no individual grader module


PDT = timezone(timedelta(hours=-7))
# Grader resolution lives in `graders/__init__.py`, not here. core.py used to import all five
# modules and hold the name→module table, which meant the orchestrator knew every type by
# name — and quiz.py, needing a sub-grader, could not reuse that table and imported `gh`
# directly instead. One registry serves both tiers (see graders/__init__.py).


def _load_config(course):
    """Course coordinates via the ONE reader — `course_config` (code/README.md: "Never
    open(<config>.json) yourself"). Takes a SLUG or a course_id, never a file path.

    Grading was the last holdout: it took a path argument and opened the json itself, which
    is why the retired `grade_engine/config/` dir stayed alive here after every other consumer
    had moved to `<course>/.claude/course-config/<slug>.json`. A path also let a caller aim the
    engine at any file — the wrong-school class of bug `course_config` exists to prevent.
    A `.json` path is still accepted (…/cs120.json → "cs120") so existing invocations keep
    working; the file it names is no longer read.
    """
    if isinstance(course, str) and course.endswith(".json"):
        course = os.path.basename(course)[:-5]
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import course_config
    return course_config.load(course)


def _credential(config, base_url):
    """The Canvas credential for this course — a token string, or a CanvasSession when the
    school has no token. `canvas_rest` accepts EITHER (client._auth_headers), so the engine
    needs no cookie-specific transport module and none may be added."""
    from canvas_token_auth import get_token
    try:
        return get_token(config["canvas_token_env"], base_url=base_url)
    except RuntimeError:
        school = config.get("school")
        if not school:
            raise RuntimeError(
                "no Canvas token for %s and the config has no `school`, so no cookie session can "
                "be opened. Add `school` to the course config (Where/CourseConfig.md)." % base_url)
        from canvas_auth.session import CanvasSession
        return CanvasSession(school)


# ── classify_assignment() — DELETED 2026-07-28 ────────────────────────────────────
# It "detected" the grader by keyword-scanning the assignment DESCRIPTION
# (`repository` / `green check` / `colab` / `jshell` …). That is not detection:
#   · our own starter boilerplate carries those words, so it mostly echoed the phrasing
#     WE wrote — every CS120 A5x page says "Request your A51 repository … green check",
#     so it returned `gh` for any content whatsoever;
#   · it decided the type BEFORE seeing what the student actually submitted;
#   · it already misrouted a Colab lab to `gh` on a lone "repository" — patched only by
#     reordering the regexes, i.e. held down by pressure, never fixed.
#
# A guess dressed as knowledge is worse than no guess: `general` gathers everything and
# AI Stage B scores it (GRADING §0 — classification is a CONVENIENCE, never required),
# whereas a wrong type silently runs the wrong automation.
#
# Same reasoning that deleted config `asmt_types` on 2026-07-26 ("a config never
# pre-declares an assignment's type" — Where/CourseConfig.md). This was the last remnant.
#
# ROUTING NOW: grader_override (the AI/user DESIGNATES after reading the assignment)
#              → else 'general'. No silent type-guessing anywhere.


def _short_pdt(iso):
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(PDT).strftime(
            "%Y-%m-%d %H:%M PDT"
        )
    except Exception:  # noqa: BLE001
        return iso


def _resolve_canvas_id(canvas, base_url, token, course_id, code, canvas_id=None):
    """Resolve the Canvas assignment id LIVE — no DB, no cached links file.

    The Canvas assignment id is the only stable Canvas key, and the caller normally
    already has it: it is in the assignment / SpeedGrader URL
    (``…?assignment_id=NNN``). ``code`` is the engine's INTERNAL label — it selects
    the grader and names the output files; it is NOT a Canvas key and is never used
    to look anything up in a stored table (that mapping went stale and is retired).

      1. explicit ``canvas_id`` (or a purely-numeric ``code``) → use it as-is.
      2. else match ``code`` against the course's LIVE assignment list by name
         (exact case-insensitive, then unique substring). 0 / >1 matches → raise,
         listing candidates so the caller can pass ``canvas_id=`` directly.
    """
    if canvas_id is None and str(code).strip().isdigit():
        canvas_id = str(code).strip()
    if canvas_id is not None:
        return int(str(canvas_id).strip())
    # EVERY assignment — follow `Link: rel="next"`. This was a single un-paginated GET, so on a
    # course with more than one page it saw only the first: asked for a chapter-6 assignment it
    # answered "no name match" and printed a candidate list that stopped at chapter 5 — i.e. it
    # reported the assignment did not exist while looking at a list that could not have held it.
    # Same defect, same course, as `canvas_core.assignments.list()` (measured 2026-08-02: the
    # chapter-5 exam sat on page 2). A truncated list is worse than an error because it reads as
    # an answer. `canvas_rest.client.get` already walks the pages and accepts a token string or a
    # CanvasSession, so there is no second page-walk to maintain here.
    from canvas_rest.client import get as _rest_get
    asmts = _rest_get(base_url, token, f"/courses/{course_id}/assignments",
                      params={"per_page": 100}) or []
    if isinstance(asmts, dict):
        asmts = asmts.get("assignments") or []
    cl = str(code).strip().lower()
    cand = ([a for a in asmts if (a.get("name") or "").strip().lower() == cl]
            or [a for a in asmts if cl in (a.get("name") or "").lower()])
    if len(cand) == 1:
        return int(cand[0]["id"])
    listing = [f'{a.get("id")}={a.get("name")!r}' for a in (cand or asmts)][:30]
    raise RuntimeError(
        f"Cannot resolve a unique Canvas assignment for code {code!r}: "
        f"{'no name match' if not cand else str(len(cand)) + ' name matches'}. "
        f"Pass canvas_id=<id> explicitly (it is in the assignment URL). "
        f"Live assignments: {listing}")


# ⛔ GRADING §0 — RUBRIC PRECEDENCE: instructions ▶ Canvas rubric object ▶ grader default.
# The INSTRUCTIONS rubric is SUPREME: if the Canvas assignment page states its OWN grading table /
# submission-item list, that outranks any grader default. Grading on a grader-internal default the
# student never saw has ZERO legitimacy when a published rubric exists. A grader default is fine
# ONLY when the instructions state no rubric. This detects the "instructions carry a rubric" case so
# it is FLAGGED, not silently overridden by the default — the AI Stage B reads the real table and
# grades on it. (Real bug this guards: W35 — see GRADING.md §0.)
_INSTR_RUBRIC_SIGNAL = re.compile(
    # `\brubrics?\b` IS THE POINT. Every other alternative here is a paraphrase of the word, and
    # the one spelling the detector could not see was a heading that simply reads
    # `Rubric (50 points)` — which is how every assignment page in this course writes it. The
    # page rubric is supreme in GRADING §0 and in this file's own comments, but the rule only
    # fires if this regex matches first, so a rubric printed in plain sight was reported ABSENT
    # and the grader default won WITHOUT raising. Masked for a whole term because Stage B's
    # authoring file re-declared the rubric by hand downstream, so only the rendered report ever
    # looked right (chapter-6, 2026-08-03: page said 25/15/8/2, Stage A scored on 5/2/3).
    r"how it(?:'s| is) graded|what (?:to|you) submit|grading\s+rubric|points?\s+breakdown"
    r"|\brubrics?\b", re.I)


def _instructions_state_rubric(asmt):
    """True if the assignment instructions appear to carry their own grading rubric / item table."""
    desc = asmt.get("description") or ""
    if not desc:
        return False
    text = re.sub(r"<[^>]+>", " ", desc)
    if not _INSTR_RUBRIC_SIGNAL.search(text):
        return False
    # require a few point numbers → a real points table, not a stray phrase
    return len(re.findall(r"\b\d{1,3}\b", text)) >= 3


class RubricError(Exception):
    """The instructions publish a rubric the engine could NOT parse into grader keys.
    Grading MUST NOT proceed on a fabricated default (GRADING §0) — raise so the caller
    stops and asks the instructor for the rubric. NEVER swallowed into a grader default."""


class RoundError(Exception):
    """The stated round and the round derived from disk do not agree, or the layout cannot be
    counted at all. Same shape as RubricError and for the same reason: the round decides which
    files this gather overwrites, so guessing it can destroy a posted grading. Raised BEFORE
    anything is fetched or written; `--force-round` is the deliberate way past."""


# instruction rubric label → canonical grader key. First match wins; order matters
# (check 'autograder/test' before generic words). Covers NB (comp/refl/rev/link) + gh
# (test/commit/refl/link). A published row whose label maps to NONE ⇒ RubricError (do not guess).
_RUBRIC_LABEL_MAP = [
    (re.compile(r"autograd|\btest", re.I), "test"),
    (re.compile(r"complete|cells?\b|notebook", re.I), "comp"),
    (re.compile(r"elaborat|reflect|learn|summ|takeaway|write-?up|essay|explanation", re.I), "refl"),
    (re.compile(r"revision|commit|\bpin|history|progress|save", re.I), "rev"),
    (re.compile(r"link|access|repo|url|submit", re.I), "link"),
]


def parse_instructions_rubric(asmt):
    """Parse the assignment page's OWN rubric table (GRADING §0 — the source of truth the
    student saw) into ``{grader_key: max_pts}``. Returns None when the instructions state NO
    rubric (→ a grader default is then legitimate). RAISES RubricError when a rubric IS stated
    but cannot be parsed/mapped — grading must stop and ask, never fabricate a default.

    The table is the `<table>` with `<tr>`/`<td>` rows `Item | Points | How graded`; the first
    cell is the label, the first pure-number cell is the points; a 'Total' row is skipped."""
    if not _instructions_state_rubric(asmt):
        return None
    desc = asmt.get("description") or ""
    out, saw_row = {}, False
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", desc, re.I | re.S):
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.I | re.S)
        if len(cells) < 2:
            continue
        label = re.sub(r"<[^>]+>", " ", cells[0]).strip()
        pts = None
        for c in cells[1:]:
            m = re.fullmatch(r"\s*(\d{1,3})(?:\.0)?\s*", re.sub(r"<[^>]+>", " ", c))
            if m:
                pts = int(m.group(1))
                break
        if pts is None or not label:
            continue
        if re.search(r"\btotal\b", label, re.I):
            continue
        saw_row = True
        # `_RUBRIC_LABEL_MAP` is an OPTIONAL normalizer: a KNOWN label -> its canonical grader key
        # (gh/nb keep working unchanged). An UNKNOWN label is NOT an error — the page rubric is the
        # source of truth, so pass the label through AS-IS as its own item key. Grader/AI then scores
        # it as stated (jshell/general are gatherers that score by the page's items). Never crash on a
        # label we don't recognize — that bent the world to the program (only gh/nb vocab could grade).
        key = next((k for rx, k in _RUBRIC_LABEL_MAP if rx.search(label)), None)
        if key is None:
            key = re.sub(r"\s+", " ", label).strip()   # raw label as the item key
        out[key] = out.get(key, 0) + pts
    if not saw_row or not out:
        raise RubricError(
            "the instructions state a rubric (points table detected) but no rubric rows could be "
            "parsed — confirm the rubric with the instructor before grading.")
    # NB/quiz labs with no explicit link/access row → link is NOT a scored item; pin it to 0 so
    # the grader does not inject its 20%-of-points default (which would overflow points_possible).
    pmax = asmt.get("points_possible") or 0
    if "link" not in out and pmax and sum(out.values()) == pmax:
        out["link"] = 0
    return out


def propose_rubric(config_path, code, canvas_module=None, canvas_id=None, grader_override=None):
    """Resolve the rubric. PRECEDENCE (GRADING §0): instructions rubric ▶ Canvas rubric object ▶
    grader default. The instructions rubric is SUPREME — a grader default is legitimate ONLY when
    the instructions state no rubric of their own. When the page DOES state one but Canvas has no
    rubric object, this returns the grader default tagged `grader-default-PROVISIONAL` + a loud note
    so Stage B grades on the instructions, NOT the default.

    Parameters
    ----------
    canvas_module : module | None — Optional drop-in replacement for the default
                    REST canvas module. Must expose the same surface as
                    `grade_engine.lib.canvas` (get, get_token, fetch_assignment,
                    fetch_submissions, fetch_rubric, fetch_users,
                    fetch_uid_to_login_map, extract_github_login_from_body, put,
                    get_raw). Test seam only — a token-less school needs NO injection
                    (the credential is a CanvasSession; see `_credential`).

    Returns:
      {
        'rubric': {item_label: max_pts, ...},
        'points_possible': int,
        'name': str,
        'asmt_id': int,
        'source': 'canvas-rubric' | 'grader-default',
        'note': str,
      }
    """
    canvas = canvas_module or _default_canvas
    config = _load_config(config_path)
    course_id = config["course_id"]
    base_url = config["canvas_base_url"]
    canvas_token = _credential(config, base_url)

    asmt_id = _resolve_canvas_id(canvas, base_url, canvas_token, course_id, code, canvas_id)

    asmt = canvas.fetch_assignment(base_url, canvas_token, course_id, asmt_id) or {}
    points_possible = asmt.get("points_possible") or 10
    asmt_name = asmt.get("name", code)

    # PRECEDENCE (GRADING §0): the instructions' OWN rubric table is SUPREME. Parse it FIRST —
    # it is the source of truth the student actually saw. RubricError (a stated-but-unparseable
    # rubric) propagates: the caller STOPS and asks, never grades on a fabricated default.
    instr = parse_instructions_rubric(asmt)   # dict | None (None = no rubric stated); may raise
    if instr:
        return {
            "rubric": instr,
            "points_possible": points_possible,
            "name": asmt_name,
            "asmt_id": asmt_id,
            "source": "instructions-rubric",
            "note": "Rubric parsed from the assignment page's own grading table (GRADING §0 — supreme).",
        }

    rubric = canvas.fetch_rubric(base_url, canvas_token, course_id, asmt_id)
    if rubric:
        return {
            "rubric": rubric,
            "points_possible": points_possible,
            "name": asmt_name,
            "asmt_id": asmt_id,
            "source": "canvas-rubric",
            "note": "Rubric loaded from Canvas; review or modify before grading.",
        }

    # Fallback: ask grader for default rubric. SAME routing as grade(): explicit override →
    # 'general' floor. A config never pre-declares a type, and neither does a keyword scan
    # of the description (classify_assignment deleted 2026-07-28 — see the note above).
    grader_name = grader_override or graders.FLOOR
    grader = graders.get(grader_name)     # unknown name RAISES — never a silent default
    default = {}
    if grader and hasattr(grader, "default_rubric"):
        default = grader.default_rubric(points_possible)
    # GRADING §0: if the instructions carry their OWN rubric, the default is NOT legitimate — flag it.
    instr_rubric = _instructions_state_rubric(asmt)
    return {
        "rubric": default,
        "points_possible": points_possible,
        "name": asmt_name,
        "asmt_id": asmt_id,
        "source": "grader-default-PROVISIONAL" if instr_rubric else "grader-default",
        "instructions_rubric_detected": instr_rubric,
        "note": ("⛔ INSTRUCTIONS STATE THEIR OWN RUBRIC (GRADING §0 — SUPREME). The grader default "
                 "here is a PLACEHOLDER; Stage B MUST read the assignment page's grading table and "
                 "score THOSE items, not this default." if instr_rubric else
                 "No rubric on Canvas. Using grader-default scaled to points_possible."),
    }


def fetch_instructions(config_path, code, canvas_id=None, canvas_module=None,
                       browser_fetcher=None):
    """STEP 1 OF GRADING — put the assignment page in front of the AI, and grade NOTHING.

    The first act of grading is reading what the assignment asks (GRADING §0, grade
    SKILL RULE #1). Until now the instructions file was only written as a SIDE EFFECT of a
    scoring run — i.e. the engine had already chosen a rubric and produced baseline scores
    before anyone could read the page. That is the wrong order, and it is how a run ended up
    scored on a generic grader default while the page published its own 3/15/6/6 table.

    Fetches the assignment, follows every embedded/linked Google Doc / Slides / iframe in the
    description (the real rubric often lives there, not in the page body), writes
    `<out>/<code>_instructions.md`, and returns where it is. No submissions are read, no
    student is touched, nothing is scored.

    Returns {code, asmt_id, name, points_possible, instructions, published_rubric}.
    `published_rubric` is INFORMATIONAL — what the page's own table parses to, or None. It is
    not applied to anything: you read the file and decide.
    """
    canvas = canvas_module or _default_canvas
    config = _load_config(config_path)
    course_id = config["course_id"]
    base_url = config["canvas_base_url"]
    canvas_token = _credential(config, base_url)

    asmt_id = _resolve_canvas_id(canvas, base_url, canvas_token, course_id, code, canvas_id)
    asmt = canvas.fetch_assignment(base_url, canvas_token, course_id, asmt_id) or {}
    asmt_name = asmt.get("name", code)
    desc = asmt.get("description") or ""

    out_root = config.get("output_dir")
    out_dir = os.path.join(out_root, "grade_result") if out_root else config["out_dir"]
    os.makedirs(out_dir, exist_ok=True)
    import tempfile as _tf
    download_dir = os.path.join(_tf.gettempdir(), f"grade_engine_{code}")
    os.makedirs(download_dir, exist_ok=True)

    try:
        _ic = read_content(desc, download_dir=download_dir, uid=f"asmt{asmt_id}",
                           canvas_token=canvas_token, browser_fetcher=browser_fetcher,
                           allow_quality_failures=True, fetch_visual=False)
        embedded = (_ic.get("all_text") or "").strip()
    except Exception:  # noqa: BLE001 — a dead embed must not stop you from reading the page
        embedded = ""

    path = os.path.join(out_dir, f"{code}_instructions.md")
    with open(path, "w") as f:
        f.write(f"# {code} — {asmt_name}\n\n")
        f.write("<!-- STEP 1: read this BEFORE any scoring run. The rubric you grade on comes "
                "from here (GRADING §0), not from a grader default. -->\n\n")
        f.write(f"- Canvas assignment id: {asmt_id}\n- points_possible: "
                f"{asmt.get('points_possible')}\n- due_at: {asmt.get('due_at')}\n\n")
        f.write("## Canvas description (raw HTML)\n\n")
        f.write((desc or "(no instruction body on the Canvas assignment)") + "\n\n")
        f.write("## Embedded / linked document text (rubric often lives here)\n\n")
        f.write((embedded or "(no embedded/linked document text found)") + "\n")

        # ── QUIZ: the questions ARE the assignment ────────────────────────────────────
        # grade SKILL RULE #1 says to read "the assignment page — every quiz QUESTION too"
        # before the engine runs, but this function only ever wrote the quiz DESCRIPTION.
        # For an exam whose page says "the problems appear only when you start the exam"
        # and "each question is graded strictly by the rubric shown inside it", that file
        # contained neither the problems nor the rubric — the two things Rule #1 exists to
        # put in front of the reader. A question publishes its OWN table and that table
        # outranks any grader default (`graders/quiz._parse_question_rubric`), so it has to
        # be readable BEFORE the scoring run, not inferred from the record afterwards.
        _qid = asmt.get("quiz_id")
        if _qid:
            try:
                _qs = canvas.get(base_url, canvas_token,
                                 f"/courses/{course_id}/quizzes/{_qid}/questions?per_page=100")
            except Exception:  # noqa: BLE001 — a quiz read must not lose the page above
                _qs = None
            f.write(f"\n## Quiz questions (quiz {_qid}) — EACH ONE IS AN ASSIGNMENT\n\n")
            if isinstance(_qs, list) and _qs:
                for _n, _q in enumerate(_qs, 1):
                    f.write(f"### Q{_n} · {_q.get('question_name') or '(unnamed)'} "
                            f"— {_q.get('points_possible')} points "
                            f"(question id {_q.get('id')})\n\n")
                    f.write((_q.get("question_text") or "(empty question body)") + "\n\n")
            else:
                f.write("(no questions returned — the quiz may be unpublished or "
                        "question-level access denied)\n")

    try:
        published = parse_instructions_rubric(asmt)
    except RubricError as e:
        published = {"__unparseable__": str(e)}
    return {"code": code, "asmt_id": asmt_id, "name": asmt_name,
            "points_possible": asmt.get("points_possible"), "due_at": asmt.get("due_at"),
            "instructions": path, "published_rubric": published}


_ORDINALS = ("", "2nd", "3rd", "4th", "5th", "6th", "7th", "8th", "9th", "10th")


def _round_suffixes(json_dir, code, tag):
    """Every round suffix present for `{code}_{tag}*.json` in `json_dir`.

    Exact-matched, never globbed: `A61_*` would also swallow `A610_*`, and the codes in this
    course differ only by that digit. `_audit` is excluded — it is a re-check run, never a
    round (Grade-Workflow "WHICH ROUND NUMBER")."""
    pat = re.compile(rf"^{re.escape(code)}_{re.escape(tag)}(_[A-Za-z0-9]+)?\.json$")
    out = set()
    try:
        names = os.listdir(json_dir)
    except OSError:
        return out
    for n in names:
        m = pat.match(n)
        if m and (m.group(1) or "") != "_audit":
            out.add((m.group(1) or "").lstrip("_"))
    return out


def next_round(json_dir, code):
    """What round a NEW Stage-A gather of `code` would be. Returns `(suffix, confident, why)`
    where `suffix` is None for a first grading, else "2nd" / "3rd" / …

    THE ROUND IS DERIVED, NOT REMEMBERED (2026-08-05). It used to live only in whatever the
    caller typed, so forgetting it silently rewrote round 1 — CS120 A61's 13-student report
    became a 1-student file and the run reported success. Disk already knows: Stage A writes
    one `{code}_stageA{round}.json` per gather and nothing ever overwrites it.

    ⛔ `confident` is the point of this function. Two independent sets are counted — the gather
    archives (`_stageA*`) and the records (`_grade*`) — and the answer is trusted ONLY when they
    agree. They disagree exactly where a count would be confidently WRONG:

      · records but no gather archive  → a pre-`_stageA` layout (CS120 chapter 5 is all of it).
        Counting gathers says "first grading" about work that is already posted.
      · counts differ                  → a gather died between its two writes.

    The caller must STOP on `confident=False` and make a human name the round. A derived value
    that cannot be cross-checked is a guess, and a guess must not choose a filename that can
    overwrite a posted grading."""
    stage = _round_suffixes(json_dir, code, "stageA")
    rec = _round_suffixes(json_dir, code, "grade")
    # THE OLD LAYOUT LIVES ONE LEVEL UP. Before `json/` existed the record was written beside the
    # report as `{code}_grades.json` (note the plural). Looking only in `json/` reported "no prior
    # record — first grading" for CS120 chapter 5 — eight assignments that are graded AND posted,
    # i.e. the confident answer would have been the destructive one. Counted here so those codes
    # land in the disagree branch below and STOP, which is the honest verdict for a layout whose
    # rounds were never recorded.
    _parent = os.path.dirname(json_dir.rstrip(os.sep))
    rec |= _round_suffixes(json_dir, code, "grades") | _round_suffixes(_parent, code, "grades")
    stage |= _round_suffixes(_parent, code, "stageA")
    if not stage and not rec:
        return None, True, "no prior gather or record — first grading"
    if stage == rec:
        n = len(stage)
        if n >= len(_ORDINALS):
            return None, False, f"{n} rounds on disk — beyond the named ordinals"
        return _ORDINALS[n], True, (f"{n} completed round(s) on disk "
                                    f"({', '.join(sorted(s or 'base' for s in stage))})")
    only_rec = sorted(s or "base" for s in rec - stage)
    only_stage = sorted(s or "base" for s in stage - rec)
    why = "gather archives and records disagree"
    if only_rec and not only_stage:
        why = (f"record(s) with no `_stageA` archive: {', '.join(only_rec)} — a pre-2026-07 "
               f"layout; the round cannot be counted from gathers")
    elif only_stage:
        why = f"gather(s) with no record: {', '.join(only_stage)} — a gather died mid-write"
    return None, False, why


def grade(config_path, code, rubric=None, browser_fetcher=None, canvas_module=None,
          canvas_id=None, grader_override=None, report_round=None, force_round=False,
          only_uid=None, audit=False, grace_days=None, q_grader=None, q_graders=None):
    """Grade `code`. Saves report+JSON, never posts.

    q_grader / q_graders : sub-unit designation for a COMPOSITE grader (a quiz and its
                      questions). `q_grader` sets every question's type; `q_graders`
                      ({question_name: type}) overrides individual ones for a mixed exam.
                      Unset ⇒ each question is graded by `general`. Same rule as
                      `grader_override` one tier down: designated, never inferred.

    grace_days      : int | None — late grace for THIS RUN. Omitted ⇒ none. Deliberately a
                      run argument and not a config field: the nine course jsons all carried
                      the same `expected_late_grace_days: 2`, which made it a policy hiding
                      in a coordinates file. Quizzes/exams still force 0 regardless.

    grader_override : str | None — the AI/user-DESIGNATED type ('nb'/'gh'/'quiz'/'general').
                      HIGHEST priority — when the caller already knows the type (the user said
                      "this is an NB lab", or the AI saw a notebook while grading), pass it and the
                      brittle description classifier is skipped entirely. General-first, type-when-known.

    Parameters
    ----------
    config_path     : str  — path to course config JSON.
    code            : str  — assignment code (e.g., 'A41'). Internal label only:
                      selects the grader + names output files. NOT a Canvas key.
    canvas_id       : int | str | None — the Canvas assignment id (from the
                      assignment URL `…assignment_id=NNN`). Preferred input. If
                      None, the id is matched LIVE by assignment name == code.
    rubric          : dict | None — `{item: max_pts, ...}`. If None, grader's
                      default scaled to points_possible is used.
    browser_fetcher : callable | None — `fetcher(url, out_path) -> bool`. Optional.
                      Used by the engine when HTTP fetch returns HTML / 401 / 403.
                      The engine itself never imports a browser library.
    canvas_module   : module | None — Drop-in replacement for grade_engine.lib.canvas.
                      Same API surface required. TEST SEAM ONLY — a token-less school
                      needs no injection; `_credential` hands canvas_rest a
                      CanvasSession (auth-mode home: Access/CanvasAuth.md).
    """
    canvas = canvas_module or _default_canvas
    config = _load_config(config_path)
    course_id = config["course_id"]
    base_url = config["canvas_base_url"]
    canvas_token = _credential(config, base_url)
    # THE COORDINATES THAT ACTUALLY READ CANVAS, stamped into the record (2026-08-02).
    # `post_grades` needs school/base/course_id, and they used to be copied by HAND into the
    # Stage-B authoring json — so when the hand forgot, the render still "succeeded" with three
    # nulls and the poster died at auth. Nothing needs to VERIFY they are present: Stage A could
    # not have fetched a single submission without them. Recording what was used removes the
    # copying step, and with it the only way for them to go missing.
    _post_coords = {"school": config.get("school"), "canvas_base_url": base_url,
                    "course_id": course_id}

    # A miss is NEVER a stop — 'general' is the floor (GRADING Part A §0).
    asmt_id = _resolve_canvas_id(canvas, base_url, canvas_token, course_id, code, canvas_id)

    asmt = canvas.fetch_assignment(base_url, canvas_token, course_id, asmt_id) or {}
    points_possible = asmt.get("points_possible") or 10
    asmt_name = asmt.get("name", code)
    due_at = asmt.get("due_at")

    # Finalize the grader (GRADING Part A §0 — classification is a convenience, NEVER a stop).
    # POLICY: nothing pre-declares an assignment's type — not the course config (asmt_types,
    # deleted 2026-07-26) and not a keyword scan of the description (classify_assignment,
    # deleted 2026-07-28). The type is DESIGNATED by whoever read the assignment; absent that,
    # 'general' is the universal floor (attachments.read gathers everything, AI Stage B scores).
    grader_name = grader_override or graders.FLOOR   # AI/user-DESIGNATED type, else the floor
    # An UNKNOWN name RAISES (graders.UnknownGrader). This used to fall back to `general`,
    # which meant a typo'd `--grader gh2` produced a complete, plausible report under the
    # wrong grader with nothing said. Missing designation → the floor; WRONG designation → stop.
    grader = graders.get(grader_name)
    # Make the missing automation VISIBLE instead of silent: without a designation the run
    # gets no gh/nb/quiz machinery (no autograder, no notebook parse, no per-question scoring).
    # That is the correct default, but it must never look like a full typed grading.
    _no_type_designated = not grader_override

    # RUBRIC (GRADING §0 — instructions rubric is SUPREME). If the caller passed no rubric:
    #   1) parse the instructions' OWN table → use it (the student saw THIS).
    #   2) instructions state a rubric but it can't be parsed → RubricError propagates: STOP and
    #      ask the instructor. NEVER grade on a fabricated grader default in this case.
    #   3) instructions state NO rubric → a grader default is legitimate.
    _used_grader_default = False
    _instr_rubric = False
    # NORMALISE A CALLER-SUPPLIED RUBRIC THE SAME WAY A PARSED ONE IS NORMALISED. The label ->
    # grader-key map ran ONLY inside `parse_instructions_rubric`, so `--rubric` was the one path
    # that reached a grader untranslated. That made the natural thing to write — the page's own
    # wording, copied verbatim — the one input guaranteed not to work, while the grader quietly
    # substituted its own numbers. An instructor-supplied rubric is the highest authority there
    # is; it must not be the only form the engine refuses to understand.
    if rubric:
        rubric = {next((k for rx, k in _RUBRIC_LABEL_MAP if rx.search(str(lbl))), str(lbl)): pts
                  for lbl, pts in rubric.items()}
    # THE ARITHMETIC CHECK NOBODY WAS DOING. A rubric that does not add up to the assignment's
    # own points_possible is wrong by inspection — yet a 10-point rubric was used to score a
    # 50-point assignment and every stage downstream accepted it, because no stage ever compared
    # the two numbers. This is the cheapest possible guard and it would have caught the whole
    # chapter-6 incident at the first run. Tolerance is generous: some pages carry a bonus row.
    if rubric:
        _tot = sum(v for v in rubric.values() if isinstance(v, (int, float)))
        if points_possible and abs(_tot - float(points_possible)) > 0.51:
            raise RubricError(
                f"rubric for {code!r} sums to {_tot} but the assignment is worth "
                f"{points_possible}. A rubric that does not add up to the assignment's points is "
                f"not a rubric for that assignment — confirm it before grading.")
    if rubric is None:
        parsed = parse_instructions_rubric(asmt)   # dict | None; raises RubricError if stated-unparseable
        if parsed:
            rubric = parsed
            _instr_rubric = True
        elif hasattr(grader, "default_rubric"):
            rubric = grader.default_rubric(points_possible)
            _used_grader_default = True
        else:
            rubric = {}
            _used_grader_default = True

    submissions = canvas.fetch_submissions(base_url, canvas_token, course_id, asmt_id) or []
    if only_uid is not None:                      # single-student run: keep just this uid
        submissions = [s for s in submissions if s.get("user_id") == only_uid]
    # RESUBMISSION body fix (re-grade rule #2) — runs for EVERY grader. Canvas's top-level
    # submission.body is often EMPTY on a resubmission, and the link may live in the latest
    # attempt's `url` (online_url) NOT `body`. Give each submission an effective body = the latest
    # attempt's body-or-url (fallback top-level url) so the grader finds the Colab/repo link instead
    # of reading a resubmission as a false 0 (notebook "inaccessible" / repo "missing").
    # (Divyam LabCh7P2 att2, 2026-07-22: att2 body empty, link only in att2.url.)
    for _sub in submissions:
        if (_sub.get("body") or "").strip():
            continue
        _eff = ""
        for _h in sorted(_sub.get("submission_history") or [],
                         key=lambda x: (x.get("attempt") or 0), reverse=True):
            _eff = (_h.get("body") or "").strip() or (_h.get("url") or "").strip()
            if _eff:
                break
        _sub["body"] = _eff or (_sub.get("url") or "")
    buckets = classify.classify_all(submissions)
    if audit:
        # AUDIT / double-check mode (never posts, never overwrites the canonical report — see the
        # `_audit` output suffix below). Already-graded submissions normally sit in the 'graded'
        # bucket and are NOT re-run by the grader; in audit mode we move them into 'resubmit' so the
        # engine RE-COMPUTES a fresh baseline for them. This lets us verify a POSTED score against a
        # clean engine run (e.g. confirm an NB revision count) without touching the live grade.
        buckets["resubmit"] = list(buckets.get("resubmit", [])) + list(buckets.get("graded", []))
        buckets["graded"] = []

    # Instructor identity = the LIVE session/token owner (`/users/self`) — never a
    # hardcoded config uid. A stored uid only goes stale (281905 once pointed at a
    # nonexistent user and failed to mask the instructor's own comments). Used below
    # to exclude the instructor's comments when detecting STUDENT comments.
    try:
        instructor_uid = (canvas.get(base_url, canvas_token, "/users/self") or {}).get("id")
    except Exception:  # noqa: BLE001 — best-effort; None just means no comment is masked
        instructor_uid = None

    download_dir = os.path.join("/tmp", f"grade_engine_{config['school']}_{code}")
    os.makedirs(download_dir, exist_ok=True)

    # ---- Student repo resolution (shared policy: lib/repo_resolve) ----
    # repo = the student's submitted link, confirmed against this assignment's LIVE
    #   Classroom accepted_assignments. NO roster / github_username / name→login.
    #   No link → Section 0 (grader gives 0 + flag). See Where/Data.md G3 /
    #   GRADING.md Part B §0.
    canvas_uid_to_repo = {}
    canvas_uid_to_repo_source = {}   # uid → "body"|"log"|"mismatch"|"unregistered"|"bad-link"
    section0_repo_flags = []  # link-vs-log disagreements (Part B §0 step 3) — instructor must verify
    section0_unmapped = []   # Canvas student → no repo (no link + not in org-hub log)

    # ── CLASS-WIDE PRE-PASS HOOK (2026-07-28) ─────────────────────────────────────────
    # A grader that needs a batch step before per-student scoring exposes prepare().
    # gh does (resolve every repo in one shot: one log listing + one roster fetch, plus
    # the eligibility flags that decide who is skipped). core.py used to run that inline
    # behind `if grader_name == "gh"` — a grader type named inside the orchestrator.
    # Now core.py only asks "do you have a pre-pass?" and stays type-agnostic; any future
    # grader needing one adds prepare() without touching this file.
    gh_token = None
    if hasattr(grader, "prepare"):
        pre = grader.prepare(
            submissions=submissions, course=config, code=code,
            canvas=canvas, base_url=base_url, canvas_token=canvas_token,
            course_id=course_id,
        ) or {}
        canvas_uid_to_repo = pre.get("repo_by_uid") or {}
        canvas_uid_to_repo_source = pre.get("source_by_uid") or {}
        section0_repo_flags = pre.get("flags") or []
        section0_unmapped = pre.get("unmapped") or []
        gh_token = pre.get("gh_token")
    if gh_token is None:
        # Graders without a pre-pass may still need GitHub access (the quiz grader fetches
        # autograder results for code-link questions). Best-effort; None if unavailable.
        try:
            from .lib import github as gh
            gh_token = gh.get_token()
        except Exception:  # noqa: BLE001
            gh_token = None

    student_results = []
    graded_rows = []
    # Set once, by the first quiz student graded (the roster is per-QUIZ, not per-student).
    # Stamped on the record below so the rubric carries `question_id` — see the quiz.py note.
    _quiz_questions = []
    # Grace comes from THIS RUN (caller arg), never from a stored setting. It used to be
    # `expected_late_grace_days` hand-written into every course json — same value (2) in all
    # nine, i.e. not a course coordinate at all. Deleted with the old config dir; see
    # lib/late_policy.py. `grace_days=None` means the caller granted none.
    grace = grace_days or 0
    db = db_mod.open_db(config.get("db_path") or config.get("sqlite_db_path"))
    is_quiz_or_exam = code.startswith(("Q", "E"))
    # Canvas is the source of truth for quiz-ness (NOT the code prefix) — stamped into every
    # grades.json entry so Stage B / report_generator inherit the label instead of re-deciding it.
    is_quiz = bool(asmt.get("is_quiz_assignment")) or bool(asmt.get("quiz_id")) \
        or ("online_quiz" in (asmt.get("submission_types") or []))

    asmt_meta = {
        "code": code,
        "name": asmt_name,
        "points_possible": points_possible,
        "due_at": due_at,
        "rubric": [(k, v) for k, v in (rubric or {}).items()],
        "asmt_id": asmt_id,
        "quiz_id": asmt.get("quiz_id"),
        "description": asmt.get("description"),   # Canvas instruction body (the "bible") — carried to graders + Stage B
        # SUB-UNIT designation, for a COMPOSITE grader (quiz → its questions). Same rule one
        # tier down as `--grader` is here: designated by whoever read the quiz, never inferred.
        # `q_grader` = the default for every question; `q_graders` = per-question exceptions
        # (a mixed exam: essay problems and program problems in one quiz). Both unset ⇒ each
        # question is graded by `general`.
        "q_grader": q_grader,
        "q_graders": q_graders or {},
    }

    for klass in ("graded", "nosubmit"):
        for s in buckets[klass]:
            user = s.get("user") or {}
            student_results.append(
                {
                    "class": klass,
                    "uid": user.get("id"),
                    "name": user.get("name", "?"),
                    "first": (user.get("name") or "Student").split()[0],
                    "existing_score": s.get("score") if klass == "graded" else 0,
                }
            )

    for klass in ("new", "resubmit"):
        for s in buckets[klass]:
            user = s.get("user") or {}
            uid = user.get("id")
            sname = user.get("name", "?")
            try:
                # ── THE CONTRACT (one call site for EVERY grader) ──────────────────
                # Hand every grader the same kwarg bundle; each takes what it needs and
                # ignores the rest (all of them accept **kwargs). Until 2026-07-28 this
                # was an `if grader_name == "gh"` fork — not because gh differs in kind,
                # but because gh alone lacked **kwargs. Removing the fork means core.py
                # names no grader type here, and quiz.py can reuse this exact contract
                # per question (a quiz question IS an assignment; only the loop differs).
                #   repo: resolved by grader.prepare() upstream; None for non-repo types.
                out = grader.grade(
                    submission=s,
                    asmt=asmt_meta,
                    course=config,
                    repo=canvas_uid_to_repo.get(uid),
                    download_dir=download_dir,
                    browser_fetcher=browser_fetcher,
                    gh_token=gh_token,
                    student_login=None,
                    canvas_module=canvas,
                    canvas_base=base_url,
                    canvas_token=canvas_token,
                    course_id=course_id,
                )
                # ── ENFORCE THE CONTRACT AT THE BOUNDARY (2026-07-28) ──────────────
                # The contract used to be an assumption living in the field reads below.
                # A grader could omit a field and the run carried on with a hole: quiz.py
                # returned no `review_content`, so ground_truth was an empty shell, the
                # view-gate exploded zero evidence files, and check() waves an empty
                # manifest through — a whole quiz postable with not one answer read. No
                # exception, no warning; the grade looked finished. Validate HERE, where
                # the grader is still named, instead of failing far away or not at all.
                _cf = contract.check(out, grader_name,
                                     declared=contract.produces(grader))
                for _c in _cf:
                    out.setdefault("needs_review", []).append(_c)
            except AttachmentReadError as e:
                student_results.append(
                    {
                        "class": klass,
                        "uid": uid,
                        "name": sname,
                        "first": sname.split()[0] if sname else "Student",
                        "stop": True,
                        "stop_reason": str(e),
                    }
                )
                print(f"  🚨 {sname} ({uid}): {e}", file=sys.stderr)
                continue
            # A grader may also RETURN a STOP (dict with stop=True) instead of raising — e.g. the NB
            # grader when a notebook link is present but unreadable (fetch failed / not shared), which
            # is NOT a 0 (verify by hand). Handle it the same as a raised STOP: Section 0, not graded.
            if out.get("stop"):
                student_results.append(
                    {"class": klass, "uid": uid, "name": sname,
                     "first": sname.split()[0] if sname else "Student",
                     "stop": True, "stop_reason": out.get("stop_reason", "engine STOP")})
                print(f"  🚨 {sname} ({uid}): {out.get('stop_reason','STOP')}", file=sys.stderr)
                continue
            # Late penalty uses the FIRST (initial) submission, not the latest —
            # a resubmission is never penalized MORE (GRADING.md §3.5). Canvas
            # submission_history holds every attempt; the earliest submitted_at is
            # the initial one (ISO-Z strings sort chronologically). Falls back to
            # the latest if history is absent.
            _hist = [h.get("submitted_at") for h in (s.get("submission_history") or [])
                     if h.get("submitted_at")]
            sub_at = min(_hist) if _hist else s.get("submitted_at")
            student_comments = [
                c for c in (s.get("submission_comments") or [])
                if c.get("author_id") != instructor_uid
            ]
            late_result = late_mod.compute_late(
                code=code,
                uid=uid,
                submitted_at=sub_at,
                due_at=due_at,
                default_grace_days=0 if is_quiz_or_exam else grace,
                db=db,
                canvas_id=asmt_id,   # late_waivers keyed by Canvas asmt id, not code
                student_comments=student_comments,
            )
            late = late_result["late"]
            ld = late_result["days_late"]
            # The engine emits NO student-facing comment, under ANY name. GRADING §4.5/§7.1
            # forbid a postable `comment`; a distinctly-named DRAFT was permitted, and this
            # line wrote `comment_draft` — which NOTHING ever read. It came from a second
            # renderer (`lib/comment.py`) with none of `comment_render`'s enforcement: it
            # printed a below-max row with no reason and no how-to-fix instead of raising
            # CommentError. Its only possible future was someone wiring it to `comment`.
            # Field + module deleted 2026-08-04. Student-facing text is authored exactly
            # once, in Stage B, via `lib/comment_render`.
            entry = {"user_id": uid, "score": out["raw"],
                     "kind": "quiz" if is_quiz else "assignment"}
            if is_quiz:
                entry["quiz_id"] = asmt.get("quiz_id")
                # Part D §2.1: EVERY attempt is graded, so the renderer refuses an authoring
                # file holding fewer attempts than Canvas recorded. It reads that count from
                # `attempts_total`, which the grader returns and this entry used to drop —
                # so the check could never fire and a 2-attempt student was rendered as a
                # 1-attempt one without a word.
                entry["attempts_total"] = out.get("attempts_total")
                if out.get("questions"):
                    _quiz_questions = out["questions"]
            if out.get("earned"):
                entry["earned"] = out["earned"]      # per-rubric breakdown → report_generator columns
            if out.get("scores"):
                entry["scores"] = out["scores"]
            # THE FLOOR ON ANY RE-GRADE, SURFACED UNCONDITIONALLY.
            # CANVAS IS THE SOURCE OF TRUTH for what a student scored, and the number we deal
            # in is the RAW one: we hand Canvas a raw score + the late date, and Canvas applies
            # its own late policy. `entered_score` IS that raw score. `score` is Canvas's
            # post-penalty OUTPUT — reading it compares a raw new score against a penalized
            # prior one and silently lowers the student (Grade-Workflow Step 5).
            #
            # Set for EVERY student, not just `klass == "resubmit"` (2026-08-03). Gating it on
            # the classifier meant the floor existed only when something else had already
            # decided this was a resubmission; when the classifier said otherwise the field
            # was absent, `regrade_floor_issues` fell back to hunting a file, found the
            # Stage-A record whose `score` is a 0 placeholder, and compared every re-grade
            # against 0 — i.e. the gate was silently off. There is no case where knowing the
            # existing grade is wrong, so there is no condition to gate it on. A never-graded
            # student is `None` -> floor 0, which is exactly right.
            entry["entered_score"] = s.get("entered_score")
            # Stage-B review content (skills/grade/SKILL.md Step 4): the AI reads this to
            # judge what Stage A scored by proxy (elaboration quality, commit legitimacy).
            if out.get("review_content"):
                entry["review_content"] = out["review_content"]
            if out.get("oversized_log"):
                entry["oversized_log"] = out["oversized_log"]
            # ENGINE-SIDE PROBLEMS MUST BE VISIBLE (2026-07-28). Graders collect their own
            # failures in `needs_review` (repo had no autograder run, an attachment could not
            # be read, a sub-grader call raised, a time penalty was applied…). core.py never
            # carried it, so those messages died inside the grader: a quiz run where 11 of 12
            # students silently lost their code score looked identical to a clean run, and the
            # only way to find out was to re-derive it from raw data. Surface it.
            if out.get("needs_review"):
                entry["needs_review"] = out["needs_review"]
            if late_result.get("late_policy") == "none":
                entry["late_policy"] = "none"
            elif late_result.get("late_policy") == "late" and late_result.get("seconds_late_override") is not None:
                entry["seconds_late"] = late_result["seconds_late_override"]
            # Quiz multi-attempt (GRADING.md Part D §2): carry EVERY attempt so the
            # poster can write each attempt's per-question scores — Canvas then
            # aggregates per the quiz policy. Engine never averages.
            if out.get("attempts"):
                entry["attempts"] = [
                    {"attempt": a.get("attempt"), "submitted_at": a.get("submitted_at"),
                     "score": a.get("raw"),
                     "needs_ai_essay": a.get("needs_ai_essay") or []}
                    for a in out["attempts"]
                ]
            # Record any STUDENT-left submission comment so validate can check that
            # an instructor reply exists (GRADING.md / grade.md "Student Comment — Reply").
            _sc = [c.get("comment") or "" for c in student_comments]
            if any(s.strip() for s in _sc):
                entry["student_comment"] = " | ".join(s.strip() for s in _sc if s.strip())
            graded_rows.append(entry)
            student_results.append(
                {
                    "class": klass,
                    "uid": uid,
                    "name": sname,
                    "first": (sname.split() or ["Student"])[0],
                    "scores": out["scores"],
                    "raw": out["raw"],
                    "posted": out["posted"],
                    "rubric_items": out.get("rubric_items"),
                    "attempts": out.get("attempts") or [],
                    "late": late,
                    "late_days": ld,
                    "late_reason": late_result.get("reason", ""),
                    "oversized_log": out.get("oversized_log"),
                    # SERVER-TIME authenticity (online-exam proctor) — instructor-only flag list.
                    "authenticity": out.get("authenticity"),
                    # THE PASSING COMMIT (§4F.6.4) — Section 0 prints it for every student.
                    "pass_commit": (out.get("review_content") or {}).get("pass_commit"),
                    # Engine-side problems the grader recorded → Section 0 (2026-07-28).
                    "needs_review": out.get("needs_review") or [],
                }
            )

    # ---- Save report ----
    # STANDARD layout: config["output_dir"] is the output ROOT (.claude/output); reports go
    # under grade_result/. Courses not yet standardized fall back to the legacy out_dir key.
    out_root = config.get("output_dir")
    out_dir = os.path.join(out_root, "grade_result") if out_root else config["out_dir"]
    os.makedirs(out_dir, exist_ok=True)
    import datetime as _dt
    try:
        from zoneinfo import ZoneInfo
        _now = _dt.datetime.now(ZoneInfo("America/Los_Angeles"))
        graded_at = _now.strftime("%Y-%m-%d %H:%M %Z")
    except Exception:
        _now = _dt.datetime.utcnow()
        graded_at = _now.strftime("%Y-%m-%d %H:%M UTC")
    graded_date = _now.strftime("%Y-%m-%d")
    # Report / grades NAMING — ONE stem, two homes (policy: GRADING.md report-naming rule).
    #   • The stem is `<code>_grade` (+ the round suffix). The REPORT keeps that stem as `.md` in
    #     grade_result/; the machine record keeps the SAME stem as `.json` in grade_result/json/.
    #     One name to remember, and the pair is obvious at a glance.
    #   • New grading, or a re-run after an error → use the base stem `<code>_grade`. The existing
    #     files are copied to a temp dir first, so a bad re-run can always be rolled back.
    #   • A genuine RE-SUBMISSION round → add `_2nd` / `_3rd` … via `report_round`, on BOTH files.
    #     Each round then keeps its own report AND its own postable record.
    # AUDIT mode uses `_audit` names, so a double-check run lands beside the live report.
    json_dir = os.path.join(out_dir, "json")
    if audit:
        _sfx = "_audit"
    else:
        # ⛔ CROSS-CHECKED, NEVER TAKEN ON TRUST (2026-08-05). `next_round` derives the round from
        # disk; `report_round` is what a human remembers. Neither decides alone — the derived value
        # VERIFIES the stated one, and a disagreement is an error, not a preference to resolve.
        # Both failure modes are real and both are destructive: forgetting the round rewrote CS120
        # A61's 13-student report as a 1-student file (2026-08-05), and a naive disk count calls a
        # pre-`_stageA` course "first grading" when it is already posted. `force_round` is the one
        # way past — redoing an earlier round on purpose is legitimate, it just has to be said.
        _derived, _sure, _why = next_round(json_dir, code)
        _stated = (report_round or "").strip().lstrip("_") or None
        if force_round:
            report_round = _stated
        elif _stated is None and _sure:
            report_round = _derived
            print(f"round: {_derived or 'base'} (derived — {_why})")
        elif _stated is not None and _sure and _stated == (_derived or ""):
            report_round = _stated
        else:
            raise RoundError(
                f"round not settled for {code!r}.\n"
                f"  stated (--round): {_stated or '(none)'}\n"
                f"  derived from disk: {_derived or 'base'}  [{'confident' if _sure else 'NOT confident'}]\n"
                f"  why: {_why}\n"
                f"  Nothing was gathered and nothing was written. Name the round and confirm it:\n"
                f"    --round {_derived or '2nd'} --force-round")
        _sfx = f"_{report_round}" if report_round else ""
    os.makedirs(json_dir, exist_ok=True)
    md_path = os.path.join(out_dir, f"{code}_grade{_sfx}.md")
    json_path = os.path.join(json_dir, f"{code}_grade{_sfx}.json")
    # [A-4] STAGE-A KEEPS ITS OWN COPY, and it is the one that survives.
    # `<code>_grade.json` is defined by GRADING §5.0 as the POSTER's record, and
    # `report_generator` rightly writes the post-ready record there at the end of the cycle —
    # which silently destroyed everything Stage A had gathered under the same name: the per-
    # commit patches, the run history and the commit timestamps. That loss is not academic:
    # judging commit quality (§4F.6) needs exactly those three, an appeal weeks later needs
    # them, and GitHub does not keep them forever (Actions logs expire; repos get deleted at
    # term end). Re-fetching is possible today and impossible later, so the gather is kept.
    # Two producers, two filenames — the render may run any number of times without erasing
    # the evidence the grade was based on.
    stage_a_json = os.path.join(json_dir, f"{code}_stageA{_sfx}.json")
    stage_a_md = os.path.join(out_dir, f"{code}_stageA{_sfx}.md")
    # REVERT POINT — before overwriting the base name (new run / error re-run), copy the EXISTING base
    # report AND grades.json to a temp dir with a timestamp. Never a silent overwrite: a bad re-run can
    # always be rolled back from temp. (Resubmission rounds use _2nd/_3rd, so they don't overwrite.)
    import shutil as _sh, tempfile as _tf
    for _old in (md_path, json_path):
        if os.path.exists(_old):
            _b, _e = os.path.splitext(os.path.basename(_old))
            try:
                _sh.copy2(_old, os.path.join(_tf.gettempdir(),
                          f"{_b}_{graded_date}_{_now.strftime('%H%M%S')}{_e}.bak"))
            except Exception:  # noqa: BLE001
                pass

    # Read the previous record's counter BEFORE overwriting it (the .bak roll above already
    # preserved the file; this only needs the number).
    _run_n = 1
    try:
        if os.path.exists(json_path):
            _prev_rec = json.load(open(json_path))
            if isinstance(_prev_rec, dict):
                _run_n = int(_prev_rec.get("stage_a_runs") or 0) + 1
    except Exception:  # noqa: BLE001 — a counter must never block a grading run
        _run_n = 1

    with open(json_path, "w") as f:
        # ONE SCHEMA for `<code>_grades.json` — an ENVELOPE, never a bare list (2026-07-30).
        # This file is written TWICE in a grading cycle: here (Stage A) and again by
        # `report_generator` (the post-ready render). Stage A used to dump the raw student
        # LIST while report_generator wrote a DICT, so the same filename held two different
        # schemas depending on how far the cycle had got — every consumer had to guess, and
        # one (the view-manifest stamp) guessed wrong and crashed.
        # THE QUIZ RUBRIC, WITH THE QUESTION IDS ON IT. A quiz posts to a question, so every
        # rubric row must name one (`report_generator._question_ids`). Nothing wrote it: the
        # rubric existed only as an Item|Max table inside the report markdown, which carries no
        # id, so `scaffold` produced a skeleton the renderer then rejected — the same run's two
        # halves disagreeing about a contract neither of them supplied. `kind` is stamped too,
        # so the renderer can tell a quiz from an assignment without inferring it.
        _quiz_meta = ({"kind": "quiz", "quiz_id": asmt.get("quiz_id"),
                       "rubric": [{"item": q["name"], "max": float(q["points_possible"] or 0),
                                   "question_id": q["id"], "question_name": q["name"]}
                                  for q in _quiz_questions]}
                      if _quiz_questions else {})
        # `stage: "A"` is what makes the two distinguishable by DATA: the poster refuses a
        # file still marked stage A — a Stage-A record carries NO comment of any kind, so
        # posting it would send grades with no feedback at all.
        # default=str → datetimes in review_content (commit dates) serialize cleanly.
        # RUN COUNTER — how many times Stage A has re-gathered THIS assignment. Every re-run
        # re-downloads every submission, repo, run-log and commit diff, so a silent 4th pass is
        # real cost paid for nothing. Making the number visible in the record and at the top of
        # the report is the only thing that turns "I re-ran it a few times" into a fact.
        json.dump({"code": code, "assignment_id": asmt_id, "stage": "A",
                   "stage_a_runs": _run_n, "students": graded_rows,
                   **_quiz_meta, **_post_coords}, f, indent=2, default=str)
    # The durable copy (see [A-4] above). Same content, a name the render never touches.
    with open(stage_a_json, "w") as f:
        json.dump({"code": code, "assignment_id": asmt_id, "stage": "A",
                   "stage_a_runs": _run_n, "gathered_at": _now.isoformat(),
                   "students": graded_rows, **_quiz_meta, **_post_coords},
                  f, indent=2, default=str)

    # ── ROUND REGISTER — the list of records Stage A actually produced ────────────
    # Every later stage must be able to answer "is this file MINE?" and today none of them
    # could: the render built the manifest path by gluing `code` together, so an authoring
    # file whose `code` was hand-set to `31_late` sent it looking for `31_late_view_manifest`
    # — a name Stage A has never written. The render succeeded anyway (manifest merely
    # "missing"), and the POSTER blocked, on 25 assignments, after the grading was finished.
    #
    # The register makes the input set closed. Downstream may use ANY round in it — the base
    # grading, a 2nd round, a late round — so going back to correct an earlier round stays
    # possible, which is why the round is NOT auto-selected. What it cannot do is accept a
    # path Stage A never wrote. Recorded as FULL PATHS: matching on filename alone would let
    # a same-named file elsewhere pass, and the point is provenance, not spelling.
    _round_key = (report_round or "").strip() or "base"
    _reg_path = os.path.join(json_dir, f"{code}_rounds.json")
    try:
        _reg = json.load(open(_reg_path)) if os.path.exists(_reg_path) else {}
    except (OSError, ValueError):
        _reg = {}
    _reg.setdefault("code", code)
    _reg.setdefault("assignment_id", asmt_id)
    _reg.setdefault("rounds", {})[_round_key] = {
        # FOLDED (2026-08-05) — `~/…`, not this machine's absolute home. Course_Globals is one
        # Drive folder on more than one Mac; an absolute home stored here is unreadable on the
        # other one, which is how a render lost its manifest (CS120 A61). lib/paths.py
        "record": _paths.fold(json_path),
        "stage_a_record": _paths.fold(stage_a_json),
        "report": _paths.fold(md_path),
        "gathered_at": _now.isoformat(),
        "stage_a_runs": _run_n,
    }
    with open(_reg_path, "w") as f:
        json.dump(_reg, f, indent=1, ensure_ascii=False)

    # Canvas INSTRUCTIONS (the "bible") saved ONCE per assignment — for Stage B to READ before
    # judging, EVERY grader type (not just NB). Stage B grades against these requirements/rubric
    # (GRADING §0 / grade skill Step 1). We do NOT just dump the raw description: the real rubric
    # often lives in a Google Doc/Slides EMBEDDED in the page, so read_content scans the description
    # and follows EVERY embed/link (gdoc, slides, iframe, file) wherever it is and pulls its text.
    # Human-readable artifacts stay in grade_result/ beside the report; grade_result/json/ holds
    # only the machine record and its own siblings (view-manifest, comment ledger).
    instr_path = os.path.join(out_dir, f"{code}_instructions.md")
    _desc = asmt.get("description") or ""
    try:
        _ic = read_content(_desc, download_dir=download_dir, uid=f"asmt{asmt_id}",
                           canvas_token=canvas_token, browser_fetcher=browser_fetcher,
                           allow_quality_failures=True, fetch_visual=False)
        _embedded = (_ic.get("all_text") or "").strip()
    except Exception:  # noqa: BLE001
        _embedded = ""
    with open(instr_path, "w") as f:
        f.write(f"# {code} — {asmt_name}\n\n")
        f.write("<!-- Canvas instruction body + embedded docs. Stage B MUST read ALL of this and "
                "grade against it; the real rubric often lives in the embedded Google Doc/Slides. -->\n\n")
        f.write("## Canvas description (raw HTML)\n\n")
        f.write((_desc or "(no instruction body on the Canvas assignment)") + "\n\n")
        f.write("## Embedded / linked document text (rubric often lives here)\n\n")
        f.write((_embedded or "(no embedded/linked document text found)") + "\n")

    # GROUND-TRUTH sidecar (per uid) — the actual answer code + reflection + engine-computed forbidden
    # shortcuts. report_generator uses it to (a) VERIFY every evidence `quote` is a real substring of
    # the student's own work (a fabricated/generic saw cannot be quoted) and (b) HARD-BLOCK a full
    # completeness score on an item whose code calls a forbidden built-in. Mechanical, ground-truth,
    # un-fakeable — replaces "please read the code" prose. Written for EVERY grader (empty where N/A).
    from .lib.nb_inspect import forbidden_in as _forbidden_in
    gt = {}
    for e in graded_rows:
        rc = e.get("review_content") or {}
        tasks = rc.get("tasks") or []
        code_src = "\n".join((t.get("evidence") or {}).get("code_src", "") for t in tasks)
        forbidden = {}
        for t in tasks:                                   # NB: per-anchor forbidden already computed
            fb = (t.get("evidence") or {}).get("forbidden") or []
            if fb:
                forbidden[t.get("anchor") or t.get("prompt", "")[:24]] = fb
        if not code_src:                                  # git / other: source = commit patch content
            code_src = "\n".join((p.get("patch") or "")
                                 for cd in (rc.get("commit_diffs") or [])
                                 for p in (cd.get("patches") or []))
            if code_src:
                fb = _forbidden_in(code_src)
                if fb:
                    forbidden["repo"] = fb
        gt[str(e.get("user_id"))] = {
            # NB has no task-extracted code_src → fall back to the notebook's own code cells
            # (rc["cells_src"]) so a completeness quote can be verified against the real cells.
            "code_src": code_src or (rc.get("cells_src") or "") or (rc.get("all_text") or ""),
            "reflection": rc.get("reflection_text") or rc.get("elaboration") or "",
            "forbidden": forbidden,
        }
    gt_path = os.path.join(out_dir, f"{code}_ground_truth.json")
    with open(gt_path, "w") as f:
        json.dump(gt, f, indent=1, ensure_ascii=False, default=str)

    sc_by_uid = {e.get("user_id"): e.get("student_comment") for e in graded_rows}

    with open(md_path, "w") as f:
        # ---- Header: assignment + graded datetime ----
        f.write(f"# {code} — {asmt_name}\n\n")
        # MONITOR alert (top of report): any run log over the 5 MB threshold. Grading
        # ran in FULL — this only gathers size data to decide a real cap later.
        _oversized = [r for r in student_results if r.get("oversized_log")]
        if _oversized:
            f.write("> # ⚠⚠ LARGE AUTOGRADER LOG(S) — MONITOR\n>\n")
            f.write("> These run logs exceeded the 5 MB monitor threshold. Grading still ran "
                    "in full (NOT a block) — this is a data-gathering alert to decide whether a "
                    "real download cap is warranted:\n>\n")
            for r in _oversized:
                ol = r["oversized_log"] or {}
                f.write(f"> - **{r['name']}** (uid {r['uid']}): {ol.get('uncompressed_mb')} MB "
                        f"uncompressed (zip {ol.get('zip_kb')} KB)\n")
            f.write("\n")
        f.write(f"graded `{graded_at}`  ·  Canvas ID `{asmt_id}`  ·  Due `{_short_pdt(due_at)}`  "
                f"·  Points {points_possible}  ·  grader `{grader_name}` (engine v{__version__})"
                # Stage-A run counter: a re-gather re-downloads every submission, repo, run-log
                # and commit diff. Printing the number makes a silent 4th pass impossible to miss.
                + (f"  ·  **Stage-A run #{_run_n}**" if _run_n > 1 else "") + "\n\n")
        # ---- Rubric used (table) — the ACTUAL items the grader scored (full names,
        # matching the student comment), taken straight from the grader's return
        # (`rubric_items`). Falls back to the numeric rubric dict only if no student
        # was graded this run.
        _n_gathered = len([r for r in student_results if not r.get("stop")])
        f.write(f"> # ⛔ DATA READY — NOT GRADED · **0/{_n_gathered} judged**\n>\n"
                f"> Stage A only GATHERED data (commit diffs, timing, elaboration text, screenshot "
                f"URLs — all in `review_content`). This is NOT a grade. **Stage B MUST, per student: "
                f"READ the actual commit diff + VIEW every screenshot, then judge and write an "
                f"individual comment.** The baseline score/comment below is a placeholder — shipping "
                f"it as-is means Stage B was skipped.\n\n")
        f.write("**Rubric used** (this grading)\n\n")
        _items = next((r["rubric_items"] for r in student_results if r.get("rubric_items")), None)
        if _items:
            f.write("| Item | Max |\n|---|---|\n")
            for lbl, mx in _items:
                f.write(f"| {lbl} | {mx} |\n")
            f.write("\n")
        elif rubric:
            f.write("| Item | Max |\n|---|---|\n")
            for k, v in rubric.items():
                mx = v.get("max", "") if isinstance(v, dict) else v
                f.write(f"| {k} | {mx} |\n")
            f.write("\n")
        else:
            f.write("_(none recorded)_\n\n")
        if _instr_rubric:
            f.write("> ✅ **Rubric parsed from the assignment page's OWN grading table (GRADING §0 — "
                    "supreme).** These are the weights the student saw; Stage B grades on THESE.\n\n")
        elif _used_grader_default:
            f.write("> ℹ️ The instructions state no rubric table; using the grader default scaled to "
                    "points_possible. If the page does publish a rubric, stop and pass it explicitly.\n\n")
        f.write("> Stage-A engine baseline (code only). AI Stage B fills essay scores + final "
                "grades and authors comments via `lib/comment_render` (which enforces the rubric "
                "+ a reason per below-max row AT GENERATION — a policy-invalid comment cannot be "
                "produced). The engine posts nothing.\n\n")

        # ---- Section 0 — Instructor Action (student comments needing reply + flags) ----
        f.write("## Section 0 — Instructor Action\n\n")

        # NO TYPE DESIGNATED → this ran on the 'general' floor. Correct as a default, but the
        # type-specific automation did NOT run (no autograder result, no notebook parse, no
        # per-question quiz scoring). Say so out loud: since classify_assignment was deleted
        # (2026-07-28) nothing guesses the type, so a forgotten --grader must never look like
        # a full typed grading.
        if _no_type_designated:
            f.write("**ℹ️ No grader type designated → graded on the `general` floor.** "
                    "Materials were gathered and AI Stage B scores them, but NO type-specific "
                    "automation ran (gh: autograder + commit analysis · nb: notebook/revision "
                    "parse · quiz: per-question + per-attempt). If this assignment IS one of "
                    "those types, re-run with `--grader gh|nb|quiz` to get that automation.\n\n")

        # WHAT THE GRADER FLAGGED (needs_review) — everything the instructor must look at before
        # trusting a score. TWO kinds, deliberately in one list because both block a confident
        # post: OUR problems (unreadable attachment, repo with no autograder run, sub-grader
        # raised) and STUDENT-BEHAVIOUR signals the engine noticed but must not judge alone
        # (commit from another account, re-commit after first pass, burst/paste pattern,
        # unexecuted cells, notebook shared as Viewer). The header said "NOT student fault"
        # until 2026-07-28, which was true when only gh's engine errors landed here and became
        # wrong once the type graders started emitting their own signals — an instructor reading
        # "not student fault" over a paste-pattern flag is being told the opposite of the truth.
        _eng_issues = [(r, n) for r in student_results if not r.get("stop")
                       for n in (r.get("needs_review") or [])]
        if _eng_issues:
            f.write(f"**⚠ Flagged by the grader** ({len(_eng_issues)}) — engine problems AND "
                    "student-behaviour signals, mixed. NOT verdicts: verify each before "
                    "trusting the affected scores.\n\n")
            for r, n in _eng_issues:
                f.write(f"- **{r['name']}** (uid {r['uid']}): {n}\n")
            f.write("\n")
        wrote0 = False
        sc_rows = [r for r in student_results if sc_by_uid.get(r["uid"])]
        if sc_rows:
            f.write("**Student comments — reply required:**\n")
            for r in sc_rows:
                f.write(f'- {r["name"]} (uid {r["uid"]}): "{sc_by_uid.get(r["uid"])}"\n')
            f.write("\n"); wrote0 = True
        if section0_repo_flags:
            f.write(f"**⚠ Repo reconcile — submitted link vs org-hub log** ({len(section0_repo_flags)}) "
                    f"— GRADING Part B §0 step 3; verify before posting:\n")
            for r in section0_repo_flags:
                f.write(f"- {r['name']} (uid {r['uid']}) [`{r['source']}`]: {r['note']}\n")
            f.write("\n"); wrote0 = True
        if section0_unmapped:
            f.write(f"**No repo resolved** ({len(section0_unmapped)}) — no repo link in the "
                    f"submission and not found in the org-hub request log (student must submit the link):\n")
            for r in section0_unmapped:
                f.write(f"- {r['name']} (uid {r['uid']})\n")
            f.write("\n"); wrote0 = True
        if canvas_uid_to_repo:
            # The resolved repo per student — printed so Stage B never has to re-derive it
            # (it was re-fetched by hand for 17 repos on 2026-07-09; the engine already had it).
            f.write(f"**Resolved repos** ({len(canvas_uid_to_repo)}) — repo · how it was resolved:\n\n")
            f.write("| Student | uid | Repo | Source |\n|---|---|---|---|\n")
            for r in student_results:
                _rp = canvas_uid_to_repo.get(r["uid"])
                if _rp:
                    f.write(f"| {r['name']} | {r['uid']} | `{_rp}` | {canvas_uid_to_repo_source.get(r['uid'],'?')} |\n")
            f.write("\n"); wrote0 = True
        stop_rows = [r for r in student_results if r.get("stop")]
        if stop_rows:
            f.write(f"**Engine STOP — attachments unreadable** ({len(stop_rows)}):\n")
            for r in stop_rows:
                f.write(f"- {r['name']} (uid {r['uid']}): {r.get('stop_reason','')}\n")
            f.write("\n"); wrote0 = True
        # ---- Commit-authenticity flags (online-exam PROCTOR) — auto-surfaced, instructor-only ----
        # Fully-online course + online exams → commit history is the anti-plagiarism proctor.
        # A single/all-at-once commit, an instant repo->pass, or backdated commit dates are NOT
        # accepted for full commit credit; Stage B decides the score, but the signal shows here
        # every run without being asked. NEVER copy this suspicion into a student comment.
        auth_rows = [r for r in student_results
                     if (r.get("authenticity") or {}).get("flags")]
        if auth_rows:
            f.write(f"**⚠ Commit-authenticity flags — server-time proctor** ({len(auth_rows)}) "
                    f"— instructor-only; NOT student-facing:\n")
            for r in auth_rows:
                a = r["authenticity"]
                gap = a.get("repo_to_pass_min")
                gap_s = f"{gap} min" if gap is not None else "?"
                f.write(f"- {r['name']} (uid {r['uid']}) — `{a.get('verdict')}` "
                        f"(repo→pass {gap_s}): {' '.join(a.get('flags') or [])}\n")
            f.write("\n"); wrote0 = True
        # ---- THE PASSING COMMIT (§4F.6.4) — auto-surfaced every run, instructor-only ----
        # Commit COUNT hides the shape that matters: whether the algorithm ever FAILED before it
        # passed. Printed for everyone (not only the flagged), because "real_fix" is the finding
        # that CLEARS a student — and the two one-shot verdicts are what a count-based read misses
        # (three commits three minutes apart look fine while the solution arrived whole).
        pc_rows = [r for r in student_results if r.get("pass_commit")]
        if pc_rows:
            f.write(f"**Passing commit — what turned the autograder green** ({len(pc_rows)}):\n")
            for r in pc_rows:
                p = r["pass_commit"]
                mark = "⚠ ONE-SHOT" if p.get("oneshot") else "ok"
                f.write(f"- {r['name']} (uid {r['uid']}) — `{p.get('verdict')}` {mark}: "
                        f"`{p.get('sha')}` \"{p.get('message')}\" — {p.get('note')}\n")
            f.write("\n"); wrote0 = True
        # ---- Watch notes (instructor DB `students.notes`) — auto-surfaced, instructor-only ----
        # Prior-grading observations kept in the SQLite DB (e.g. "single-commit repeat — watch this").
        # Surfacing them here means a previously-flagged student is re-checked automatically on the
        # NEXT assignment, unprompted. If the student is ALSO authenticity-flagged THIS run, mark it
        # a repeat. Never student-facing.
        _auth_flagged = {r["uid"] for r in student_results if (r.get("authenticity") or {}).get("flags")}
        note_rows = []
        for r in student_results:
            st = db_mod.get_student(db, r["uid"]) if db is not None else None
            if st and (st.get("notes") or "").strip():
                repeat = "  ⚠ ALSO FLAGGED THIS RUN" if r["uid"] in _auth_flagged else ""
                note_rows.append((r["name"], r["uid"], st["notes"].strip(), repeat))
        if note_rows:
            f.write(f"**⚠ Watch notes (instructor DB — prior observations)** ({len(note_rows)}):\n")
            for name, uid, note, repeat in note_rows:
                f.write(f"- {name} (uid {uid}){repeat}: {note}\n")
            f.write("\n"); wrote0 = True
        if not wrote0:
            f.write("None.\n\n")

        # ---- Section 1 — Final Grades (Stage-A baseline; AI Stage B FINAL is authoritative) ----
        f.write("## Section 1 — Final Grades\n\n")
        f.write("_Stage-A baseline (code only; essays pending). The AI **Stage B FINAL** "
                "(grades.json + appended section) is the authoritative grade._\n\n")
        # Per-rubric columns (from each grader's `scores` breakdown) so the summary shows WHICH item lost
        # points, not just the total. Keys come from the rubric (e.g. link/comp/rev/refl for NB).
        rub_keys = list((rubric or {}).keys())
        _rc = " | ".join(f"{k}/{rubric[k]}" for k in rub_keys)
        f.write("| Student | UID | Class | " + (_rc + " | " if _rc else "") + f"Score/{points_possible:g} | Late |\n")
        f.write("|---|---|---|" + "---|" * (len(rub_keys) + 2) + "\n")
        _dash = " | ".join("—" for _ in rub_keys)
        _pre = (_dash + " | ") if rub_keys else ""
        for r in student_results:
            if r.get("stop"):
                f.write(f"| {r['name']} | {r['uid']} | 🚨 STOP | {_pre}— | — |\n")
                continue
            if r["class"] == "graded":
                f.write(f"| {r['name']} | {r['uid']} | ✅ SKIP | {_pre}(already {r.get('existing_score','?')}) | — |\n")
                continue
            if r["class"] == "nosubmit":
                _z = (" | ".join("0" for _ in rub_keys) + " | ") if rub_keys else ""
                f.write(f"| {r['name']} | {r['uid']} | ❌ no-sub | {_z}0 | — |\n")
                continue
            late_str = f"LATE({int(r['late_days'])}d)" if r.get("late") else "—"
            emoji = "🔄" if r["class"] == "resubmit" else "🆕"
            _sc = r.get("scores") or {}
            _cells = (" | ".join(str(_sc.get(k, "?")) for k in rub_keys) + " | ") if rub_keys else ""
            f.write(f"| {r['name']} | {r['uid']} | {emoji} | {_cells}{r['raw']:g} | {late_str} |\n")

        # quiz multi-attempt — sub-part of Final Grades (each attempt a separate grade)
        multi = [r for r in student_results if len(r.get("attempts") or []) > 1]
        if multi:
            f.write("\n**Quiz multi-attempt** — each attempt is a SEPARATE grade; Canvas "
                    "aggregates per the quiz policy (average/best/latest); the grader never "
                    "averages. Post each attempt's per-question scores (not the fudge-points field):\n\n")
            f.write("| Student | UID | Attempt | Score (code) | Submitted |\n|---|---|---|---|---|\n")
            for r in multi:
                for a in sorted(r["attempts"], key=lambda x: (x.get("attempt") or 0)):
                    f.write(f"| {r['name']} | {r['uid']} | {a.get('attempt')} | "
                            f"{a.get('raw')}/{points_possible} | {a.get('submitted_at','')} |\n")
            f.write("\n")

        # ---- Section 2 — Deductions / Notable (Stage-A; finalized in Stage B) ----
        f.write("\n## Section 2 — Deductions / Notable\n\n")
        _ded = [r for r in student_results if r["class"] in ("new", "resubmit")
                and r.get("raw") is not None and r["raw"] < points_possible]
        if _ded:
            # Pointed at "Section 3" until 2026-08-04, when that section was deleted — the line
            # was sending a reader to a heading this file no longer writes. There is nothing in
            # Stage A to point AT: Stage A records the NUMBER, the reason is authored in Stage B.
            f.write("Below full marks at Stage A — the number only. The per-student reason is "
                    "authored in Stage B and rendered into the graded report's §5:\n")
            for r in _ded:
                f.write(f"- {r['name']} (uid {r['uid']}): {r['raw']}/{points_possible}\n")
            f.write("\n")
        else:
            f.write("None below full marks at Stage A.\n\n")

        # ---- Section 3 (Comments) DELETED 2026-08-04 ----
        # It dumped the engine's DRAFT comment (`html_comment`, rendered by `lib/comment.py`)
        # as "HTML FOR CANVAS". That was a second renderer with none of `comment_render`'s
        # enforcement — it printed a below-max row with no reason and no how-to-fix instead of
        # raising CommentError — and the label invited exactly the wrong move: copying Stage-A
        # HTML to Canvas. It was ALREADY empty for the `general` and `jshell` graders, which
        # returned "". Student-facing text is authored once, in Stage B, via `comment_render`;
        # the report that carries it is `report_generator`'s §5, not this file.

        # ---- Section 4 — Summary ----
        f.write("## Section 4 — Summary\n\n")
        f.write(f"graded {len(graded_rows)} · skip {len(buckets['graded'])} · "
                f"no-submit {len(buckets['nosubmit'])} · "
                f"STOP {sum(1 for r in student_results if r.get('stop'))}  ·  **Nothing posted.**\n")

    # [A-4] The Stage-A REPORT is kept under its own name too. `<code>_grade.md` is the
    # instructor's final report and the render overwrites it — correctly — so the gather
    # narrative (Section 0 flags, resolved repos, authenticity, the passing commit per
    # student) would otherwise exist only until Stage B ran. That narrative is the audit
    # trail behind every commit deduction, which is exactly what an appeal asks to see.
    import shutil as _sh2
    try:
        _sh2.copy2(md_path, stage_a_md)
    except Exception:  # noqa: BLE001 — a keepsake copy must never break a grading run
        pass

    n_stops = sum(1 for r in student_results if r.get("stop"))
    print(
        f"✓ {code}: {len(graded_rows)} graded · {len(buckets['graded'])} skip · "
        f"{len(buckets['nosubmit'])} no-sub · {n_stops} STOP · "
        f"S0 unmapped={len(section0_unmapped)}"
    )
    print(f"  saved: {md_path}")
    print(f"  saved: {json_path}")
    print(f"  kept:  {stage_a_json}  (+ {os.path.basename(stage_a_md)}) — survives the render")
    print("Engine done (Stage-A baseline). Stage B fills essays + final and renders comments "
          "via `lib/comment_render` (reason enforced at generation) before showing/posting. Nothing posted.")
    print(f"  instructions (READ before judging): {instr_path}")
    return {
        "code": code,
        "report_md": md_path,
        "grades_json": json_path,
        "instructions": instr_path,
        "buckets": {k: len(v) for k, v in buckets.items()},
        "stops": n_stops,
        "graded": len(graded_rows),
        "section0": {
            "unmapped": len(section0_unmapped),
        },
    }


# Backwards-compatible alias for callers still using the old name
def run(config_path, code, **kwargs):
    return grade(config_path, code, **kwargs)
