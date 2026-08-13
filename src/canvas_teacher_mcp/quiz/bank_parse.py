#!/usr/bin/env python3
"""bank_parse — publisher test-bank TEXT -> quiz_builder questions JSON + a review preview.

This is the ADAPTER in front of `quiz-builder`: it turns a publisher's plain-text question
bank into the JSON `quiz_builder.build_quiz_from_file` already consumes. It NEVER touches
Canvas — it reads one text file and writes three files. Posting stays with quiz_builder,
publishing stays with the instructor.

    bank_parse.py <bank.txt> --course <slug> --chapter 7 [--points 3] [--quiz-id N]

Writes into  <output_dir>/quiz_build/Ch<N>/ :
    Ch<N>_source.txt   the bank as parsed (UTF-8, LF) — provenance for the JSON
    Ch<N>_quiz.json    quiz_builder input
    Ch<N>_quiz.html    preview: every question + choices, correct ones marked — REVIEW THIS

Bank grammar (verified against the Liang Java test bank, chapter 7):

    Chapter 7 Single-Dimensional Arrays        title line
    Section 7.5 Copying Arrays                 section marker, skipped ("Sections" too)
    12.<TAB>stem text                          question start
                                               blank line separates stem from code
    int[] list = {1, 2, 3};                    code block (rendered in Courier)
    a.<TAB>choice
    ...
    Key:cde  optional rationale                answer letters, then prose
    #                                          block separator

Three rules exist because breaking any of them loses questions silently:
  * `key:` is matched CASE-INSENSITIVELY — 5 of chapter 7's 53 items use lowercase `key:`,
    and a case-sensitive parser drops exactly those.
  * only the RUN of [a-e] right after `key:` is the answer; the rest is the author's
    rationale ("Key:abcd e is incorrect because...") and never reaches the student.
  * the source already carries HTML entities (`&lt;`), so escaping is entity-aware — a plain
    escape would show students `&amp;lt;`.

A content error in the bank is NOT fixed here. Correct the source, save it as the
`_source.txt` this parser reads, and note it in the skill's report — the parser stays a
faithful translator so its output can always be traced back to a file.
"""
import argparse
import html as _html
import json
import os
import re
import sys

_SEP = re.compile(r"(?m)^#[ \t]*$")
_SECTION = re.compile(r"(?i)^\s*sections?\s+\d")
_QSTART = re.compile(r"^\s*(\d+)\s*[.]\s*(.*)$")
_CHOICE = re.compile(r"^\s*([a-eA-E])\s*[.]\s+(.*)$")
_KEY = re.compile(r"(?i)^\s*key\s*:\s*([a-e]*)\s*(.*)$")
_CODEFONT = 'font-family: Courier New;'


def read_bank(path):
    """Decode the bank. Publisher banks are Windows-authored: CP1252 + CRLF, NOT UTF-8
    (chapter 7 carries one en-dash, 0x96, which makes a UTF-8 read raise)."""
    raw = open(path, "rb").read()
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc).replace("\r\n", "\n").replace("\r", "\n"), enc
        except UnicodeDecodeError:
            continue
    raise SystemExit("bank_parse: cannot decode %s" % path)


def esc(s):
    """Escape for HTML while LEAVING EXISTING ENTITIES ALONE. The bank already contains
    `&lt;` / `&amp;`; a naive escape would render them literally to the student."""
    s = re.sub(r"&(?![a-zA-Z][a-zA-Z0-9]*;|#\d+;|#x[0-9a-fA-F]+;)", "&amp;", s)
    return s.replace("<", "&lt;").replace(">", "&gt;")


def code_html(lines):
    """Quiz-5 house style: one Courier span, <br> between lines, indentation via &nbsp;."""
    out = []
    for ln in lines:
        stripped = ln.lstrip(" \t")
        pad = "&nbsp;" * (len(ln) - len(stripped))
        out.append(pad + esc(stripped))
    return '<span style="%s">%s</span>' % (_CODEFONT, "<br>".join(out))


def parse_block(block, idx):
    """One `#`-delimited block -> a question dict, plus a list of problem strings."""
    problems = []
    lines = [l for l in block.split("\n") if not _SECTION.match(l)]

    num = stem_first = None
    stem_rest, choices, key_letters, rationale = [], [], None, ""
    state = "pre"
    for ln in lines:
        if state == "pre":
            m = _QSTART.match(ln)
            if m and not _CHOICE.match(ln):
                num, stem_first, state = int(m.group(1)), m.group(2).strip(), "stem"
            continue
        km = _KEY.match(ln)
        if km:
            key_letters, rationale = km.group(1).lower(), km.group(2).strip()
            state = "done"
            continue
        if state == "done":
            continue
        cm = _CHOICE.match(ln)
        if cm:
            choices.append([cm.group(1).lower(), cm.group(2).rstrip()])
            state = "choices"
            continue
        if state == "choices" and ln.strip() and choices:
            choices[-1][1] += " " + ln.strip()      # wrapped choice line
        elif state == "stem":
            stem_rest.append(ln)

    if num is None:
        return None, ["block %d: no question number" % idx]
    if not choices:
        problems.append("Q%s: no choices" % num)
    if key_letters is None:
        problems.append("Q%s: NO ANSWER KEY" % num)
    elif not key_letters:
        problems.append("Q%s: `key:` present but no letter" % num)

    letters = [c[0] for c in choices]
    correct = []
    for k in (key_letters or ""):
        if k in letters:
            correct.append(letters.index(k))
        else:
            problems.append("Q%s: key '%s' is not among choices %s" % (num, k, letters))

    # stem = leading prose paragraph; anything after the first blank line is a code block
    body, code = [], []
    seen_blank = False
    for ln in stem_rest:
        if not ln.strip():
            seen_blank = True
            continue
        (code if seen_blank else body).append(ln)
    text = " ".join([stem_first] + [b.strip() for b in body]).strip()
    text_html = esc(text)
    if code:
        text_html += "<br><br>" + code_html(code) + "<br>"

    return {"num": num, "text_html": text_html, "choices": [c[1] for c in choices],
            "correct": correct, "rationale": rationale, "has_code": bool(code)}, problems


def parse(text):
    questions, problems = [], []
    for i, block in enumerate(_SEP.split(text), 1):
        if not block.strip():
            continue
        q, p = parse_block(block, i)
        problems.extend(p)
        if q:
            questions.append(q)
    return questions, problems


def to_items(questions, chapter, points):
    items = []
    for q in questions:
        n = len(q["correct"])
        items.append({"type": "mc" if n == 1 else "ma",
                      "name": "%02d-%03d" % (chapter, q["num"]),
                      "points": points,
                      "text_html": q["text_html"],
                      "choices": q["choices"],
                      "correct": q["correct"][0] if n == 1 else q["correct"]})
    return items


def preview_html(title, questions, items):
    rows = []
    for q, it in zip(questions, items):
        opts = []
        for i, c in enumerate(q["choices"]):
            ok = (i in q["correct"])
            opts.append(
                '<li style="%s">%s%s</li>'
                % ("background:#e6f4ea;border-left:4px solid #137333;padding:3px 8px;margin:2px 0;"
                   if ok else "padding:3px 8px;margin:2px 0;",
                   esc(c), ' <strong style="color:#137333">&#10004;</strong>' if ok else ""))
        rows.append(
            '<div style="border:1px solid #ddd;border-radius:6px;padding:12px 16px;margin:14px 0;">'
            '<div style="color:#1F3864;font-weight:bold;">%s &middot; %s &middot; %s pt</div>'
            '<div style="margin:8px 0;">%s</div><ol type="a" style="margin:6px 0;">%s</ol>%s</div>'
            % (it["name"], it["type"].upper(), it["points"], q["text_html"], "".join(opts),
               '<div style="color:#666;font-size:90%%;">rationale: %s</div>' % esc(q["rationale"])
               if q["rationale"] else ""))
    return ("<!doctype html><meta charset='utf-8'><title>%s</title>"
            "<body style=\"font-family:-apple-system,Segoe UI,sans-serif;max-width:900px;"
            "margin:24px auto;padding:0 16px;\"><h1 style='color:#1F3864'>%s</h1>"
            "<p style='color:#666'>%d questions &middot; %g points total &middot; "
            "green = correct answer</p>%s</body>"
            % (title, title, len(items), sum(i["points"] for i in items), "".join(rows)))


def build_dir(course, chapter):
    """Where a chapter's build files belong: <output_dir>/quiz_build/Ch<N>.

    Derived, never stored — the course config holds `canvas_url` and `school` and nothing that
    can be computed from where the file itself sits (Where/CourseConfig.md).
    """
    from .. import course_config

    return os.path.join(course_config.load(course)["output_dir"], "quiz_build", "Ch%d" % chapter)


def write_build(out, text, questions, items, chapter, source_name, intro_html="", quiz_id=None):
    """Write the three build files and return their paths.

    Split out of `main` so a caller without a command line — the MCP tool — writes exactly what
    the CLI writes. The source text is kept beside the JSON because it is the provenance: the
    questions can be traced back to what they were parsed from, and only if it is kept.
    """
    os.makedirs(out, exist_ok=True)
    stem = os.path.join(out, "Ch%d" % chapter)

    with open(stem + "_source.txt", "w", encoding="utf-8") as f:
        f.write(text)
    payload = {"intro_html": intro_html, "questions": items}
    if quiz_id:
        payload["quiz_id"] = quiz_id
    with open(stem + "_quiz.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1, ensure_ascii=False)
    title = "Chapter %d — parsed from %s" % (chapter, source_name)
    with open(stem + "_quiz.html", "w", encoding="utf-8") as f:
        f.write(preview_html(title, questions, items))

    return {"source_txt": stem + "_source.txt",
            "quiz_json": stem + "_quiz.json",
            "preview_html": stem + "_quiz.html"}


def main(argv):
    p = argparse.ArgumentParser(prog="bank_parse.py")
    p.add_argument("bank", help="publisher test-bank .txt")
    p.add_argument("--course", required=True, help="course slug (course_config)")
    p.add_argument("--chapter", type=int, required=True)
    p.add_argument("--points", type=float, default=3.0, help="points per question (default 3)")
    p.add_argument("--quiz-id", type=int, default=None, dest="quiz_id")
    p.add_argument("--intro-html", default="", dest="intro_html")
    p.add_argument("--outdir", default=None, help="override the output directory")
    a = p.parse_args(argv)

    text, enc = read_bank(a.bank)
    questions, problems = parse(text)
    items = to_items(questions, a.chapter, a.points)

    out = a.outdir or build_dir(a.course, a.chapter)
    write_build(out, text, questions, items, a.chapter, os.path.basename(a.bank),
                a.intro_html, a.quiz_id)
    stem = os.path.join(out, "Ch%d" % a.chapter)

    nums = [q["num"] for q in questions]
    gaps = [n for n in range(min(nums), max(nums) + 1) if n not in nums] if nums else []
    ma = [i["name"] for i in items if i["type"] == "ma"]
    print("source      : %s  (decoded %s)" % (a.bank, enc))
    print("questions   : %d   numbers %s..%s   %s"
          % (len(items), min(nums or [0]), max(nums or [0]),
             "no gaps" if not gaps else "GAPS %s" % gaps))
    print("points      : %g each -> %g total" % (a.points, sum(i["points"] for i in items)))
    print("multi-answer: %d  %s" % (len(ma), ", ".join(ma)))
    print("with code   : %d" % sum(1 for q in questions if q["has_code"]))
    print("problems    : %s" % ("none" if not problems else ""))
    for pr in problems:
        print("   ! " + pr)
    print("\nwrote %s_source.txt / _quiz.json / _quiz.html" % stem)
    print("\n>> REVIEW %s_quiz.html IN A BROWSER before building the quiz." % stem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
