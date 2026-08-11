#!/usr/bin/env python3
"""Per-student autograder status for ONE assignment — run locally, get the table now.

The org-hub's `repo-report` workflow builds the same information for a whole school, but it runs on
GitHub Actions (nightly, or a manual dispatch that costs ~1,340 REST calls). This is the local,
one-assignment version: point it at a course + assignment code and it prints student / pass-fail /
score straight to the terminal in a few seconds.

    python3 hw_status.py --course <course> --code A61
    python3 hw_status.py --course <course>   --code A76 --emails
    python3 hw_status.py --course <course> --code A61 --no-names     # skip Canvas, GitHub only

Where the data comes from
    repos   `gh repo list <org>` filtered by the org-hub naming `<course>-<term>-<CODE>-<handle>`
            (LISTED, never constructed — re-accepts produce suffixed variants)
    result  each repo's latest push run: conclusion + `totalPoints/maxPoints` parsed from the run log
    names   Canvas roster, matched to the GitHub handle. The token comes from `canvas_token_auth`
            (env `$<SCHOOL>_CANVAS_TOKEN` -> `Canvas-Auth/<school>.json`) — NEVER from a text file.

Course coordinates (org, canvas base, course id) come from `course_config` — nothing is hardcoded.
"""
from __future__ import annotations

import argparse
import base64
import concurrent.futures as cf
import difflib
import io
import json
import os
import re
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from . import course_config  # noqa: E402

WORKERS = 16


def gh(path, jq=None):
    cmd = ["gh", "api", path] + (["--jq", jq] if jq else [])
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        return None
    out = p.stdout.strip()
    if not out:
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return out


def list_repos(org, course, code):
    """Every student repo for this assignment — listed, then matched. Never name-constructed."""
    p = subprocess.run(["gh", "repo", "list", org, "--limit", "1000", "--json", "name",
                        "--jq", ".[].name"], capture_output=True, text=True)
    pat = re.compile(rf"^{re.escape(course)}-[^-]+-{re.escape(code)}-(.+)$", re.I)
    hits = []
    for name in p.stdout.split():
        m = pat.match(name)
        if m:
            hits.append((name, m.group(1)))
    return sorted(hits)


def autograder(org, repo):
    """(conclusion, 'earned/max') for the repo's latest push run."""
    runs = gh(f"repos/{org}/{repo}/actions/runs?event=push&per_page=1")
    if not runs or not runs.get("workflow_runs"):
        return "— no run", "—"
    run = runs["workflow_runs"][0]
    concl = run.get("conclusion") or run.get("status") or "?"
    label = {"success": "PASS", "failure": "FAIL"}.get(concl, concl)
    score = "—"
    rid = run.get("id")
    if rid:
        p = subprocess.run(["gh", "api", f"repos/{org}/{repo}/actions/runs/{rid}/logs"],
                           capture_output=True)
        if p.returncode == 0 and p.stdout[:2] == b"PK":
            try:
                z = zipfile.ZipFile(io.BytesIO(p.stdout))
                text = "\n".join(z.read(n).decode("utf-8", "replace") for n in z.namelist()[:40])
                tp = re.findall(r'"totalPoints":\s*(\d+)', text)
                mp = re.findall(r'"maxPoints":\s*(\d+)', text)
                if tp and mp:
                    score = f"{tp[-1]}/{mp[-1]}"
            except zipfile.BadZipFile:
                pass
    return label, score


def canvas_roster(slug):
    """{sortable_name: {name, login}} — token via canvas_token_auth, never a file scrape."""
    from .auth.token import get_token
    from .rest import client
    base, env = course_config.canvas_coords(slug)
    cid = course_config.load(slug)["course_id"]
    users = client.get(base, get_token(env, base), f"/courses/{cid}/users",
                       params={"enrollment_type[]": "student", "per_page": 100})
    out = {}
    for u in users:
        n = u.get("sortable_name", "?")
        out[n] = {"name": n, "email": u.get("email", ""),
                  "login": (u.get("login_id") or "").lower(),
                  "tok": re.findall(r"[a-z]+", n.lower())}
    return out


def resolve(handle, roster):
    h = handle.lower()
    best, sc = None, 0.0
    for r in roster.values():
        s = sum(len(t) for t in r["tok"] if len(t) >= 4 and t in h)
        s += difflib.SequenceMatcher(None, h, r["login"].split("@")[0]).ratio()
        if s > sc:
            best, sc = r, s
    return best if sc >= 1.5 else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--course", required=True, help="course slug, e.g. <course> / <course>")
    ap.add_argument("--code", required=True, help="assignment code, e.g. A61")
    ap.add_argument("--emails", action="store_true", help="also print the PASS / FAIL email lists")
    ap.add_argument("--no-names", action="store_true", help="skip Canvas; show GitHub handles only")
    a = ap.parse_args()

    cfg = course_config.load(a.course)
    org = cfg.get("github_org")
    if not org:
        sys.exit(f"course_config['{a.course}'] has no github_org")

    repos = list_repos(org, a.course, a.code)
    if not repos:
        sys.exit(f"no student repos matched {a.course}-*-{a.code}-* in {org}")

    roster = {}
    if not a.no_names:
        try:
            roster = canvas_roster(a.course)
        except Exception as e:            # Canvas is a nicety here — GitHub data still prints
            print(f"(names unavailable: {e})", file=sys.stderr)

    with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        results = list(ex.map(lambda t: autograder(org, t[0]), repos))

    rows = []
    for (repo, handle), (label, score) in zip(repos, results):
        who = handle
        email = ""
        if roster:
            r = resolve(handle, roster)
            if r:
                who, email = r["name"], r["email"]
        rows.append((who, handle, label, score, email))
    rows.sort(key=lambda r: (r[2] != "PASS", r[0].lower()))

    w = max(len(r[0]) for r in rows) + 2
    print(f"\n{a.course} {a.code} — {len(rows)} repos in {org}\n")
    print(f"{'Student'.ljust(w)}{'Handle'.ljust(24)}{'Result'.ljust(10)}Score")
    print("-" * (w + 42))
    for who, handle, label, score, _ in rows:
        print(f"{who.ljust(w)}{handle.ljust(24)}{label.ljust(10)}{score}")
    n_pass = sum(1 for r in rows if r[2] == "PASS")
    print(f"\nPASS {n_pass} · FAIL {sum(1 for r in rows if r[2] == 'FAIL')} · "
          f"other {len(rows) - n_pass - sum(1 for r in rows if r[2] == 'FAIL')}")

    if a.emails and roster:
        for group in ("PASS", "FAIL"):
            mails = [r[4] for r in rows if r[2] == group and r[4]]
            print(f"\n{group} ({len(mails)}):\n  " + ", ".join(mails))


if __name__ == "__main__":
    main()
