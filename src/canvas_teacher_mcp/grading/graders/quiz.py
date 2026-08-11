"""Quiz / Exam grader — COMPOSITE. An ITERATOR, never a scorer.

A quiz is a SET of questions, and a QUESTION IS AN ASSIGNMENT. This module loops
attempt × question and hands each question to a type grader through the SAME
contract core.py uses for a whole assignment. It scores nothing itself:

    core.py ──> quiz.py ──(per question, same contract)──> gh | nb | jshell | general
     0층         1층                                         2층 = the SAME modules
                                                             an assignment uses at 1층

Each question is wrapped as a one-off `asmt` carrying the question's OWN published
rubric (parsed from the question text) and its own points — GRADING §0: the rubric
the student saw outranks any grader default.

TYPE IS DESIGNATED, NEVER INFERRED. `--q-grader` sets every question's type;
`--q-graders {"<question>": "<type>"}` overrides individual ones for a MIXED exam
(MID1 = an algorithm essay + a program per problem). Neither given ⇒ `general`:
gather the answer, Stage B scores it. Nothing is sniffed.

  ⚠ This docstring claimed the opposite until 2026-07-28 — "graded by its TYPE, read
  from the QUESTION TEXT" — describing a dispatcher that was never written. The code
  actually branched on whether the STUDENT pasted a repo link: a code question missing
  its link silently became an ungraded essay, and no non-git question type could be
  reached at all. Reading the question text would have been the same disease anyway
  (`classify_assignment` was deleted the same day for keyword-scanning a description
  and matching our own starter boilerplate).

Commit history is graded only where the designated grader grades it (gh); an essay
question routed to `general` has none, per the quiz instruction "commit only for
coding, not for essay or flowchart".

Requires from core.py via kwargs:
  canvas_module, canvas_base, canvas_token, course_id, gh_token
"""
import os
import re
import shutil
import subprocess
from html import unescape

from ..lib import github as gh_lib
from ..lib import repo_resolve
from ..lib import attachments
# NO `from . import gh` here. A tier must not reach for a specific peer — that single import
# is what kept "the bottom tier is shared" a claim instead of a fact, because a quiz question
# could only ever reach `gh`. Sub-graders are resolved through the SAME registry core.py uses
# (imported lazily inside the call to avoid a circular import: graders/__init__ imports this
# module). See `_sub_grader()` below.

# What this grader emits on EVERY normal grade (lib/contract.py). Declared, not inferred — and
# this is the module the declaration exists BECAUSE of: it silently returned no
# `review_content`, which emptied ground_truth, produced zero evidence files, and left the
# view-gate waving an empty manifest through. A declared-but-empty field is now reported
# instead of vanishing.
# `needs_review` is deliberately absent: it holds engine-side PROBLEMS (time penalty applied,
# commit flags, no autograder run), so a clean submission has none. Measured on Q52P1 —
# declaring it flagged every untroubled student.
PRODUCES = frozenset({"review_content", "attempts", "rubric_items"})


# Sub-grader return keys this tier already handles by name, so `code_data["detail"]` carries
# the REST. `review_content` and `needs_review` are collected separately (evidence + Section 0);
# raw/scores/rubric_items are re-exposed at the top of code_data; `posted` is the grader's own
# per-unit figure, meaningless for one question inside a quiz.
_CONSUMED_KEYS = frozenset({
    "raw", "posted", "scores", "rubric_items",
    "review_content", "needs_review",
})


def _sub_grader(name):
    """Resolve a QUESTION's grader through the shared registry — the same table core.py uses
    for an assignment, so a question really is graded by the same module (README ◆ 3-tier).

    Imported here, not at module top: `graders/__init__` imports this module to register it,
    so a top-level import would be circular. The cost is one dict lookup per question.
    """
    from . import get      # noqa: PLC0415 — deliberate, see docstring
    return get(name)


def prepare(**kw):
    """CLASS-WIDE PRE-PASS — delegated to the `gh` grader (core.py calls this when present).

    A quiz CODE question needs exactly the repo resolution an assignment gets: the canonical
    repo from the org-hub request log, matched by the student's Canvas email — not merely the
    link the student happened to paste in that one answer box. That pre-pass (log-listing
    cache + email bridge + `repo_resolve.resolve_reconciled`) already exists in `gh.prepare`,
    so it is CALLED here rather than copied — one implementation, the quiz only iterates
    (README ◆ the grading-side symmetry). Resolved through the registry, never an import of a
    specific peer (see `_sub_grader`).

    Without this, `resolve(repo_link)` was the whole resolution: a code question whose link
    was missing got no repo → no autograder run, no commit history → the question scored 0,
    while the same problem delivered as an ASSIGNMENT graded fine. GRADING Part B §0: "do NOT
    score 0 merely because no link was pasted — the log is the source of truth."

    `unmapped` is DROPPED: it means "this student has no repo at all", which is the NORMAL
    case for a quiz whose questions are essays — passing it up would flag the whole class in
    Section 0. Real link-vs-log discrepancies (`flags`) are kept.
    """
    pre = _sub_grader("gh").prepare(**kw) or {}
    return {"repo_by_uid": pre.get("repo_by_uid") or {},
            "source_by_uid": pre.get("source_by_uid") or {},
            "gh_token": pre.get("gh_token"),
            "flags": pre.get("flags") or [],
            "unmapped": []}


# Module-level caches so we don't refetch per-student.
_QSUBS_CACHE = {}        # quiz_id → {uid: {qsub_id, attempt, submission_data}}
_QQUESTIONS_CACHE = {}   # quiz_id → [{id, name, points_possible, text}]
_QMETA_CACHE = {}        # quiz_id → {time_limit} (minutes; None = untimed) for the timeout penalty


_PDF_RASTER_MAX_PAGES = 12           # a drawing PDF is ~1p; cap runaway multi-page docs


def _rasterize_pdf(pdf_path, out_dir):
    """A PDF that is a scanned/photo drawing must be VIEWED (§0Z). Read opens PDFs
    natively, but ONLY up to 20MB — phone-photo PDFs (Nathan: ~70MB) blow past that.
    So rasterize each page to a downscaled PNG (pdftoppm) the AI can view. Returns the
    list of PNG paths (empty if pdftoppm is missing or fails — caller keeps the raw
    path as a fallback). NO information loss vs the drawing: it is already a raster."""
    if not shutil.which("pdftoppm"):
        return []
    prefix = os.path.join(out_dir, os.path.splitext(os.path.basename(pdf_path))[0] + "_p")
    try:
        subprocess.run(
            ["pdftoppm", "-png", "-scale-to", "1600", "-l", str(_PDF_RASTER_MAX_PAGES),
             pdf_path, prefix],
            check=True, capture_output=True, timeout=120)
    except (subprocess.SubprocessError, OSError):
        return []
    return sorted(
        os.path.join(out_dir, f) for f in os.listdir(out_dir)
        if f.startswith(os.path.basename(prefix)) and f.endswith(".png"))


def default_rubric(points_possible):
    return {"quiz": points_possible}


def _strip_html(s):
    return unescape(re.sub(r"<[^>]+>", " ", s or "")).strip()


# (GitHub Classroom invite→accepted_assignments + starter-instructor lookups removed
#  2026-06-25. org-hub: a quiz code-question's repo = the link the student pasted in
#  the answer (repo_resolve Step 1); instructor logins = gh_lib.instructor_logins(token).
#  No log fallback here — quiz answers paste the link inline; no link → no code_data.)


def _load_quiz_data(canvas_module, canvas_base, canvas_token, course_id, quiz_id, asmt_id,
                    download_dir=None):
    if quiz_id in _QSUBS_CACHE:
        return _QSUBS_CACHE[quiz_id], _QQUESTIONS_CACHE[quiz_id]
    # Quiz META (for the timeout penalty, GRADING.md Part B §2.4): the exam's time_limit
    # in minutes. None = untimed → no timeout penalty. Fetched once, cached with the quiz.
    _qmeta = canvas_module.get(canvas_base, canvas_token,
                               f"/courses/{course_id}/quizzes/{quiz_id}")
    _QMETA_CACHE[quiz_id] = {"time_limit": (_qmeta or {}).get("time_limit")
                             if isinstance(_qmeta, dict) else None}
    qs = canvas_module.get(canvas_base, canvas_token,
                           f"/courses/{course_id}/quizzes/{quiz_id}/questions?per_page=100")
    questions = []
    if isinstance(qs, list):
        for q in qs:
            questions.append({
                "id": q.get("id"),
                "name": q.get("question_name", ""),
                "points_possible": q.get("points_possible", 0),
                "text": _strip_html(q.get("question_text", "")),   # stripped instruction
                "text_html": q.get("question_text", ""),           # RAW instruction (links/imgs)
            })
    # ── Step 0: read each question's INSTRUCTION content ONCE (cached with the quiz) ──
    # The instruction may embed a Google Doc/Slides link, images, or formulas; Stage B
    # needs the FULL instruction (not stripped text) to extract the grading items +
    # per-item criteria (the rubric). Same read_content the student answers use.
    if download_dir:
        if not canvas_base:
            raise KeyError("canvas_base_url is required to resolve instruction links; "
                           "it comes from the course config, never from a default")
        _ihost = canvas_base.split("/api/")[0]
        for q in questions:
            _ihtml = re.sub(r'((?:src|href)=")(/(?:users|courses|files)/)',
                            lambda m: m.group(1) + _ihost + m.group(2), q.get("text_html", ""))
            _idir = os.path.join(download_dir, f"instr_q{q['id']}")
            q["instruction_content"], q["instruction_images"] = q["text"], []
            try:
                _ir = attachments.read_content(_ihtml, [], download_dir=_idir,
                                               uid=f"instr{q['id']}", allow_quality_failures=True)
                q["instruction_content"] = (_ir.get("all_text") or "").strip() or q["text"]
                if os.path.isdir(_idir):
                    for _f in sorted(os.listdir(_idir)):
                        _p = os.path.join(_idir, _f)
                        if not os.path.isfile(_p):
                            continue
                        with open(_p, "rb") as _fh:
                            _h = _fh.read(8)
                        if _h.startswith((b"\x89PNG", b"\xff\xd8\xff", b"GIF8")):
                            q["instruction_images"].append(_p)
            except Exception:  # noqa: BLE001 — instruction read is best-effort
                pass
    subs_by_uid = {}
    qsubs = canvas_module.get(canvas_base, canvas_token,
                              f"/courses/{course_id}/quizzes/{quiz_id}/submissions?per_page=100")
    qs_list = (qsubs or {}).get("quiz_submissions", []) if isinstance(qsubs, dict) else []
    for q in qs_list:
        uid = q.get("user_id")
        if uid is None:
            continue
        sub = canvas_module.get(canvas_base, canvas_token,
                                f"/courses/{course_id}/assignments/{asmt_id}/submissions/{uid}?include[]=submission_history",
                                paginate=False)
        hist = (sub or {}).get("submission_history") or []
        # Keep EVERY attempt (GRADING.md Part D §2.3 — grade each independently;
        # Canvas aggregates). submission_history is newest-first; sort oldest→newest.
        attempts = sorted(
            ({"attempt": h.get("attempt"),
              "submitted_at": h.get("submitted_at"),
              "submission_data": h.get("submission_data") or []}
             for h in hist),
            key=lambda a: (a.get("attempt") or 0))
        if not attempts:                      # no history → one empty attempt so grading still runs
            attempts = [{"attempt": q.get("attempt") or 1,
                         "submitted_at": None, "submission_data": []}]
        subs_by_uid[uid] = {
            "qsub_id": q.get("id"),
            "attempts_total": len(attempts),
            "attempts": attempts,
        }
    _QSUBS_CACHE[quiz_id] = subs_by_uid
    _QQUESTIONS_CACHE[quiz_id] = questions
    return subs_by_uid, questions


# Engine rubric keys the gh grader reads, and the published wording that maps to each.
# GRADING §0: the rubric the STUDENT SAW (the question's own table) outranks any grader
# default — so we parse it here rather than letting gh fall back to default_rubric().
_RUBRIC_KEY_PATTERNS = (
    ("link",   r"repo(?:sitory)?\s*link|link\s*submitted"),
    ("test",   r"autograder|test\s*result|program\s*(?:efficiency|result)"),
    ("elab",   r"elaborat|write[- ]?up|explanation"),
    ("commit", r"commit"),
)


def _parse_question_rubric(qtext, qpts):
    """Read the question's OWN published grading table → {engine_key: points}.

    A quiz question is an assignment (it publishes `Grading (50 points) | Item | Points`),
    so its table is the supreme rubric for that question. Returns None when the question
    publishes no table — then the grader's default legitimately applies.

    Deliberately NOT a hardcoded 5/25/10/10: those are THIS term's numbers, and a rubric
    is DATA. (A stale "5/50/30/15" from an old working log was nearly used here — the
    published table said 5/25/10/10.)
    """
    plain = _strip_html(qtext or "")
    m = re.search(r"Grading\s*\(?\s*(\d+)?\s*points?\)?(.{0,800}?)Total", plain, re.S | re.I)
    if not m:
        return None
    body = m.group(2)
    found = {}
    for key, pat in _RUBRIC_KEY_PATTERNS:
        # `pat` contains alternations — it MUST be wrapped in a non-capturing group before
        # appending the number capture. Without the wrap, `A|B` + `[^0-9]…(\d+)` parses as
        # `A` OR `B…(\d+)`, so a first-alternative match reaches no capture group and
        # group(1) is None (TypeError on float()). Caught on the first real Q52P1 run.
        mm = re.search(r"(?:" + pat + r")[^0-9]{0,40}?(\d+(?:\.\d+)?)", body, re.I)
        if mm and mm.group(1) is not None:
            found[key] = float(mm.group(1))
    if not found:
        return None
    # Sanity: the parsed items must add up to the question's points. If they don't, the
    # parse is wrong — return None and let the grader default apply rather than scoring
    # on a mis-read table (a silently wrong rubric is worse than an honest default).
    if qpts and abs(sum(found.values()) - float(qpts)) > 0.51:
        return None
    return found


def _grade_attempt(answers_data, questions, ctx, as_of=None, attempt=None):
    """Score ONE attempt's answers independently (GRADING.md Part D §2 — each
    attempt graded like a separate submission; Canvas aggregates). Called once per
    submission_history entry. `as_of` = this attempt's submission time → code
    questions are graded COMMIT-TIME (the repo as it stood at as_of: last autograder
    run + commits at/before as_of). Returns the per-attempt
    {raw, rows, needs_ai_essay, code_breakdown, needs_review, review_content, finalizable}."""
    uid = ctx["uid"]; user = ctx["user"]
    course = ctx["course"]; github_org = ctx["github_org"]; gh_token = ctx["gh_token"]
    download_dir = ctx["download_dir"]
    first_name = ctx["first_name"]; code = ctx["code"]
    asmt_name = ctx["asmt_name"]; pmax = ctx["pmax"]

    ans_by_id = {sd.get("question_id"): _strip_html(sd.get("text", ""))
                 for sd in answers_data}
    # RAW answer HTML per question — quiz answers (and their embedded screenshots)
    # live in submission_data, NOT submission['body'], so attachments must be
    # pointed at the answer HTML explicitly (Phase 2, 2026-06-02).
    ans_html_by_id = {sd.get("question_id"): (sd.get("text", "") or "")
                      for sd in answers_data}
    # file_upload-type answers carry their file only here (text is null).
    ans_attach_by_id = {sd.get("question_id"): (sd.get("attachment_ids") or [])
                        for sd in answers_data}
    rows = []
    total = 0.0
    needs_ai = []        # EVERY question → Stage B assigns the final score (rubric-driven)
    needs_review = []    # engine-side issues for the instructor (no autograder run, unread, etc.)
    code_breakdown = {}  # per-question sub-grader detail (when a repo is present)
    q_review = []        # (qname, review_content) per question → merged for core.py below
    finalizable = True   # #3: any engine-unread attachment flips this False (total withheld)

    for q in questions:
        qid = q["id"]
        qname = q.get("name") or f"Q{qid}"
        qpts = float(q.get("points_possible") or 0)
        qtext = q.get("text", "")
        answer = ans_by_id.get(qid, "")

        # Every question is a GENERAL grading unit — NO upfront code/essay split.
        #   1) extract attachments + 2) read student text (ALWAYS)
        #   3) run the sub-grader the CONTENT calls for (gh when a repo is present;
        #      hybrid-safe — a question may have a repo AND prose AND screenshots)
        #   4) hand everything + the rubric to Stage B, which assigns the FINAL score.
        # The engine gathers + runs deterministic sub-graders; the AI scores (rubric).

        # ── 1+2: extract attachments + read the student's text ──
        # attempt# in the dir name ISOLATES each attempt's downloads — without it,
        # attempt 1 and attempt 2 of the same question shared one folder and their
        # images cross-contaminated (Eliza: att1 showed att2's screenshots). Each
        # attempt is a separate quiz, so its files get a separate directory.
        essay_dir = os.path.join(download_dir, f"{uid}_a{attempt}_q{qid}_essay")
        raw_answer_html = ans_html_by_id.get(qid, "")
        if not course.get("canvas_base_url"):
            raise KeyError("canvas_base_url is required to resolve answer links; "
                           "it comes from the course config, never from a default")
        _host = course["canvas_base_url"].split("/api/")[0]
        _ans_html = re.sub(
            r'((?:src|href)=")(/(?:users|courses|files)/)',
            lambda m: m.group(1) + _host + m.group(2),
            raw_answer_html)
        # file_upload answers carry the file ONLY in attachment_ids (text null);
        # resolve each id → public_url (auth-free, token-bearing) so the shared
        # reader can fetch it. Fall back to /files/{id}/download (401s on <school> →
        # reads empty → flagged) when public_url can't be fetched.
        _cm, _cb, _ct = ctx.get("canvas_module"), ctx.get("canvas_base"), ctx.get("canvas_token")
        _file_atts = []
        for fid in ans_attach_by_id.get(qid, []):
            _furl = f"{_host}/files/{fid}/download?download_frd=1"
            if _cm:
                try:
                    _pu = _cm.get(_cb, _ct, f"/files/{fid}/public_url")
                    if isinstance(_pu, dict) and _pu.get("public_url"):
                        _furl = _pu["public_url"]
                except Exception:  # noqa: BLE001 — fall back to the plain URL
                    pass
            _file_atts.append({"url": _furl, "id": fid, "display_name": f"q{qid}_upload_{fid}"})
        attach_text = ""
        unread = []
        res = None
        try:
            # read_content takes raw (html, attachments) directly — no fake submission.
            # github_org → the reader extracts repo_link from the RAW answer HTML (href
            # attrs hold the URL). This is the SAME machinery the assignment/body path
            # uses; the quiz answer lives in submission_data, so we feed its HTML here
            # instead of submission["body"]. Do NOT re-extract from stripped text below.
            res = attachments.read_content(
                _ans_html, _file_atts, download_dir=essay_dir, uid=uid,
                github_org=github_org, allow_quality_failures=True)
            attach_text = res.get("all_text", "") or ""   # docx/pdf/etc. extracted text
            # ENGINE-unread = failed item that is NOT a student-quality failure
            # (private/encrypted etc.). Student-quality failures are acceptable
            # (AI gives that item 0); only an engine gap withholds the total.
            _qf = {q.get("source") for q in res.get("quality_failures", [])}
            unread = [it.get("source") for it in res.get("items", [])
                      if it.get("status") == "failed" and it.get("source") not in _qf]
        except attachments.AttachmentReadError as e:
            unread = [str(e)]
            needs_review.append(f"{qname}: attachment read failed — {e}")
        except Exception as e:  # noqa: BLE001 — attachment fetch is best-effort
            needs_review.append(f"{qname}: attachment read warning: {e}")
        # Downloaded files the AI must SEE. attachments caches files WITHOUT an
        # extension → detect by magic bytes; skip the manifest_*.json sidecar.
        #   answer_images = PNG/JPG/GIF (Read views inline)
        #   answer_docs   = PDF/other docs (Read opens PDFs page-by-page). A drawing
        #     submitted as a PDF (Nathan) was previously downloaded but NEVER surfaced
        #     because only image magic bytes were accepted → §0Z "view every drawing"
        #     silently violated. Surface the path so Stage B opens it (NO rasterize).
        answer_images = []
        answer_docs = []
        if os.path.isdir(essay_dir):
            for f in sorted(os.listdir(essay_dir)):
                p = os.path.join(essay_dir, f)
                if not os.path.isfile(p):
                    continue
                try:
                    with open(p, "rb") as _fh:
                        _head = _fh.read(8)
                except OSError:
                    continue
                if _head.startswith((b"\x89PNG", b"\xff\xd8\xff", b"GIF8")):
                    answer_images.append(p)
                elif _head.startswith(b"%PDF"):
                    answer_docs.append(p)
        # EVERY PDF answer is a drawing/scan that must be VIEWED (§0Z). Uniformly
        # rasterize its pages to downscaled PNGs and add them to answer_images so the
        # drawing ALWAYS lands where Stage B looks (no separate docs list to overlook,
        # no 20MB Read cap to trip on — Nathan's ~70MB phone PDF). The original PDF path
        # stays in answer_docs and the PDF's extracted text is in answer_attachment_text,
        # so rasterizing loses nothing. Overhead is ~1s/page — negligible.
        for _pdf in answer_docs:
            _pngs = _rasterize_pdf(_pdf, essay_dir)
            if _pngs:
                answer_images.extend(_pngs)
            else:
                needs_review.append(
                    f"{qname}: PDF answer {os.path.basename(_pdf)} could not be rasterized "
                    f"(pdftoppm missing/failed) — view {os.path.basename(_pdf)} manually")
        # "Loading placeholder" embeds = an upload that never resolved to a real file
        # (no /files/ URL) → cannot download. Flag so Stage B doesn't read a stuck
        # screenshot as "no answer".
        incomplete_uploads = sorted(set(re.findall(
            r'data-placeholder-for="([^"]+)"', raw_answer_html)))
        if incomplete_uploads and not answer_images and not answer_docs:
            needs_review.append(
                f"{qname}: {len(incomplete_uploads)} embedded upload(s) never finished "
                f"loading (no downloadable file) — {incomplete_uploads}")

        # ── 3: SUB-GRADER — DESIGNATED, never inferred (2026-07-28) ────────────────────
        # The type of a question is a property of the QUESTION, so it is designated by whoever
        # set the quiz up (`--q-grader`, or per question via `q_graders`), exactly as an
        # assignment's type is designated by `--grader`. Undesignated ⇒ `general`: gather the
        # answer and let Stage B score it. There is no sniffing step and no fallback chain.
        #
        # It used to read `if repo and gh_token: → gh, else: → essay`, i.e. the type came from
        # whether the STUDENT happened to paste a repo link. Two failures followed from that:
        # a code question whose author forgot the link silently became an ungraded essay, and
        # a non-git question type (NB, flowchart) had nowhere to go at all — while the module
        # docstring advertised "graded by its TYPE, read from the QUESTION TEXT". Reading the
        # question text would have been the same disease: `classify_assignment` was deleted the
        # same day for keyword-scanning a description and echoing our own starter boilerplate.
        q_grader_name = ctx.get("q_graders", {}).get(qname) or ctx.get("q_grader") or "general"
        code_data = None
        # repo_link from the READER (raw answer HTML → href preserved). A student who
        # submits the repo as a hyperlink (`<a href=...>GitHub Repo</a>`) is now caught;
        # extracting from the tag-stripped `answer` dropped the href (Laura M2QP3 bug).
        repo_link = res.get("repo_link") if isinstance(res, dict) else None
        repo, _src = repo_resolve.resolve(repo_link)
        # The pasted link stays PRIMARY, but it is no longer the ONLY source: `prepare()`
        # resolved this student's canonical org-hub repo once for the whole class, so a
        # missing link falls back to it instead of scoring 0 (GRADING Part B §0), and a link
        # that disagrees with the log is FLAGGED instead of silently trusted (§0 step 3).
        _canonical = ctx.get("prepared_repo")
        if not repo and _canonical:
            repo = _canonical
        elif repo and _canonical and repo.lower() != _canonical.lower():
            needs_review.append(
                f"{qname}: submitted repo `{repo}` ≠ canonical org-hub repo `{_canonical}` "
                f"— graded the submitted one; verify which is the student's real work")
        # (instructor-login exclusion now happens inside gh.grade — it resolves the
        #  closed write-set itself. quiz.py no longer fetches it per question.)
        # ── A QUESTION IS AN ASSIGNMENT (2026-07-28) ──────────────────────────────────
        # Wrap the question as a one-off `asmt` and call the SAME grader contract core.py
        # uses per student. quiz.py is the ITERATOR (attempt × question); the scoring lives
        # in the type grader — one implementation, never a second copy here.
        #
        # Until now this called gh's private `_fetch_repo_data` (the collector) and scored
        # nothing, which is why: (a) questions came back unscored, and (b) no
        # `review_content` was produced → core.py wrote an empty ground_truth → view_gate
        # emitted zero evidence files → the view-gate could not enforce reading a quiz
        # answer at all. Going through grade() fixes all of it in one move, and any future
        # NB / flowchart question routes to ITS grader with no change here.
        #
        # RUBRIC: the question publishes its own table (GRADING §0 — the instructions'
        # rubric is supreme). Parsed from the question text; a stated-but-unparseable
        # rubric raises rather than silently falling back to a grader default.
        q_rubric = _parse_question_rubric(qtext, qpts)
        q_asmt = {
            "code": f"{code}-{qname}",
            "name": qname,
            "points_possible": qpts,
            "due_at": ctx.get("due_at"),
            "rubric": [(k, v) for k, v in (q_rubric or {}).items()],
            "description": qtext,
            # CONTEXT the type grader needs — it owns the tier logic, we only say WHICH:
            "is_quiz": True,                      # → HOURS tiers, no grace (Part D §2.4)
            "time_limit": ctx.get("time_limit"),  # → exam timeout on repo→passing-run
            # NO quiz_id — a question is never itself a quiz (blocks any recursion).
        }
        # `submitted_at` = THIS attempt's time, so gh._decide_as_of reads the repo
        # COMMIT-TIME for this attempt (Part D §2.4) exactly as before.
        q_sub = {"body": raw_answer_html, "user": user, "submitted_at": as_of,
                 "initial_submitted_at": as_of}

        if q_grader_name != "general":
            # A DESIGNATED grader runs even when its material is missing — it reports the gap
            # itself (gh: "no repo resolved for this submission"). Skipping the call because a
            # repo link is absent is the fallback this step exists to remove: it turned a code
            # question into an ungraded essay and said nothing.
            try:
                r = _sub_grader(q_grader_name).grade(
                    submission=q_sub, asmt=q_asmt, course=course,
                    repo=repo, download_dir=essay_dir, gh_token=gh_token,
                    student_login=None,
                    # Hand over the ALREADY-READ answer content so the grader does not
                    # re-read it. `q_sub` is a shim carrying only body/user/timestamps —
                    # it has no `attachments`, so a re-read would count the HTML's images
                    # as expected but find none to fetch → AttachmentReadError. Read once.
                    att_result=res,
                )
                # review_content per question → merged at attempt level below → core.py
                # ground_truth → evidence file → the view-gate finally covers quiz answers.
                q_review.append((qname, r.get("review_content") or {}))
                # ── code_data — per-question REFERENCE for Stage B, not engine input ──────
                # Nothing in the engine reads it (core.py / report_generator / the poster all
                # ignore it); it rides in grades.json for the AI. That claim is NOT maintained
                # here in prose — a comment asserting a fact becomes a lie the day the fact
                # changes, which is the exact failure this file was rebuilt to remove (its own
                # docstring once described a dispatcher that did not exist).
                # `selftest.reference_only_fields()` re-checks it every run and FAILS if
                # anything outside this module starts reading it.
                code_data = {
                    # Named here: the CONTRACT fields every grader emits, plus what this tier
                    # itself knows (which grader ran, which repo it was pointed at).
                    "grader": q_grader_name,
                    "repo": repo,
                    "engine_score": r.get("raw"),
                    "scores": r.get("scores") or {},
                    "rubric_items": r.get("rubric_items") or [],
                    # Everything else the sub-grader returned, VERBATIM and unnamed. This dict
                    # used to spell out 13 gh-only keys (tp, mp, commit_inspect, run_history,
                    # ag_penalty, authenticity, commit_flags, due/timeout_frac,
                    # recommit_after_pass, repo/run_created_at) — an iterator that is supposed
                    # to work with ANY sub-grader, hard-coded to one grader's vocabulary. A
                    # notebook question produced a dict of Nones with nothing of its own in it.
                    # Passing the rest through means gh keeps every field it had AND nb/jshell
                    # get theirs, with no list here to maintain.
                    "detail": {k: v for k, v in r.items() if k not in _CONSUMED_KEYS},
                }
                code_breakdown[qname] = code_data
                # The sub-grader WROTE these (gh._engine_notes) — this tier only tags them with
                # the question they came from. Composing them here was the layering bug: the
                # iterator held interpretation logic, and the assignment path, having no
                # iterator, showed none of it.
                for _n in (r.get("needs_review") or []):
                    needs_review.append(f"{qname}: {_n}")
            except Exception as e:  # noqa: BLE001
                # Name the grader that actually ran — this used to say "gh" unconditionally,
                # which would misattribute an nb/jshell question's failure once the sub-grader
                # became designated rather than always gh.
                needs_review.append(
                    f"{qname}: sub-grader '{q_grader_name}' failed (repo={repo}) — {e}")

        # ── #3: engine-unread attachment → withhold this attempt's TOTAL ──
        # (keep the gathered parts; raise a flag — never silently score over a hole)
        if unread:
            finalizable = False
            needs_review.append(
                f"{qname}: {len(unread)} attachment(s) the engine could not read "
                f"→ total not finalizable until resolved")

        # ── 4: hand text + attachments + sub-grader data + rubric to Stage B ──
        rows.append((qname, qpts, None,
                     {"why": "Stage B (AI) assigns the final score from the rubric using the "
                             "gathered text/attachments"
                             + (" + autograder/commit data" if code_data else ""),
                      "how_to_fix": ""}))
        needs_ai.append({
            "qname": qname, "qid": qid, "points_possible": qpts,
            "question_text": qtext[:1200],          # stripped instruction (quick ref)
            # FULL instruction (step 0) — read_content of the question incl. any linked
            # Google Doc/Slides text + instruction images. Stage B extracts the grading
            # items + per-item criteria (the rubric) from THIS, then scores.
            "instruction_content": q.get("instruction_content", qtext),
            "instruction_images": q.get("instruction_images", []),
            "answer_text": answer,
            # RAW answer HTML (tags intact) — Stage B inspects it for paste artifacts:
            # inline code tokens rendered as color/font <span>s = pasted from a rendered
            # markdown source (≈ AI chat UI), which direct Canvas typing never produces.
            # Signal only — NOT a verdict; combine with commit↔narrative + server-time.
            "answer_raw_html": raw_answer_html,
            "answer_images": answer_images,
            "answer_docs": answer_docs,             # PDF/doc paths — Stage B opens via Read (§0Z)
            "answer_attachment_text": attach_text,
            "incomplete_uploads": incomplete_uploads,
            "code_data": code_data,                 # gh sub-grader result, or None
            "unread": unread,
        })

    # raw is a 0 BASELINE — every question now goes to Stage B, which assigns the
    # final per-question score from the rubric (engine gathers + runs deterministic
    # sub-graders; AI scores). `finalizable=False` means an engine-unread attachment
    # exists → the total must NOT be posted until resolved (flag in needs_review).
    raw = round(total, 2)
    # ── review_content (2026-07-28) — THE MISSING LINK ────────────────────────────────
    # core.py:806 builds <code>_ground_truth.json from review_content.commit_diffs +
    # .elaboration, and view_gate explodes that into <code>_evidence/<uid>.txt so the
    # gate can require the AI to have READ each student's own work before posting.
    # quiz.py never returned review_content, so ground_truth was an empty shell (871 B),
    # evidence was 0 files, and quiz text answers were exempt from the view-gate.
    # Merge the per-question content the type graders produced, tagged by question.
    _all_diffs, _elab_parts = [], []
    for _qn, _rc in q_review:
        for _cd in (_rc.get("commit_diffs") or []):
            _all_diffs.append({**_cd, "question": _qn})
        _et = (_rc.get("elaboration") or "").strip()
        if _et:
            _elab_parts.append(f"### {_qn}\n{_et}")
    # Questions with no repo still have a written answer — that IS the gradeable evidence.
    for _na in needs_ai:
        if not any(_na["qname"] == _qn for _qn, _ in q_review):
            _at = (_na.get("answer_text") or "").strip()
            if _at:
                _elab_parts.append(f"### {_na['qname']}\n{_at}")
    review_content = {
        "commit_diffs": _all_diffs,
        "elaboration": "\n\n".join(_elab_parts),
        "per_question": {qn: rc for qn, rc in q_review},
    }

    return {"raw": raw, "rows": rows,
            "needs_ai_essay": needs_ai, "code_breakdown": code_breakdown,
            "needs_review": needs_review,
            "review_content": review_content,
            "finalizable": finalizable}


def grade(*, submission, asmt, course, repo=None,
          download_dir=None, browser_fetcher=None,
          canvas_module=None, canvas_base=None, canvas_token=None, course_id=None,
          gh_token=None, **_):
    # `repo` = this student's canonical org-hub repo, resolved once by prepare() and handed
    # down by core.py's uniform contract. It was previously swallowed by **_ , so a code
    # question could only ever see the link pasted in its own answer box.
    user = submission.get("user") or {}
    uid = user.get("id")
    first_name = (user.get("name") or "Student").split()[0]
    code = asmt["code"]
    asmt_name = asmt.get("name", "")
    pmax = asmt["points_possible"]
    asmt_id = asmt.get("asmt_id")
    quiz_id = asmt.get("quiz_id")
    github_org = course.get("github_org", "")

    if not quiz_id:
        body = submission.get("body") or ""
        m = re.search(r"quiz:\s*(\d+)", body)
        if m:
            quiz_id = int(m.group(1))

    if not (canvas_module and canvas_base and canvas_token and course_id and quiz_id and asmt_id):
        return {"scores": {"quiz": 0}, "raw": 0, "posted": 0, "stub": True,
                "needs_review": ["quiz grader missing plumbing "
                                 "(canvas_module/quiz_id/asmt_id/course_id) — ensure asmt has "
                                 "quiz_id and core.py passes the canvas kwargs"]}

    subs_by_uid, questions = _load_quiz_data(canvas_module, canvas_base, canvas_token,
                                             course_id, quiz_id, asmt_id,
                                             download_dir=download_dir)
    student = subs_by_uid.get(uid)
    if not student:
        # NOTHING TO GRADE — the student never attempted the quiz. A real 0, not a STOP and not
        # a failure to gather, so it is flagged as its own shape (lib/contract.py): there are
        # legitimately no attempts and no evidence, and without the flag the contract reads
        # this as three declared fields being dropped.
        return {"scores": {"quiz": 0}, "raw": 0, "posted": 0, "nothing_to_grade": True,
                "needs_review": ["no quiz submission found for this student — verify the "
                                 "student attempted the quiz"]}

    # Grade EVERY attempt independently (GRADING.md Part D §2). The per-question
    # scoring is in _grade_attempt(); here we just loop the attempts and collect.
    # Repo per code question = the link pasted in that answer, else this student's canonical
    # org-hub repo from prepare() (`prepared_repo`). No name→login / roster lookup.
    ctx = {"uid": uid, "user": user, "course": course,
           "prepared_repo": repo,          # canonical org-hub repo (prepare(); None if none)
           "github_org": github_org, "gh_token": gh_token, "download_dir": download_dir,
           "first_name": first_name, "code": code,
           "asmt_name": asmt_name, "pmax": pmax, "due_at": asmt.get("due_at"),
           "time_limit": _QMETA_CACHE.get(quiz_id, {}).get("time_limit"),
           # SUB-GRADER DESIGNATION — a quiz-wide default plus per-question exceptions, both
           # supplied by the caller. A mixed quiz (MID1 = algorithm essay + program code per
           # problem) needs the per-question map; a uniform one needs only the default. The
           # engine never guesses either; unset ⇒ `general` (gather, Stage B scores).
           "q_grader": asmt.get("q_grader"),
           "q_graders": asmt.get("q_graders") or {},
           "canvas_module": canvas_module, "canvas_base": canvas_base,
           "canvas_token": canvas_token}

    graded_attempts = []
    for att in (student.get("attempts") or []):
        r = _grade_attempt(att.get("submission_data") or [], questions, ctx,
                           as_of=att.get("submitted_at"), attempt=att.get("attempt"))
        r["attempt"] = att.get("attempt")
        r["submitted_at"] = att.get("submitted_at")
        graded_attempts.append(r)

    # AUTHORITATIVE per-attempt data is out["attempts"]. The grader grades EVERY attempt
    # equally and NEVER decides which one "counts" — report_generator emits one record per
    # attempt, the poster writes each attempt's scores, and Canvas (keep_highest/latest/
    # average, the quiz's own scoring_policy) does the aggregation. The engine picks no
    # winner.
    #
    # The remaining top-level fields (raw/scores/comment/…) are a DISPLAY-ONLY convenience
    # for the single-attempt case and for the summary table's one row per student; they are
    # NOT the grade and are never posted for a multi-attempt student. For multi-attempt we
    # populate them from the highest-attempt# entry purely so the summary row renders — the
    # real breakdown is in the per-attempt section. `multi_attempt` flags this so no
    # consumer mistakes the representative row for the student's grade.
    repr_att = max(graded_attempts, key=lambda a: (a.get("attempt") or 0), default=None)
    # ── EVIDENCE / ENFORCEMENT fields span EVERY attempt, never the representative one ──
    # `review_content` (→ core.py ground_truth → evidence file → view-gate) and
    # `needs_review` (→ Section 0 engine-issue list) are NOT display fields, even though
    # they sat in the display block until 2026-07-28. Taking them from repr_att means the
    # attempts that are not representative are never surfaced: Diego Alcala (Q52P1) graded
    # fine on attempt 1 but attempt 2 — the higher number, hence representative — had no
    # repo data, so his review_content came back empty, ground_truth had no entry, NO
    # evidence file was written, and the view-gate let him through unread. That is the
    # exact hole view_gate's docstring names ("a copied score with the 2nd attempt never
    # read"), arriving from the other side. Merge across all attempts so every attempt the
    # engine graded must be READ before it can be posted.
    _m_diffs, _m_elab, _m_perq, _m_review = [], [], {}, []
    for _a in graded_attempts:
        _an = _a.get("attempt") or 0
        _rc = _a.get("review_content") or {}
        for _cd in (_rc.get("commit_diffs") or []):
            _m_diffs.append({**_cd, "attempt": _an})
        _et = (_rc.get("elaboration") or "").strip()
        if _et:
            _m_elab.append(f"## attempt {_an}\n{_et}")
        for _qn, _qrc in (_rc.get("per_question") or {}).items():
            _m_perq[f"att{_an}:{_qn}"] = _qrc
        for _nr in (_a.get("needs_review") or []):
            _m_review.append(f"attempt {_an}: {_nr}")
    out = {
        "scores": {q["name"]: 0 for q in questions},
        "raw": repr_att["raw"] if repr_att else 0.0,
        "posted": repr_att["raw"] if repr_att else 0.0,
        "rubric_items": [(r[0], r[1]) for r in repr_att["rows"]] if repr_att else [],
        "needs_ai_essay": repr_att["needs_ai_essay"] if repr_att else [],
        "code_breakdown": repr_att["code_breakdown"] if repr_att else {},
        # Must reach core.py: it feeds ground_truth → evidence → view-gate (2026-07-28).
        # Merged over ALL attempts (see the note above) — never the representative one.
        "review_content": {"commit_diffs": _m_diffs,
                           "elaboration": "\n\n".join(_m_elab),
                           "per_question": _m_perq},
        "attempts_total": student.get("attempts_total"),
        # THE QUESTION ROSTER, read LIVE from Canvas at the top of this run. `report_generator`
        # enforces a QUIZ CONTRACT — every rubric row must name its `question_id`, because the
        # post writes to a question, not to an item name — and it says in the same breath that
        # "Stage A must stamp `question_id`". Stage A never did: the id lived only in this
        # module's local `questions` list and died with the call, so `scaffold` built the rubric
        # by re-parsing item names out of the report markdown and the render then refused every
        # quiz it had itself prepared. Carried out so core.py can stamp it on the record.
        "questions": [{"id": q.get("id"), "name": q.get("name"),
                       "points_possible": q.get("points_possible")} for q in questions],
        "attempts": graded_attempts,         # AUTHORITATIVE per-attempt results (Part D §2.3)
        "multi_attempt": len(graded_attempts) > 1,
        "engine_partial": bool(repr_att and repr_att["needs_ai_essay"]),
    }
    if _m_review:
        out["needs_review"] = _m_review
    return out
