"""git_page — GLOBAL git-program page builder (config-driven).

The ONE builder for a git/program assignment's instruction gdoc + Canvas page. A course's LOCAL
conductor (`git-assignment`) calls this; it reads the course's coordinates through the ONE reader
`course_config.load(slug)` (course_id, base, token_env, github_org, output_dir, pages_folder,
request_form) — never hardcode them, and never open a config json here.

Follows `assignment-page-builder/program-assignment-format.md` (pinned sections + [2] function-manual
shape + backtick inline code). Uses the skeleton `canvas_core.assignment_page_builder.make_page`, which
returns `out["html"]` (summary + doc embed + slide embed LAST) and pushes ONLY when push=True.

RENDERING IS THE SKELETON'S — this file owns none of it. `ic` (backticks), `rich_ul`/`rich_ol`/
`rich_table`, `link`, `pre`, `callout`, `slide_embed` all come from `skel`. This builder only decides
WHAT goes on the page and in WHAT ORDER, plus the git-only parts (request URL, autograder table,
auto/elab/commit/link rubric, function-vs-I/O mode). If a shape is missing, ADD IT TO THE SKELETON —
never re-implement it here (a private renderer copy here is what left NB pages unable to render
backticks at all; removed 2026-07-17).

Delivery:
  · homework      -> git_page(..., push=True)               -> Canvas assignment
  · quiz question -> html = git_page(..., push=False)["html"] -> quiz-builder wraps it as an essay

asmt — has TWO modes, keyed on whether `prototype` is present:
  COMMON (both modes):
    code, title, quiz_name?, assignment_id?, request_id?, slide_embed_url?,
    gist,                              # [1] one line (rendered as the "Overview" section)
    spec: [(label, desc)]?,            # [3] "What each does" (multi-case)
    algorithm: [str, ...]?,            # [4] pseudo/approach bullets
    examples: str?,                    # [5] a call->return code block
    restrictions: [str, ...],          # [6] -> yellow bold highlight box (outline bullets)
    elaboration: [str, ...]?,          # what the student MUST write (graded) -> navy box; also a gdoc section
    test_items: [{runner, max, checks}]# [7] autograder table
    rubric_rows: [[label, pts, criteria]]?  # replaces the 4 standard rubric rows entirely, for an
                                       #   assignment whose split is not link/auto/elab/commit (a
                                       #   project graded on design structure, an exam with no
                                       #   repo-link row). MUST sum to `points` or git_page STOPs.
                                       #   Drives BOTH the Grading table and the Submit list.
    submit_items: [str]?               # overrides the Submit list when what is handed in is not
                                       #   one line per rubric row (e.g. a project where two of the
                                       #   four rows are read off the repo, not submitted).
    local_test: str | [str, ...]?,     # the BASELINE "run the tests locally" line(s) -> tip box.
                                       #   e.g. '`make test`' (Catch2) / '`pytest -m T1`' (pytest).
                                       #   Source of truth = that repo's classroom.yml — NEVER inferred from
                                       #   language/framework (a Catch2 assignment may still need stdin, a
                                       #   run.sh, or a data file). Per-assignment EXCEPTIONS are authored
                                       #   onto the page by the AI, not encoded here. Omit -> no tip block.
  FUNCTION mode (prototype PRESENT — Ch6+/functions; e.g. <course>):
    prototype,                         # the def/signature line, e.g. "int power(int b,int e)"
    params: [(name, type, desc)],      # Parameters (manual)
    returns: str, intuition: str       # -> renders the "The function / Parameters / Returns" section
  I/O mode (prototype ABSENT — Ch2-5 stdin->stdout; the <course> default):
    input, output,                     # str = one paragraph, OR list = outline bullets
                                       #   (e.g. one bullet PER PROGRAM in a two-program assignment)
    expected                           # a code block: sample keyboard input -> screen output
                                       # -> renders "Input / Output / Expected Output" (no "The function")
  Canvas-page section order: title -> Overview(gist) -> Request your repository (near the TOP) ->
    I/O-or-function -> spec -> Restrictions -> Elaboration -> Test items -> Grading -> Submit.
  points=50 with the default homework weights -> rubric 25/10/10/5 (a programming-quiz question).

"""
import json
import os
import sys
import html as _h

from ..richdoc import build  # gws-richdoc block builders
from . import page_builder as skel
from .. import course_config  # noqa: E402  # THE config reader (single source; never re-implement)

# Default rubric weights (homework, GRADING.md Part B). A quiz git-program question passes the
# QUIZ_WEIGHTS instead; a course may set its own via a `Grading override:` line in its CLAUDE.md
# (GRADING.md Q4) — read the in-force rubric, never assume these numbers.
HOMEWORK_WEIGHTS = {"auto": 50, "elab": 20, "commit": 20, "link": 10}

# Named rubric levels. A caller passes one of these as `rubric_weights` instead of writing a dict,
# so a course/assignment type is chosen by NAME. The in-force split still comes from GRADING.md or
# the course's `Grading override:` document — these are the shapes, not the authority.
RUBRIC_LEVELS = {
    "L0":  {"auto": 35, "elab": 40, "commit": 20, "link": 5},   # exam — elaboration-heaviest
    "L1":  {"auto": 40, "elab": 35, "commit": 20, "link": 5},   # exam
    "L10": {"auto": 50, "elab": 30, "commit": 15, "link": 5},   # elaboration-weighted homework
}

# The autograder table's footnote: the graders sum to 100, which is then scaled into the rubric row.
AUTOGRADER_NOTE = "The autograder reports 100; that is your Autograder test result rubric score."

# `input_spec` — ONLY for a program matched against fixed STRING inputs (spelling/case can differ).
# Omit it for number-only input: an exact-match warning is meaningless for integers.
INPUT_WARN = ("The autograder sends ONLY these inputs. Your conditions must match them EXACTLY — any "
              "other spelling or case makes your if-condition FALSE, so your program FAILS:")

# Elaboration: the same 3-part prompt on every assignment; only the edge list is per-problem.
ELAB_INTRO = ("Write this in your submission (NOT inside the repo). Graded strictly. Answer ALL three "
              "parts; a vague answer, or \"no errors\", earns 0.")


def _request_url(cfg, request_id, code=None):
    """ONE VALUE, FOUR PLACES. `request_id` == `code` == the assignment slot in the student repo
    name == the org-hub config.json key:

        <course>-<term>-A612-<student-login>  ·  <COURSE>A612Starter  ·  config key "A612"

    `request_id` stays available for the ~1% assignment whose request key genuinely differs from
    the grading code — but it is NOT a second name for the same thing, and it must never diverge
    SILENTLY. On 2026-08-04 all 14 <course> chapter-5 pages shipped `assignment=5-6`-style TITLES
    while the register held `A56`. Nothing caught it: the student request form is a dropdown
    generated from config.json, so students just picked the right entry and the broken pre-fill
    went unnoticed for an entire chapter. A divergence must be DECLARED, never defaulted into.
    """
    if code is not None and request_id != code:
        raise SystemExit(
            "STOP — request_id %r != code %r.\n"
            "  These name the same thing: the assignment slot in the student repo name, the\n"
            "  starter repo, and the org-hub config.json key. A page built with the other one\n"
            "  pre-fills a request the hub cannot honour.\n"
            "  If this assignment really needs a different request key, pass request_id AND\n"
            "  confirm it is a key in <org>/classroom/config.json first."
            % (request_id, code))
    return ("https://github.com/%s/classroom/issues/new?template=%s&assignment=%s"
            % (cfg["github_org"], cfg.get("request_form", "request.yml"), request_id))


# Inline code (`backticks`), lists, boxes and links all come from the SKELETON — this builder owns
# NO rendering of its own. (Until 2026-07-17 a private _CODESPAN/_ic/_ul/_restrict/_elab lived here;
# that copy is why NB pages could not render backticks at all — the renderer was locked inside the
# git builder. Skeleton renders; builders assemble. Do not re-add a copy.)
_ic = skel.ic
_ul = skel.rich_ul


def _restrict(items):
    """Restrictions — the skeleton's yellow/bold callout, so forbidden functions stand out."""
    return skel.callout(items or ["(none)"], kind="warn")


def _elab_parts(edges):
    """The graded 3-part elaboration prompt. `edges` = this problem's edge cases (list of str)."""
    e = "; ".join(edges) if edges else "the edge cases for this problem"
    return [
        ("1. Algorithm — your design, in words",
         ["Explain your approach: the key idea and the steps. Describe the DESIGN, not a line-by-line "
          "reading of the code."]),
        ("2. Correctness — show it works for EVERY input",
         ["State WHY your logic is right (the reasoning / the invariant).",
          "Walk through at least one worked example, step by step.",
          "Address the edge cases: %s." % e,
          "\"It compiled and the autograder was green\" is NOT a proof."]),
        ("3. Errors, debugging, and the commits that fixed them",
         ["Each error -> its commit: what it was, the cause, the fix, and the commit (message/hash) "
          "that fixed it. Your error story is cross-checked against your commit timeline.",
          "Runtime errors — be specific: what the program did, how you traced the cause, how you fixed it.",
          "The hardest debugging: which part cost the most time — the symptom, what you tried, what worked.",
          "Vague (\"it was hard\") = 0. Name the real bug, the real symptom, the real fix, the real commit.",
          "No errors? Then show your clean process (walk your commit-by-commit progression) — an empty "
          "\"no errors\" = 0."]),
    ]


def _elab(items):
    """Elaboration requirements. A LIST of strings -> the navy callout as given (the older shape).
    `elab_edges` (a list of this problem's edge cases) -> the standard graded 3-part prompt."""
    if not items:
        return ""
    return skel.callout(items, kind="note",
                        title="Your written elaboration is graded — include ALL of the following:")


def _elab_standard(edges):
    """The 3-part elaboration, rendered for Canvas. Same text the gdoc gets, so they cannot drift."""
    body = "".join("<p style='margin:8px 0 2px;'><b>%s</b></p>%s" % (skel.ic(h), skel.rich_ul(subs))
                   for h, subs in _elab_parts(edges))
    return "<p>%s</p>%s" % (skel.ic(ELAB_INTRO), body)


def _pts(points, w):
    return {k: round(points * w[k] / 100) for k in ("auto", "elab", "commit", "link")}


def _rubric_rows(points, w, override=None):
    """Returns (table rows incl. Total, the Submit-section lines).

    `override` — `asmt["rubric_rows"]`, a list of `[label, pts, criteria]`. For an assignment whose
    rubric is not the four standard rows (a project graded on design structure, an exam with no
    repo-link row). It must still SUM to `points`: the reason weights exist is that a page whose
    rubric disagrees with `points_possible` is a silent grading bug, and an explicit list has to
    clear the same bar rather than bypass it.
    """
    if override:
        rows = [(str(lb), int(pt), str(cr)) for lb, pt, cr in override]
        tot = sum(pt for _lb, pt, _cr in rows)
        if tot != points:
            raise SystemExit(
                "STOP — asmt['rubric_rows'] sums to %d but points=%d.\n"
                "  rows: %s\n"
                "  The rubric printed on the page IS the rubric the grader reads (GRADING §0), so it "
                "must equal points_possible. Fix the rows or fix --points."
                % (tot, points, ", ".join("%s=%d" % (lb, pt) for lb, pt, _c in rows)))
        submit = ["%s (%d) — %s" % (lb, pt, cr) for lb, pt, cr in rows]
        return rows + [("Total", points, "")], submit
    p = _pts(points, w)
    return [
        ("Repo link submitted", p["link"], "Link to your repository."),
        ("Autograder test result", p["auto"], "Your autograder score /100, scaled to this weight."),
        ("Elaboration", p["elab"], "Detailed algorithm, correctness for all inputs, and errors/fixes — write everything in the Elaboration section."),
        ("Commit quality", p["commit"], "Genuine design -> implement -> debug -> pass commit history (not one all-at-once commit)."),
        ("Total", points, ""),
    ], [
        "Repo link (%d) — your repository link." % p["link"],
        "Autograder result (%d) — score or green-check screenshot." % p["auto"],
        "Elaboration (%d) — algorithm + correctness for all inputs, then errors and fixes." % p["elab"],
        "Commit history link (%d) — your commit timing and count." % p["commit"],
    ]


# ── the instruction gdoc (program-assignment-format [1]..[7]) ─────────────────────────────────
def _doc_blocks(asmt, points, w, cfg):
    code = asmt["code"]
    req = _request_url(cfg, asmt.get("request_id", code), code)
    n = [0]

    def sec(t):
        n[0] += 1
        return build.section_box("[ %d ] %s" % (n[0], t))

    blocks = [
        build.banner(asmt["title"], "GitHub Program Assignment",
                     "Work in your repo, commit as you go, push for the green check."),
        sec("What you write"),
        build.body(asmt.get("gist", "")),
    ]
    if asmt.get("overview"):             # a fuller framing paragraph under the one-line gist
        blocks.append(build.body(asmt["overview"]))
    if asmt.get("signature"):            # the exact prototype the student implements — make it stand out
        blocks += [sec("\U0001F527 Method to implement"), build.code(asmt["signature"])]
    if asmt.get("concept"):              # one concept that needs room, as its OWN section
        c = asmt["concept"]
        blocks += [sec(c["title"])]
        for st in c.get("steps", []):
            if st.get("label"):
                blocks.append(build.body("**%s**" % st["label"]))
            if st.get("body"):
                blocks.append(build.body(st["body"]))
            if st.get("example"):
                blocks.append(build.code(st["example"]))
    if asmt.get("what_to_complete"):
        blocks += [sec("What to complete"), build.bullets(asmt["what_to_complete"])]
    if asmt.get("input_spec"):           # the exact strings the autograder sends (string-matching only)
        blocks.append(build.warning([INPUT_WARN] + list(asmt["input_spec"])))
    if asmt.get("prototype"):            # FUNCTION mode (Ch6+ / <course>): student writes a named function
        blocks += [
            sec("The function"),
            build.code(asmt["prototype"]),
            build.body("Parameters"),
            build.bullets(["`%s` (`%s`) - %s" % (nm, ty, ds) for nm, ty, ds in asmt.get("params", [])]),
            build.body("Returns"),
            build.bullets([asmt.get("returns", "")]),
            build.body(asmt.get("intuition", "")),
        ]
    elif asmt.get("io_block") or asmt.get("io_lines") or asmt.get("io_table"):
        # CONTRACT mode: Parameter/Return/Rules/Example as ONE aligned code snippet. Preferred over a
        # prose paragraph, which renders as an unreadable run-on line for a list or a mapping:
        #   io_block (aligned snippet)  >  io_lines (bullets)  >  io (plain paragraph)
        blocks.append(sec("Input / Output"))
        if asmt.get("io_block"):
            blocks.append(build.code(asmt["io_block"], lang="text"))
        elif asmt.get("io_lines"):
            blocks.append(build.bullets(asmt["io_lines"]))
        if asmt.get("io_table"):
            blocks.append(build.table(asmt["io_table"]["headers"], asmt["io_table"]["rows"]))
        if asmt.get("expected"):
            blocks += [sec("Expected Output"), build.code(asmt["expected"])]
    else:                               # I/O mode (Ch2-5 stdin->stdout): the program reads input and prints
        # input/output may be a STRING (one paragraph) OR a LIST (outline bullets, one line each -- e.g.
        # one bullet per program in a two-program assignment). A list keeps each program on its own line.
        def _iob(v):
            return build.bullets(list(v)) if isinstance(v, (list, tuple)) else build.body(v or "")
        blocks += [
            sec("Input"), _iob(asmt.get("input")),
            sec("Output"), _iob(asmt.get("output")),
        ]
        if asmt.get("expected"):
            blocks += [sec("Expected Output"), build.code(asmt["expected"])]
    if asmt.get("spec"):   # [3] only for a multi-case/criteria function; single-behavior funcs skip it
        blocks += [sec("What each does"),
                   build.bullets(["`%s` -> %s" % (lb, ds) for lb, ds in asmt["spec"]])]
    if asmt.get("algorithm"):
        blocks += [sec("Algorithm"),
                   build.bullets(asmt["algorithm"]) if isinstance(asmt["algorithm"], (list, tuple))
                   else build.code(asmt["algorithm"])]
    if asmt.get("examples"):
        blocks += [sec("Examples   (a call and its returned value - not keyboard input)"),
                   build.code(asmt["examples"])]
    blocks += [
        sec("Restrictions"),
        build.warning(asmt.get("restrictions", []) or ["(none)"]),
    ]
    if asmt.get("guide_steps"):          # the walk-through: one labelled step at a time
        blocks.append(sec("Step by step"))
        for st in asmt["guide_steps"]:
            if st.get("label"):
                blocks.append(build.body("**%s**" % st["label"]))
            if st.get("body"):
                blocks.append(build.body(st["body"]))
            if st.get("example"):
                blocks.append(build.code(st["example"]))
    if asmt.get("elab_edges") is not None:
        blocks.append(sec("Elaboration you must write (graded)"))
        blocks.append(build.body(ELAB_INTRO))
        for head, subs in _elab_parts(asmt["elab_edges"]):
            blocks += [build.body("**%s**" % head), build.bullets(subs)]
    elif asmt.get("elaboration"):
        blocks += [sec("Elaboration you must write (graded)"), build.bullets(asmt["elaboration"])]
    blocks += [
        sec("How your work is tested"),
    ]
    rows = [[it["runner"], str(it["max"]), it["checks"]] for it in asmt.get("test_items", [])]
    if rows:
        blocks.append(build.table(["Test Runner Name", "Max Score", "What it checks"], rows))
        blocks.append(build.body(AUTOGRADER_NOTE))
    # The tip BLOCK is global (a git assignment always has a way to run its tests); the COMMAND is not.
    # `local_test` is the course's baseline line(s), e.g. `make test` (Catch2) or `pytest -m T1`. Anything
    # beyond the baseline — this assignment needs stdin, run.sh, a data file — is per-assignment and is
    # authored onto the page by the AI, never guessed here. The repo's classroom.yml is the only authority
    # for what the graders actually run, so this builder must not infer it from language/framework.
    # (Until 2026-07-20 this line hardcoded `pytest`, which happened to fit <course> and <course> Ch2-5 and was
    # wrong for <course> Ch6+ (Catch2) and for <course> (Java) — which forked this whole builder to escape it.)
    if asmt.get("local_test"):
        lt = asmt["local_test"]
        blocks += [build.tip(list(lt) if isinstance(lt, (list, tuple)) else [lt])]
    # NOTE: Request / Grading / Submit are CANVAS-PAGE level (they live in _canvas_summary), NOT in the
    # instruction gdoc — program-assignment-format.md pins the gdoc to [1]..[6]/tests only. Keeping them
    # out of the gdoc avoids double Request/Rubric/Submit (the gdoc is embedded IN the Canvas page).
    return blocks


# ── the Canvas page summary (concise; the gdoc holds the detail) ──────────────────────────────
def _canvas_summary(asmt, points, w, cfg):
    code, title = asmt["code"], asmt["title"]
    req = _request_url(cfg, asmt.get("request_id", code), code)
    rub_rows, submit_items = _rubric_rows(points, w, asmt.get("rubric_rows"))

    gist = ("<p style='font-size:1.05em;'><b>%s</b></p>" % _ic(asmt["gist"])) if asmt.get("gist") else ""
    if asmt.get("prototype"):            # FUNCTION mode
        func = ("<p>%s</p>%s<p><b>Returns:</b> %s</p>"
                % (_ic("`%s`" % asmt["prototype"]),
                   _ul(["`%s` (`%s`) - %s" % (nm, ty, ds) for nm, ty, ds in asmt.get("params", [])]),
                   _ic(asmt.get("returns", ""))))
        build_sec = skel.section("The function", func)
    elif asmt.get("io_block") or asmt.get("io_lines") or asmt.get("io_table"):
        io_html = ""                    # CONTRACT mode — aligned snippet, never a run-on paragraph
        if asmt.get("io_block"):
            io_html += skel.pre(asmt["io_block"])
        elif asmt.get("io_lines"):
            io_html += _ul(asmt["io_lines"])
        if asmt.get("io_table"):
            io_html += skel.rich_table(asmt["io_table"]["headers"], asmt["io_table"]["rows"])
        if asmt.get("expected"):
            io_html += "<p><b>Expected Output:</b></p>" + skel.pre(asmt["expected"])
        build_sec = skel.section("Input / Output", io_html)
    else:                               # I/O mode (stdin->stdout)
        def _iohtml(label, v):
            if isinstance(v, (list, tuple)):
                return "<p><b>%s</b></p>%s" % (label, _ul([str(x) for x in v]))
            return "<p><b>%s:</b> %s</p>" % (label, _ic(v or ""))
        io_html = _iohtml("Input", asmt.get("input")) + _iohtml("Output", asmt.get("output"))
        if asmt.get("expected"):
            io_html += "<p><b>Expected Output:</b></p>" + skel.pre(asmt["expected"])
        build_sec = skel.section("Input / Output", io_html)
    test_rows = [[it["runner"], str(it["max"]), it["checks"]] for it in asmt.get("test_items", [])]
    test_section = (skel.section(
        "Test items (autograder)",
        skel.rich_table(["Test Runner Name", "Max Score", "What it checks"], test_rows)
        + "<p>%s</p>" % skel.ic(AUTOGRADER_NOTE)) if test_rows else "")
    rubric_tbl = skel.rich_table(["Item", "Points"], [[a, b] for a, b, _c in rub_rows])
    # The access code belongs IN this section, next to the link it unlocks. A code printed anywhere
    # else (its own box, the quiz intro, a separate paragraph) gets scrolled past and the student
    # hits the form with nothing to type. Link + code = ONE block, always.
    req_body = ("<p>%s — submit the form, accept, clone, then commit/push until the green check.</p>"
                % skel.link(req, "Request your %s repository" % code))
    if asmt.get("access_code"):
        req_body += skel.callout(
            # PLAIN TEXT, not _ic() output. `callout` runs every line through `ic` itself, so a
            # pre-rendered span is escaped and the student reads the raw markup instead of the
            # code (skeleton docstring: "Passing real HTML in is a MISTAKE"). Caught 2026-08-06 on
            # the first page that ever used `access_code` — <course> FP, before it was published.
            ["Access code for that form: `%s`" % asmt["access_code"],
             "Paste it into the form's access-code field — without it no repository is built."],
            kind="warn")
    # `submit_items` — what the student actually HANDS IN, when that is not one-line-per-rubric-row.
    # A detailed rubric criterion ("graded by reading your source…") is not a thing to submit, so a
    # rubric written for mechanical grading must not double as the submit list.
    submit_body = skel.rich_ol(asmt.get("submit_items") or submit_items)
    # Slide deck embed goes at the TOP (right under title + gist) to give intuition up front.
    slide = skel.slide_embed(asmt.get("slide_embed_url")) if asmt.get("slide_embed_url") else ""
    overview_html = gist
    if asmt.get("overview"):
        ov = asmt["overview"]
        hl = asmt.get("overview_highlight")
        if hl and hl in ov:              # the ONE key constraint, yellow-bold inside the paragraph
            ov = ov.replace(hl, "**%s**" % hl, 1)
            overview_html += ("<p style='line-height:1.7;'>%s</p>" % _ic(ov))
        else:
            overview_html += "<p style='line-height:1.7;'>%s</p>" % _ic(ov)
    concept = (skel.section(asmt["concept"]["title"], skel.steps(asmt["concept"].get("steps", [])))
               if asmt.get("concept") else "")
    input_box = (skel.callout([INPUT_WARN] + list(asmt["input_spec"]), kind="warn")
                 if asmt.get("input_spec") else "")
    if asmt.get("elab_edges") is not None:
        elab_section = skel.section("Elaboration (required — this is graded)",
                                    _elab_standard(asmt["elab_edges"]))
    elif asmt.get("elaboration"):
        elab_section = skel.section("Elaboration (required — this is graded)", _elab(asmt["elaboration"]))
    else:
        elab_section = ""
    return "\n".join([
        skel.page_title(title),
        (skel.section("Overview", overview_html) if overview_html else ""),
        # canonical position: Request link goes RIGHT under Overview (git-asmt order 2->3),
        # so students see how to get their repo up front -- not buried below the instructions.
        skel.section("Request your repository", req_body),
        slide,
        (skel.section("\U0001F527 Method to implement", skel.code_block(asmt["signature"]))
         if asmt.get("signature") else ""),
        concept,
        (skel.section("What to complete", _ul(asmt["what_to_complete"]))
         if asmt.get("what_to_complete") else ""),
        input_box,
        build_sec,
        (skel.section("What each does", _ul(["`%s` — %s" % (lb, ds) for lb, ds in asmt["spec"]])) if asmt.get("spec") else ""),
        skel.section("Restrictions", _restrict(asmt.get("restrictions", []))),
        elab_section,
        test_section,
        skel.section("Grading (%d points)" % points, rubric_tbl),
        skel.section("Submit (one item per rubric row)", submit_body),
    ])


# ── ENTRY — the conductor calls this ──────────────────────────────────────────────────────────
def git_page(course_slug, asmt, *, points, rubric_weights=None, push=False, due_at=None):
    """Build the git-assignment instruction gdoc + Canvas HTML. Returns out (out['html'] for
    quiz-builder). push=True pushes to a Canvas assignment (needs asmt['assignment_id']).
    The rich instruction gdoc is ALWAYS built and embedded (homework and quiz alike)."""
    cfg = course_config.load(course_slug)
    w = rubric_weights or HOMEWORK_WEIGHTS
    # doc name = Canvas item name verbatim (folder convention)
    name = ("%s - %s" % (asmt["quiz_name"], asmt["title"])) if asmt.get("quiz_name") \
        else "[Assignment %s] %s" % (asmt["code"], asmt["title"])
    out_path = os.path.join(cfg["output_dir"], "Canvas-Pages", "%s.html" % asmt["code"])
    return skel.make_page(
        cfg["course_id"], asmt.get("assignment_id"), name,
        _doc_blocks(asmt, points, w, cfg),
        _canvas_summary(asmt, points, w, cfg),
        pages_folder=course_config.pages_folder(course_slug),   # helper (drive_folder-derived / legacy)
        output_path=out_path,
        slide_embed_url=None,  # placed at TOP of the summary (see _canvas_summary), not appended last
        push_canvas=push, due_at=due_at, points=points,
        base=cfg["canvas_base_url"], token_env=cfg["canvas_token_env"],
    )


# ── DATA ENTRY — build from an asmt JSON file, so an assignment is DATA, not a script ────────
#
# Why this lives here: until 2026-07-20 git_page was importable ONLY as a Python function, so
# every session had to hand-write a throwaway driver just to hold the asmt dict. That is session
# code — it drifts, is never reviewed, and is exactly what the code-gate exists to stop. An
# assignment's content is DATA; it belongs in a .json the instructor can read, diff and re-run.
# The entry belongs to the BUILDER (its own interface), not to a course: putting it in one
# course would make every other course copy the same loader — the drift this file has already
# suffered twice (the private _ic/_ul copy; <course> forking the whole builder).
#
#   python3 git_page.py <course_slug> <asmt.json> [--points N] [--due ISO] [--push] [--quiz]
#
# The JSON is ONE asmt object or a LIST of them (built in order). Per-item "points" / "due_at"
# override the command-line defaults. --quiz uses QUIZ_WEIGHTS and does not push
# (the HTML goes to quiz-builder as an essay question).
QUIZ_WEIGHTS = {"auto": 50, "elab": 30, "commit": 15, "link": 5}


def build_from_file(course_slug, json_path, *, points=None, due_at=None, push=False, quiz=False):
    """Build every asmt in `json_path`. Returns the list of make_page outputs."""
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    items = data if isinstance(data, list) else [data]
    weights = QUIZ_WEIGHTS if quiz else None
    outs = []
    for a in items:
        pts = a.get("points", points)
        if pts is None:
            raise ValueError("git_page: %s has no points (set it in the JSON or pass --points)"
                             % a.get("code", "?"))
        outs.append(git_page(course_slug, a, points=pts, rubric_weights=weights,
                             push=(push and not quiz), due_at=a.get("due_at", due_at)))
    return outs


if __name__ == "__main__":
    argv = sys.argv[1:]
    pos = [x for x in argv if not x.startswith("--")]
    if len(pos) < 2:
        print("usage: python3 git_page.py <course_slug> <asmt.json> "
              "[--points N] [--due ISO8601] [--push] [--quiz]")
        raise SystemExit(2)

    def _opt(name):
        return argv[argv.index(name) + 1] if name in argv else None

    _cli_points = _opt("--points")   # NOT `_pts` — that is a module-level function here
    for _r in build_from_file(pos[0], pos[1],
                              points=int(_cli_points) if _cli_points else None,
                              due_at=_opt("--due"),
                              push="--push" in argv,
                              quiz="--quiz" in argv):
        print("pushed=%s doc=%s html=%s"
              % (_r.get("pushed", False), _r.get("doc_id"), _r.get("html_path")))
