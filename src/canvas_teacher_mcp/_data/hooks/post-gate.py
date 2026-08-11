#!/usr/bin/env python3
"""Grade-post harness — PreToolUse hook.

Blocks ONLY Canvas grade/comment posting. Grading must stop at save+report;
posting is a separate, explicitly instructor-authorised step.

- Grade-post is BLOCKED by default.
- It is allowed only while the gate file ~/.claude/.post-gate holds a unix
  timestamp within the last 60 minutes. The gate can only be opened from a
  real terminal (Claude itself is blocked from writing it) — that deliberate
  act IS the instructor's "post" command.
- NON-grade Canvas writes (page body, assignment description, HTML upload,
  publish/unpublish) are NOT affected.
- Claude is also blocked from editing the harness files themselves.

Exit 0 = allow. Exit 2 = block (stderr shown to Claude).
"""
import sys, json, os, re, time

HOME = os.path.expanduser("~")
GATE = os.path.join(HOME, ".claude", ".post-gate")
HOOK = os.path.join(HOME, ".claude", "hooks", "post-gate.py")
SETTINGS = os.path.join(HOME, ".claude", "settings.json")
GATE_WINDOW = 60 * 60  # seconds an opened gate stays valid

# grade/comment posting signatures — these appear ONLY in grade-post code
GRADE_SIGS = [
    r"comment\[text_comment\]", r"comment%5Btext_comment%5D",
    r"posted_grade", r"quiz_submissions\[", r"fudge_points",
    r"post_grades\.py",
]

# Toggle for GROUP A (inline-form gate).
#   True  -> block only inline grading            (A AND B)
#   False -> A disabled, block on grade token only (B alone)
GROUP_A_ENABLED = True

# ═══ GROUP A — inline-form gate ═══
INLINE_FORM = r"python3?\s+-c\b|python3?\s+-\s|<<-?\s*['\"]?[A-Za-z]"
def _is_inline_form(cmd):
    return bool(re.search(INLINE_FORM, cmd or ""))
# ═══ END GROUP A ═══

# ═══ GROUP B — grade read/render tokens ═══
GRADE_ONLY_SIGS = [
    r"fetch_submissions", r"post_submission_grade", r"/submissions\b",
    r"submission_comments", r"entered_score", r"workflow_state",
    r"report_generator", r"grades_json", r"grade_engine", r"grade_skill",
]
CANON_SCRIPTS = r"(?:post_grades|grade_skill|report_generator)\.py|-m\s+grade_engine"
def _has_grade_token(cmd):
    if re.search(CANON_SCRIPTS, cmd or ""):
        return False
    return any(re.search(s, cmd or "", re.I) for s in GRADE_ONLY_SIGS)
# ═══ END GROUP B ═══

def is_inline_grading(cmd):
    if not _has_grade_token(cmd):
        return False
    if GROUP_A_ENABLED:
        return _is_inline_form(cmd)      # A AND B
    return True                          # B only


def is_grade_post(text):
    if not text:
        return False
    for s in GRADE_SIGS:
        if re.search(s, text, re.I):
            return True
    # a PUT/POST write to a /submissions endpoint = grade/comment posting
    if (re.search(r"instructure\.com", text, re.I) and "/submissions" in text
            and re.search(r"\bPUT\b|\bPOST\b|-X\s*'?\"?P(UT|OST)", text)):
        return True
    return False


def gate_open():
    try:
        with open(GATE) as f:
            return (time.time() - float(f.read().strip())) <= GATE_WINDOW
    except Exception:
        return False


def deny(msg):
    sys.stderr.write(msg)
    sys.exit(2)


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # unparseable input — do not break normal work
    tool = payload.get("tool_name", "")
    ti = payload.get("tool_input", {}) or {}
    cwd = payload.get("cwd") or os.getcwd()

    if tool in ("Edit", "Write", "MultiEdit"):
        fp = os.path.realpath(ti.get("file_path", "") or "")
        if fp in (os.path.realpath(GATE), os.path.realpath(HOOK),
                  os.path.realpath(SETTINGS)):
            deny("BLOCKED: the grade-post harness (hook script / gate / global "
                 "settings) cannot be edited through Claude. Change it from a real "
                 "terminal if you must.")
        sys.exit(0)

    if tool == "Bash":
        cmd = ti.get("command", "") or ""
        # Claude must not touch the gate or the hook via Bash
        if re.search(r"\.post-gate|hooks/post-gate\.py", cmd):
            deny("BLOCKED: the post-gate / hook is changed only from a real "
                 "terminal, never through Claude.")
        if is_inline_grading(cmd):
            deny("BLOCKED - INLINE GRADING (RULE #0e). "
                 "Grade only via grade_skill.py / report_generator / post_grades.py. "
                 "No inline collect/score/render. (Canvas page work unaffected.)")
        text = cmd
        # also scan any script file the command runs
        for m in re.finditer(r"(?:python3?|bash|sh|\./)\s+(\S+\.(?:py|sh))", cmd):
            p = m.group(1)
            cand = p if os.path.isabs(p) else os.path.join(cwd, p)
            try:
                if os.path.isfile(cand):
                    text += "\n" + open(cand, errors="ignore").read(300000)
            except Exception:
                pass
        if is_grade_post(text):
            if gate_open():
                sys.exit(0)  # instructor opened the gate — allow this post
            deny("BLOCKED — GRADE-POST HARNESS.\n"
                 "A grade/comment post to Canvas was detected, but the post-gate is "
                 "closed (no instructor post-command is active). Grading stops at "
                 "save + report.\n"
                 "To post, the instructor opens the gate FROM A REAL TERMINAL:\n"
                 "    date +%s > ~/.claude/.post-gate\n"
                 "(valid 20 min). Non-grade Canvas writes are not affected.")
        sys.exit(0)

    sys.exit(0)


if __name__ == "__main__":
    main()
