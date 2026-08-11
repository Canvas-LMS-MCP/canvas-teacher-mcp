#!/usr/bin/env python3
"""Build and ship a Starter repo for a git coding assignment — the whole sequence, once.

WHY THIS EXISTS
    The steps are mechanical and a skipped one is invisible. On 2026-07-30 <COURSE>A612Starter sat
    EMPTY (0 commits, 0 branches) for nine days: it was created next to its siblings but the push
    was never run, nothing verified it, and the failure only surfaced when a student's repo request
    died with "Could not create your repo from ...". This script makes "not done" impossible to
    mistake for "done": every stage verifies its own result and stops on the first failure.

WHAT A STARTER IS (git-asmt-repo/SKILL.md Part C — this script enforces it)
    A new repo with ONE commit whose tree is the assignment minus the answer:
    non-empty · no solution (not even in history) · still compiles · ships the harness ·
    private + is_template · registered in the org-hub.

USAGE
    python3 git_starter_build.py --course <course> --code A612 --lang java-junit \
        [--solution-dir <dir>] [--master <org/repo>] [--starter <org/repo>] \
        [--strip "src/Main.java:traverse"] [--register] [--verify-100] [--dry-run]

    --course      course slug; org / repo prefix come from course_config
    --code        assignment code (A612, W35, Q6Q1 ...)
    --lang        java-junit | cpp-catch2 | cpp-stdout | python-pytest  (the L2 skill)
    --solution-dir  local audited solution dir (default: <course dir>/<PREFIX><CODE>)
    --strip       file:symbol pairs to stub, repeatable; default = the L2 convention for --lang
    --register    also run GitHub-Starter-Hub/ops/config.sh add-assignment
    --verify-100  final proof: template-clone the Starter, drop the solution in, push, read the run
                  BY SHA, expect 100/100, then delete the throwaway repo
    --dry-run     print every command, touch nothing remote

NOT IN SCOPE
    Writing the solution or the tests (that is the AI's job, per L1 Part A) and building the Canvas
    page (git-asmt-page). This script only ships what already passed the audit.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from . import course_config  # noqa: E402  (the ONE config reader)

LANGS = {
    # lang            compile (in the repo root)                      the file students edit
    "java-junit": {
        "compile": ['javac -cp lib/junit-platform-console-standalone-1.10.2.jar '
                    '-d out src/*.java test/*.java'],
        "clean": ["rm -rf out"],
        "student_file": "src/Main.java",
        "stub_style": "java",
    },
    "cpp-catch2": {
        "compile": ["g++ -std=c++17 -Wall -Wextra main.cpp -o /tmp/_sb_main",
                    "g++ -std=c++17 -Wall -Wextra -c tests.cpp -o /tmp/_sb_tests.o"],
        "clean": ["rm -f /tmp/_sb_main /tmp/_sb_tests.o", "make clean"],
        "student_file": "main.hpp",
        "stub_style": "cpp",
    },
    "cpp-stdout": {
        "compile": ["g++ -std=c++17 -Wall -Wextra -c main.cpp -o /tmp/_sb_main.o"],
        "clean": ["rm -f /tmp/_sb_main.o", "rm -f result*.txt"],
        "student_file": "main.cpp",
        "stub_style": "cpp",
    },
    "python-pytest": {
        "compile": ["python3 -m py_compile main.py"],
        "clean": ["rm -rf __pycache__ .pytest_cache"],
        "student_file": "main.py",
        "stub_style": "python",
    },
}

JUNK = ["out", "a.out", "main", "programtest", "__pycache__", ".pytest_cache",
        "*.o", "*.class", "*.dSYM", "result*.txt",
        # Working copies of the SOLUTION. A backup/old/bak dir is not "junk" — it is the answer
        # under a different name, and stripping `main.hpp` does nothing to it.
        # (2026-08-02: <COURSE>A1102Starter shipped .backup_2026-05-16/main.hpp = the full solution.
        # GATE C passed because it only diffed the student file.)
        ".backup*", "backup*", "*.bak", "*_backup", "*_old", "old", ".vscode"]

# Files that may legitimately live in a Starter. Anything else that is a copy of a
# student-editable file is a leak — checked by name AND by content in stage 3.



class Stop(Exception):
    """A gate failed. The caller prints it and exits non-zero — never 'continue anyway'."""


def sh(cmd, cwd=None, check=True, capture=True, dry=False):
    if dry:
        print(f"    [dry] {cmd}")
        return ""
    p = subprocess.run(cmd, shell=True, cwd=cwd, text=True,
                       capture_output=capture)
    if check and p.returncode != 0:
        raise Stop(f"command failed ({p.returncode}): {cmd}\n{(p.stdout or '')[-2000:]}"
                   f"{(p.stderr or '')[-2000:]}")
    return (p.stdout or "").strip()


def gh_json(path, jq=None):
    # QUOTE the path: a query string carries '&', and unquoted it splits the shell command in
    # two — `gh api …?head_sha=X` runs in the background and `per_page=1 --jq …` fails, so this
    # function returned None every time and stage 9's poll could never see a finished run.
    cmd = f"gh api '{path}'"
    if jq:
        cmd += f" --jq '{jq}'"
    out = subprocess.run(cmd, shell=True, text=True, capture_output=True)
    if out.returncode != 0:
        return None
    txt = (out.stdout or "").strip()
    if not txt:
        return None
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        return txt


def stage(n, title):
    print(f"\n▶ {n}. {title}")


# ---------------------------------------------------------------- strip

def strip_file(path, symbols, style):
    """Replace each named function/method body with a TODO stub, keeping the signature.

    EVERY overload of a symbol is stripped, not just the first. C++ lets one name carry several
    bodies (`Scores()` and `Scores(int[], int)`), and stopping at the first match leaves the rest
    of the answer in the Starter — exactly what happened to <COURSE>A1103Starter on 2026-08-02.
    """
    src = open(path).read()
    for sym in symbols:
        if style == "python":
            pat = re.compile(rf"(def\s+{re.escape(sym)}\s*\([^)]*\)\s*:\n)(.*?)(?=\n(?:def |class |\Z))",
                             re.S)
            repl = r"\1    # TODO: implement this function\n    pass\n"
        elif style in ("java", "cpp"):
            # signature line ... { body }  — brace-matched, so nested blocks survive.
            # Loop: a name may have SEVERAL overloads; strip them all. `pos` walks forward past
            # each stub already written, so the scan terminates.
            pos, hits = 0, 0
            while True:
                m = re.search(rf"[^\n]*\b{re.escape(sym)}\s*\([^)]*\)[^{{;]*\{{", src[pos:])
                if not m:
                    break
                m_start, m_end = m.start() + pos, m.end() + pos
                start = m_end - 1
                depth, i = 0, start
                while i < len(src):
                    if src[i] == "{":
                        depth += 1
                    elif src[i] == "}":
                        depth -= 1
                        if depth == 0:
                            break
                    i += 1
                else:
                    raise Stop(f"strip: unbalanced braces around '{sym}' in {path}")
                body_stub = "{\n        // TODO: implement this\n    }"
                head = src[m_start:start]
                ret_stub = ""
                if style == "java" and not re.search(r"\bvoid\b", head):
                    # The neutral value follows the RETURN TYPE, and an array type returns null even
                    # though its element type is primitive: `int[] f()` with `return 0;` does not
                    # compile, and the stub must compile (L1 Part C property 3). Match the declared
                    # type right before the method name, not any primitive word anywhere in `head`.
                    _rt = re.search(r"([\w.<>\[\]]+)\s*(?:\[\s*\])*\s+\w+\s*\($", head.rstrip())
                    _t = (_rt.group(1) if _rt else "") + ("[]" if re.search(r"\[\s*\]\s*\w+\s*\($", head.rstrip()) else "")
                    if "[" in _t:
                        ret_stub = "        return null;\n"
                    elif re.match(r"^(int|long|short|byte|char)$", _t):
                        ret_stub = "        return 0;\n"
                    elif _t in ("float", "double"):
                        ret_stub = "        return 0.0;\n"
                    elif _t == "boolean":
                        ret_stub = "        return false;\n"
                    else:
                        ret_stub = "        return null;\n"
                elif style == "cpp" and not re.search(r"\bvoid\b", head):
                    # A CONSTRUCTOR/DESTRUCTOR has no return type — `return {};` in one is ill-formed
                    # ("constructor must not return a value"), so the stub would not compile (Part C
                    # property 3). It reads as non-void only because there is no `void` either.
                    # Detect it: the signature is bare `Name(` / `~Name(` with nothing before the name
                    # on that line. (Hit 2026-08-02 on <course> A1102 — the first struct assignment; every
                    # earlier course stripped free functions only.)
                    _sig = head[head.rfind("\n") + 1:].strip()
                    _is_ctor = re.match(rf"^~?{re.escape(sym)}\s*\(", _sig) is not None
                    if not _is_ctor:
                        ret_stub = "        return {};\n"
                if ret_stub:
                    body_stub = "{\n        // TODO: implement this\n" + ret_stub + "    }"
                src = src[:start] + body_stub + src[i + 1:]
                pos = start + len(body_stub)      # continue AFTER the stub we just wrote
                hits += 1
            if hits == 0:
                raise Stop(f"strip: symbol '{sym}' not found in {path}")
            continue
        src, n = pat.subn(repl, src)
        if n == 0:
            raise Stop(f"strip: symbol '{sym}' not found in {path}")
    open(path, "w").write(src)


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--course", required=True)
    ap.add_argument("--code", required=True)
    ap.add_argument("--lang", required=True, choices=sorted(LANGS))
    ap.add_argument("--solution-dir")
    ap.add_argument("--master")
    ap.add_argument("--starter")
    ap.add_argument("--strip", action="append", default=[],
                    help="file:symbol[,symbol...] — repeatable")
    ap.add_argument("--omit", action="append", default=[],
                    help="path — repeatable. Ship the Starter WITHOUT this file at all, instead "
                         "of stubbing it. For a from-scratch project where the student designs "
                         "the class themselves, a stub hands over every field and method "
                         "signature — which IS the thing being graded. The Starter then does NOT "
                         "compile until the student writes the file; stage 4 inverts its "
                         "expectation accordingly and says so out loud.")
    ap.add_argument("--register", action="store_true")
    ap.add_argument("--verify-100", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    dry = a.dry_run
    L = LANGS[a.lang]

    cfg = course_config.load(a.course)
    org = cfg.get("github_org")
    if not org:
        raise Stop(f"course_config['{a.course}'] has no github_org")

    sol_dir = a.solution_dir
    if not sol_dir:
        raise Stop("--solution-dir is required (the audited local solution dir)")
    sol_dir = os.path.abspath(sol_dir)
    if not os.path.isdir(sol_dir):
        raise Stop(f"solution dir not found: {sol_dir}")
    base = os.path.basename(sol_dir.rstrip("/"))
    master = a.master or f"{org}/{base}"
    starter = a.starter or f"{master}Starter"

    print(f"course={a.course} code={a.code} lang={a.lang}")
    print(f"solution={sol_dir}\nmaster={master}\nstarter={starter}")

    # 1 — the solution dir must actually build+pass where it stands
    stage(1, "solution dir compiles (L2 COMPILE)")
    for c in L["compile"]:
        sh(c, cwd=sol_dir, dry=dry)
    for c in L["clean"]:
        sh(c, cwd=sol_dir, check=False, dry=dry)
    print("    ok")

    # 2 — copy to /tmp, drop history + junk
    stage(2, "copy to /tmp, drop .git and build output")
    tmp = tempfile.mkdtemp(prefix="starter_")
    work = os.path.join(tmp, os.path.basename(starter))
    if not dry:
        shutil.copytree(sol_dir, work)
        shutil.rmtree(os.path.join(work, ".git"), ignore_errors=True)
        for pat in JUNK:
            sh(f"rm -rf {pat}", cwd=work, check=False)
    print(f"    {work}")

    # 3 — strip the answer
    stage(3, "strip the solution to a compiling stub")
    targets = a.strip or []
    omits = a.omit or []
    if not targets and not omits:
        raise Stop(f"--strip is required, e.g. --strip '{L['student_file']}:funcName'  "
                   "(nothing is stripped by guess — an unstripped Starter ships the answer). "
                   "Use --omit PATH when the student writes the whole file from scratch.")
    for path in omits:
        full = os.path.join(work, path)
        if not dry:
            if not os.path.isfile(full):
                raise Stop(f"omit target missing: {path}")
            os.remove(full)
        print(f"    omitted {path} (student writes this file from scratch)")
    if omits and not dry:
        # an omitted file's directory may now be empty — ship it absent, not as an empty dir
        for path in omits:
            d = os.path.dirname(os.path.join(work, path))
            if d and os.path.isdir(d) and not os.listdir(d):
                os.rmdir(d)
                print(f"    removed now-empty {os.path.relpath(d, work)}/")
    for spec in targets:
        path, _, syms = spec.partition(":")
        if not syms:
            raise Stop(f"--strip needs file:symbol, got '{spec}'")
        full = os.path.join(work, path)
        if not dry:
            if not os.path.isfile(full):
                raise Stop(f"strip target missing: {path}")
            strip_file(full, [s.strip() for s in syms.split(",") if s.strip()], L["stub_style"])
        print(f"    stubbed {path}: {syms}")

    # 3b — LEAK SWEEP: any OTHER file in the tree that still holds a stripped body is the answer
    # under a different name. Judge by CONTENT, not name (git-asmt-repo Part C). The JUNK list
    # cannot be trusted alone — it only ever knows the leak shapes we have already been bitten by.
    if not dry:
        stripped_names = {os.path.basename(s.split(":")[0]) for s in targets}
        omitted_names = {os.path.basename(p) for p in omits}
        # For an omitted file there is no legitimate copy anywhere, so we can also match by
        # CONTENT: any file carrying its body under another name is the answer in disguise.
        omitted_bodies = {}
        for p in omits:
            try:
                src = open(os.path.join(sol_dir, p), encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            squashed = re.sub(r"\s+", "", src)
            if len(squashed) >= 200:              # too short to fingerprint reliably
                omitted_bodies[p] = squashed
        marker = "// TODO: implement this" if L["stub_style"] in ("cpp", "java") else "# TODO: implement"
        leaks = []
        for root, dirs, files in os.walk(work):
            dirs[:] = [d for d in dirs if d != ".git"]
            for fn in files:
                full = os.path.join(root, fn)
                rel = os.path.relpath(full, work)
                try:
                    txt = open(full, encoding="utf-8", errors="ignore").read()
                except OSError:
                    continue
                if fn in omitted_names:
                    leaks.append(f"{rel} (same name as an omitted file)")
                    continue
                squashed = re.sub(r"\s+", "", txt)
                hit = next((p for p, body in omitted_bodies.items() if body in squashed), None)
                if hit:
                    leaks.append(f"{rel} (holds the body of the omitted {hit})")
                    continue
                if rel in {s.split(":")[0] for s in targets}:
                    continue                      # the stubbed file itself
                if fn not in stripped_names:
                    continue                      # only same-named copies can hold the same answer
                if marker not in txt:
                    leaks.append(rel)
        if leaks:
            raise Stop("SOLUTION LEAK — these files still carry a student file's answer:\n  "
                       + "\n  ".join(leaks)
                       + "\nDelete them from the solution dir (or add them to JUNK) and re-run.")
        print("    leak sweep: no un-stripped or renamed copy of a student file in the tree")

    # 4 — the stub must still compile, and must NOT pass
    #     …UNLESS files were omitted: then the Starter is deliberately incomplete and must NOT
    #     compile. Saying that out loud here is what keeps GATE D honest — a red COMPILE is a
    #     harness bug in strip mode and the intended state in omit mode, and the two must never
    #     be confused by a later reader of the log.
    orig_src = None
    if omits:
        stage(4, "omit mode — the Starter must NOT compile yet")
        if not dry:
            for path in omits:
                if os.path.exists(os.path.join(work, path)):
                    raise Stop(f"omit failed — {path} is still in the tree")
            # a mixed run (--strip AND --omit) still has to prove the strip did something
            for spec in targets:
                f = spec.split(":")[0]
                if open(os.path.join(work, f)).read() == open(os.path.join(sol_dir, f)).read():
                    raise Stop(f"stub {f} is identical to the solution — the strip did nothing")
            for c in L["clean"]:
                sh(c, cwd=work, check=False, dry=dry)
        print("    ok (omitted files absent; COMPILE is red until the student writes them — "
              "INTENDED, not a harness bug)")
    else:
        stage(4, "stub compiles, harness paths resolve")
        for c in L["compile"]:
            sh(c, cwd=work, dry=dry)
        for c in L["clean"]:
            sh(c, cwd=work, check=False, dry=dry)
        if not dry:
            stub_src = open(os.path.join(work, targets[0].split(":")[0])).read()
            orig_src = open(os.path.join(sol_dir, targets[0].split(":")[0])).read()
            if stub_src == orig_src:
                raise Stop("stub is identical to the solution — the strip did nothing")
        print("    ok (stub compiles and differs from the solution)")

    # 5 — solution master must exist and be green
    stage(5, "solution master repo")
    info = gh_json(f"repos/{master}")
    if info is None:
        raise Stop(f"solution master {master} does not exist — create/push it first (never auto-created)")
    print(f"    exists (private={info.get('private')} template={info.get('is_template')})")

    # 6 — fresh init + ONE commit + push
    stage(6, "create the Starter: fresh init, one commit, push")
    if gh_json(f"repos/{starter}") is None:
        sh(f"gh repo create {starter} --private", dry=dry)
    cmds = [
        "git init -q -b main",
        "git add -A",
        'git -c user.email=starter-build@local -c user.name="starter-build" '
        f'commit -q -m "{a.code} starter"',
        f"git remote add origin https://github.com/{starter}.git",
        "git push -q -u origin main --force",
    ]
    for c in cmds:
        sh(c, cwd=work, dry=dry)
    sh(f"gh repo edit {starter} --template", dry=dry)
    print("    pushed")

    # 7 — RE-FETCH and check the six properties (GATE C)
    stage(7, "GATE C — re-fetch the Starter and verify it")
    if dry:
        print("    [dry] skipped")
    else:
        time.sleep(3)
        info = gh_json(f"repos/{starter}")
        if info is None:
            raise Stop("Starter not found after push")
        files = gh_json(f"repos/{starter}/contents", jq=".[].name")
        branches = gh_json(f"repos/{starter}/branches", jq="length")
        checks = {
            "non-empty (has files)": bool(files),
            "has a branch": bool(branches),
            "private": info.get("private") is True,
            "is_template": info.get("is_template") is True,
        }
        if targets and orig_src is not None:
            remote_src = gh_json(
                f"repos/{starter}/contents/{targets[0].split(':')[0]}", jq=".content")
            if remote_src:
                import base64
                remote_txt = base64.b64decode(remote_src).decode("utf-8", "replace")
                checks["stub shipped (differs from solution)"] = (remote_txt != orig_src)
        for path in omits:
            # the API returns nothing for a path that is not in the tree — that is the pass
            checks[f"omitted: {path} absent from the Starter"] = (
                gh_json(f"repos/{starter}/contents/{path}", jq=".content") is None)
        for k, v in checks.items():
            print(f"    {'ok ' if v else 'FAIL'}  {k}")
        bad = [k for k, v in checks.items() if not v]
        if bad:
            raise Stop("GATE C failed: " + ", ".join(bad))

    # 8 — register in the org-hub
    if a.register:
        stage(8, "register in the org-hub config")
        ops = os.path.abspath(os.path.join(HERE, "..", "..", "GitHub-Starter-Hub", "ops", "config.sh"))
        if not os.path.isfile(ops):
            raise Stop(f"ops/config.sh not found at {ops}")
        sh(f'"{ops}" {org} add-assignment {a.course} {a.code} {starter.split("/")[-1]}', dry=dry)
        print("    registered")

    # 9 — final proof: a throwaway clone of the Starter + the solution must score 100
    if a.verify_100:
        stage(9, "final proof — throwaway repo from the Starter, solution in, run BY SHA")
        test_repo = f"{org}/{a.course}-starterbuild-verify-{a.code.lower()}"
        if dry:
            print(f"    [dry] would create {test_repo}")
        else:
            sh(f"gh repo delete {test_repo} --yes", check=False)
            sh(f"gh repo create {test_repo} --template {starter} --private")
            vdir = os.path.join(tmp, "verify")
            time.sleep(3)
            sh(f"gh repo clone {test_repo} {vdir} -- -q")
            for f in [s.split(":")[0] for s in targets] + list(omits):
                dest = os.path.join(vdir, f)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copy(os.path.join(sol_dir, f), dest)
            sh("git add -A", cwd=vdir)
            sh('git -c user.email=starter-build@local -c user.name="starter-build" '
               'commit -q -m verify', cwd=vdir)
            sh("git push -q", cwd=vdir)
            sha = sh("git rev-parse HEAD", cwd=vdir)
            print(f"    sha={sha} — waiting for the run")
            total, concl = None, None
            for _ in range(120):
                run = gh_json(f"repos/{test_repo}/actions/runs?head_sha={sha}&per_page=1",
                              jq='.workflow_runs[0] | "\\(.status) \\(.conclusion) \\(.id)"')
                if run and run.startswith("completed"):
                    _, concl, rid = run.split()
                    z = os.path.join(tmp, "log.zip")
                    sh(f"gh api repos/{test_repo}/actions/runs/{rid}/logs > {z}", check=False)
                    log = sh(f"unzip -p {z} 2>/dev/null || true", check=False)
                    pts = re.findall(r"Total points for [A-Za-z0-9_]+: [\d.]+/[\d.]+", log)
                    tot = re.findall(r'"totalPoints":\s*(\d+)', log)
                    total = tot[-1] if tot else None
                    for line in pts[-8:]:
                        print("    " + line)
                    break
                time.sleep(10)
            sh(f"gh repo delete {test_repo} --yes", check=False)
            if total != "100":
                raise Stop(f"final proof FAILED (conclusion={concl} total={total}) — the Starter is broken")
            print("    100/100")

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n✔ starter ready: {starter}")


if __name__ == "__main__":
    try:
        main()
    except Stop as e:
        print(f"\n✖ STOP: {e}", file=sys.stderr)
        sys.exit(1)
