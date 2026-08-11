"""Shared student-comment renderer — the ONE source of truth for comment text.

Used by BOTH `report_generator` (§5 of the grade report) AND `post_grades`
(the `comment[text_comment]` PUT to Canvas), so the comment a student sees in
the report is byte-identical to the one posted. Never duplicate this logic.

Enforces GRADING.md §4.5.3 STRUCTURALLY: a comment ALWAYS carries the full
rubric breakdown (every item `earned/max`), and every below-max row MUST have a
reason — otherwise `render_comment` raises `CommentError` and nothing renders.
That is the forcing function: you cannot produce a comment that omits the rubric
or a deduction reason. (Prose rules were forgotten; this cannot be.)
"""
from __future__ import annotations

import re


class CommentError(Exception):
    """Raised when the input cannot produce a policy-valid comment."""


def reconcile_commit(item, final, engine):
    """AUDIT tag for an engine-scored rubric item (the git commit item).

    The engine (graders/gh) commit-authenticity score is a SIGNAL, NOT a floor or a
    ceiling. Stage-B, having actually examined the history, is the decider
    (CommitAuthenticity.md: "the engine only SURFACES the signal, Stage B / the
    instructor decides"). So this NEVER blocks or reverts Stage-B's reasoned score —
    it only returns a tag noting any deviation from the engine value, so the engine
    signal stays VISIBLE next to the final score in the report/comment. Any below-max
    commit score still carries its reason via the normal render path (§4.5.3).

    Returns a tag string (engine value + arrow) when final != engine, else None."""
    if engine is None or final is None:
        return None
    f, e = float(final), float(engine)
    if f == e:
        return None
    arrow = "↑" if f > e else "⤓"
    return f"{arrow} engine {engine}→{final}"


# Comment structure = GREETING -> evaluation (rubric+reasons) -> CHEER -> SIGNATURE.
# Pools are short, dry, human — a line a professor would actually jot. NO exclamation
# spam, NO flattery, NO AI-ish over-enthusiasm. Picked deterministically by uid so a
# student always gets the same wording (reproducible reports) yet comments vary student
# to student.
_GREETINGS = ["Hi {n},", "Hello {n},", "{n},", "Hi {n} —", "Dear {n},"]
_CHEER_FULL = [
    "All requirements met. Well done.",
    "Complete and correct.",
    "Everything's here — good work.",
    "Solid submission.",
    "Clean work on this one.",
]
_CHEER_PARTIAL = [
    "A few items to address — see the breakdown below.",
    "You're close; the notes below show what to add.",
    "Mostly there — check the breakdown below for next time.",
    "See the breakdown below for the points to pick up.",
    "Worth tightening the items noted below.",
]
_SIGNATURE = "Best,\nKyu Lee"


def _pick(pool, uid):
    return pool[int(uid) % len(pool)]


def _e(s):
    import html as _h
    return _h.escape(str(s))


# Inline code-font style for command tokens in the Canvas HTML comment. Canvas strips
# <style>, so the span carries the style inline (matches the course "code font ALWAYS"
# rule). A command is marked in the source reason text with `backticks`.
_CODE_SPAN = ("<span style=\"font-family:'Courier New',monospace;background-color:#f2f2f2;"
              "padding:1px 5px;border-radius:3px;border:1px solid #e0e0e0;\">{}</span>")


def _cf(text, html):
    """Format `backtick`-delimited command tokens: a code-font span in the HTML
    comment, left as markdown backticks in the .md report. HTML-escapes the rest.
    An unmatched backtick (odd count) is a no-op fall-back to a plain escaped string."""
    text = str(text)
    if not html:
        return text  # markdown backticks already render as code in a viewer
    parts = text.split("`")
    if len(parts) % 2 == 0:  # odd number of backticks -> unmatched, don't risk mangling
        return _e(text)
    return "".join(_CODE_SPAN.format(_e(seg)) if i % 2 else _e(seg)
                   for i, seg in enumerate(parts))


def _reason_bullets(reason):
    """Split a stored reason string into (label, text) bullets for the section
    BELOW the table: 'What I saw' for evidence (pin lines), 'How to fix' for the
    'For full marks:' tail, plain bullets otherwise."""
    fix = ""
    for marker in ("For full marks:", "To earn full marks:"):
        if marker in reason:
            reason, fix = reason.split(marker, 1)
            break
    out = []
    for p in [x.strip(" .|") for x in reason.split("|") if x.strip(" .|")]:
        out.append(("What I saw", p) if p.startswith("pin ") else (None, p))
    if fix.strip():
        out.append(("How to fix", fix.strip()))
    return out


def render_comment(rubric, earned, reasons=None, points_possible=None,
                   held=False, held_msg=None, first_name=None, uid=0,
                   fmt="html", code_name="", notes=None,
                   engine_floor=None, bonus=None, bonus_comment=None):
    """Render one student's comment in the FIXED structure:
       GREETING -> CHEER -> 'Grade Breakdown' TABLE (Criteria|Max|Score|Note) ->
       per-below-max section (Why / How-to-fix bullets, OUTSIDE the table) -> SIGNATURE.

    fmt='html' -> Canvas submission comment (DEFAULT). Canvas RENDERS HTML comments
       in the UI as a real <table>/<ul> (confirmed: last-semester comments rendered as
       tables). NOTE: the Canvas API `submission_comments[].comment` field returns a
       text-EXTRACTED (flattened) copy — do NOT verify rendering from the API field;
       check SpeedGrader. Use HTML entities (&amp; / &gt;) — they render correctly.
    fmt='md'   -> the .md grade report (readable markdown table + bullets in a viewer).
    Enforces GRADING §4.5.3: a below-max item with no reason raises CommentError.
    """
    reasons = reasons or {}
    # `notes[item]` = an ADVISORY on a FULL-MARK row: the student kept the points this time,
    # but must change something next time (e.g. a one-off beginner carve-out — GRADING §4.4/§4.8
    # waives the single-commit deduction in chapter 2, and the student has to be TOLD that the
    # waiver ends). Without this, a max row silently drops its reason and the warning never
    # reaches the student — which would force hand-written comments (forbidden: the 2026-06-24
    # A05 incident). A note NEVER substitutes for a deduction reason on a below-max row.
    notes = notes or {}
    # `engine_floor[item]` = the engine's commit-authenticity SIGNAL score for an
    # engine-scored item (the git commit item). It is recorded as an AUDIT tag next to
    # Stage-B's `earned[item]` — never used to block or revert Stage-B's reasoned score
    # (the engine surfaces, Stage-B decides). Empty => no engine-scored item.
    engine_floor = engine_floor or {}
    pp = points_possible if points_possible is not None else sum(r["max"] for r in rubric)
    greeting = _pick(_GREETINGS, uid).format(n=first_name or "there")
    html = fmt != "md"

    if held:
        msg = held_msg or ("Your submission could not be opened during grading. Please "
                           "re-share it as Editor (Anyone with the link, Editor) and "
                           "resubmit so it can be graded.")
        if html:
            return f"<p>{_e(greeting)}</p>\n<p>{_e(msg)}</p>\n<p>Best,<br>Kyu Lee</p>"
        return f"{greeting}\n\n{msg}\n\nBest,\nKyu Lee"

    total = 0
    rows = []        # (item, max, score, ok)
    sections = []    # (item, score, max, [(label, text)])
    dg_tags = {}     # item -> "⤓ engine N→M (basis)" for an engine-floor downgrade
    for r in rubric:
        item, mx = r["item"], r["max"]
        if item not in earned or earned[item] is None:
            raise CommentError(f"no earned score for rubric item '{item}'")
        sc = earned[item]
        if item in engine_floor:
            tag = reconcile_commit(item, sc, engine_floor[item])
            if tag:
                dg_tags[item] = tag
        total += sc
        below = sc < mx
        if below:
            why = reasons.get(item)
            if not why or not str(why).strip():
                raise CommentError(f"'{item}' is below max ({sc}/{mx}) but has no reason "
                                   f"(GRADING.md §4.5.3 requires a reason for every deduction)")
            # §4.5.3 also requires HOW-TO-FIX: a deduction must tell the student how to
            # earn it back. A reason without a fix marker is a policy-invalid comment.
            if not any(mk in str(why) for mk in ("For full marks:", "To earn full marks:")):
                raise CommentError(
                    f"'{item}' is below max ({sc}/{mx}) but its reason has no fix — every "
                    f"deduction must include a 'For full marks: <how to fix>' clause "
                    f"(GRADING.md §4.5.3: WHAT + EVIDENCE + HOW TO FIX)")
            # SPECIFICITY for a notebook-completeness deduction (§4F.3.1): a generic
            # "some cells were left un-run" is not actionable — the reason MUST name the
            # actual un-run cells / sections (the nb grader already supplies them). Enforce
            # a `cell`/`Section` citation so a vague override can't slip through.
            # SCOPED TO NOTEBOOKS (2026-08-02). The test used to be "does the item name contain
            # 'complet'", which caught any rubric that happens to use the word. A flowchart lab
            # scores "Flowchart completeness" and has no cells at all, so a perfectly specific
            # reason ("the assignment boxes read `num2 = smallest`, reversing the direction")
            # was rejected for not citing a cell number that cannot exist. Require a notebook
            # vocabulary in the ITEM NAME before demanding notebook evidence.
            _is_nb_item = ("complet" in item.lower()
                           and re.search(r"notebook|\bnb\b|cell", item, re.I))
            if _is_nb_item and not re.search(r"(?:cell|Section)\s*\d|@answer|\.to_\w+\(|to_csv|to_hdf|to_excel", str(why), re.I):
                raise CommentError(
                    f"'{item}' is below max ({sc}/{mx}) — a completeness deduction MUST name the "
                    f"specific un-run cells or sections (e.g. 'Section 7 export cells to_csv/to_hdf'), "
                    f"not a generic 'some cells' (GRADING.md §4F.3.1). The nb grader lists them in "
                    f"review_content.execution.unexecuted.")
            sections.append((item, sc, mx, _reason_bullets(str(why))))
        elif notes.get(item):
            sections.append((item, sc, mx, [("Heads-up for next time", str(notes[item]))]))
        rows.append((item, mx, sc, not below, bool(notes.get(item)) and not below))
    # BONUS — instructor-awarded points ON TOP of the rubric (Grade-Workflow Step 4 named
    # `bonus`/`bonus_comment` in the record schema; the code never implemented it, so a bonus
    # could only be faked by inflating a rubric row — which corrupts the row's own meaning and
    # the re-grade basis). It is a separate line with its own stated reason, may push the total
    # above points_possible, and REQUIRES a reason: an unexplained bonus is as unanswerable to
    # the student as an unexplained deduction.
    bonus = float(bonus or 0)
    if bonus and not str(bonus_comment or "").strip():
        raise CommentError(
            f"uid {uid}: bonus of {bonus:g} with no `bonus_comment` — say what it is for. "
            "A student cannot be told 'you got extra points' with no reason.")
    grand = total + bonus
    cheer = _pick(_CHEER_FULL if total == pp else _CHEER_PARTIAL, uid)
    head = f"{code_name} Grade Breakdown".strip()

    if html:
        # Canvas RENDERS this as a real table in the UI. Use HTML entities (_e escapes
        # &/</>); do NOT verify from the API comment field (it returns flattened text).
        L = [f"<p>{_e(greeting)}</p>", f"<p>{_e(cheer)}</p>",
             f"<p><strong>{_e(head)}</strong></p>",
             '<table border="1" cellpadding="4" cellspacing="0">',
             "  <tr><th>Criteria</th><th>Max</th><th>Score</th><th>Note</th></tr>"]
        for item, mx, sc, ok, noted in rows:
            _n = 'see note below' if not ok else ('full marks — please read the note below' if noted else '')
            if item in dg_tags:
                _n = f"{dg_tags[item]} · {_n}" if _n else dg_tags[item]
            L.append(f"  <tr><td>{_e(item)}</td><td>{mx}</td><td>{sc}</td>"
                     f"<td>{_e(_n)}</td></tr>")
        if bonus:
            L.append(f"  <tr><td>{_e('Bonus')}</td><td>—</td><td>+{bonus:g}</td>"
                     f"<td>{_e(bonus_comment)}</td></tr>")
        L.append(f"  <tr><td><strong>Total</strong></td><td><strong>{pp}</strong></td>"
                 f"<td><strong>{grand:g}/{pp}</strong></td><td></td></tr>")
        L.append("</table>")
        for item, sc, mx, bullets in sections:
            L.append(f"<p><strong>{_e(item)} ({sc}/{mx})</strong></p>")
            L.append("<ul>")
            for lab, txt in bullets:
                L.append(f"  <li>{('<em>'+_e(lab)+':</em> ') if lab else ''}{_cf(txt, True)}</li>")
            L.append("</ul>")
        L.append("<p>Best,<br>Kyu Lee</p>")
        return "\n".join(L)

    # markdown (instructor report)
    L = [greeting, "", cheer, "", f"**{head}**", "",
         "| Criteria | Max | Score | Note |", "|---|---|---|---|"]
    for item, mx, sc, ok, noted in rows:
        _n = 'see note below' if not ok else ('full marks — see note below' if noted else '')
        if item in dg_tags:
            _n = f"{dg_tags[item]} · {_n}" if _n else dg_tags[item]
        L.append(f"| {item} | {mx} | {sc} | {_n} |")
    if bonus:
        L.append(f"| Bonus | — | +{bonus:g} | {bonus_comment} |")
    L.append(f"| **Total** | **{pp}** | **{grand:g}/{pp}** | |")
    L.append("")
    for item, sc, mx, bullets in sections:
        L.append(f"**{item} ({sc}/{mx})**")
        for lab, txt in bullets:
            L.append(f"- {('*'+lab+':* ') if lab else ''}{txt}")
        L.append("")
    L += ["Best,", "Kyu Lee"]
    return "\n".join(L)


def comment_html(*args, **kwargs):
    """The Canvas-postable HTML comment (renders as a table in the SpeedGrader UI)."""
    kwargs["fmt"] = "html"
    return render_comment(*args, **kwargs)


def render_note(blocks, first_name=None, uid=0, fmt="html", greeting=None):
    """Render a free-form instructor NOTE / reply — NOT a rubric grade comment.

    Used for a follow-up teaching comment (e.g. answering a student's question or
    giving step-by-step guidance) posted ALONGSIDE the grade comment. Structure:
       GREETING -> blocks -> SIGNATURE.
    `blocks` is a list of (kind, payload):
       ("p",  "paragraph text")
       ("ol", ["step 1", "step 2", ...])   # ordered list
       ("ul", ["item", ...])                # bullet list
    Command tokens wrapped in `backticks` render as code-font (html) / stay as
    markdown backticks (md), via the shared _cf. No rubric table, no reason
    enforcement — this is deliberately outside GRADING §4.5.3 (it is not a grade)."""
    html = fmt != "md"
    g = greeting or _pick(_GREETINGS, uid).format(n=first_name or "there")
    if html:
        L = [f"<p>{_e(g)}</p>"]
        for kind, payload in blocks:
            if kind == "p":
                L.append(f"<p>{_cf(payload, True)}</p>")
            elif kind in ("ol", "ul"):
                tag = "ol" if kind == "ol" else "ul"
                L.append(f"<{tag}>")
                for it in payload:
                    L.append(f"  <li>{_cf(it, True)}</li>")
                L.append(f"</{tag}>")
        L.append("<p>Best,<br>Kyu Lee</p>")
        return "\n".join(L)
    # markdown
    L = [g, ""]
    for kind, payload in blocks:
        if kind == "p":
            L.append(payload); L.append("")
        elif kind == "ol":
            for i, it in enumerate(payload, 1):
                L.append(f"{i}. {it}")
            L.append("")
        elif kind == "ul":
            for it in payload:
                L.append(f"- {it}")
            L.append("")
    L += ["Best,", "Kyu Lee"]
    return "\n".join(L)
