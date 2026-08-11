"""View-gate — enforce that EVERY artifact Stage A surfaced was actually READ by
the AI (Stage B) before any grade is posted.

Root fix for the M3Q7 disaster (2026-07-21): the engine DOWNLOADED every submitted
drawing (answer_images/answer_docs were populated), but the AI never opened them and
docked ~9 students' essays for "drawing not re-VIEWED" — then those grades were posted.
The §0Z rule ("VIEW every screenshot/drawing") is not self-enforcing; this makes it
MECHANICAL.

Design (no hook — a hook would sit in the critical path of every Read, taxing latency
and risking a broken Read on any hook bug, and would pollute every other session):
  1. build_manifest(): after Stage A, list every viewable artifact path the engine
     surfaced, deduped → <code>_view_manifest.json.
  2. read_paths(): at POST time, parse the session transcript (.jsonl) ONCE for Read
     tool calls → the set of files the AI actually opened. Zero per-Read overhead.
  3. check(): every manifest artifact must appear in the read set; any that did not =
     "graded without looking" = the poster ABORTS.

The AI must Read the ENGINE-surfaced paths, not a re-downloaded private copy — otherwise
the paths do not match and the gate stops the post. That is the point: view the exact
files the engine gathered.

SECOND HOLE, closed 2026-07-28: the manifest scan matched on FIELD NAMES — only quiz's
`answer_images`/`answer_docs` — while the docstring claimed to be universal. `general`
and `jshell` put screenshots in `review_content.images` + `items[].path`, and `nb` in
`image_paths`, so those assignments produced an EMPTY manifest; check() skips an empty
manifest, so a submission could be posted with not one screenshot opened (real case:
VSC1/VSC2, 33 images). build_manifest now matches on the VALUE — any absolute path to an
existing viewable file, anywhere in the record — so a new grader is covered the day it is
written. Same class of bug as quiz.py never returning `review_content` (empty
ground_truth → zero evidence files), fixed the same day.
"""
import glob
import json
import os
import re
from datetime import datetime

from . import paths as _paths

_VIEW_SUFFIX = ".view.png"   # attachments caches each image twice (raw + <name>.view.png)


def _norm(p):
    """Normalize a path so the two cached copies of one image (raw and .view.png)
    collapse to a single identity, and reading EITHER copy satisfies the manifest.

    PORTABLE (2026-08-05). This is the single choke point every side of the gate passes
    through — the manifest's `artifacts`, the transcript's Read paths, and the stored
    proof's confirmed list. Two of those three are read back from disk, so they can carry
    another machine's home (`Course_Globals` is one Drive folder on two Macs).
    `paths.resolve` re-roots such a path here, once, and every comparison downstream lines
    up. See lib/paths.py."""
    rp = os.path.realpath(_paths.resolve(p))
    if rp.endswith(_VIEW_SUFFIX):
        rp = rp[: -len(_VIEW_SUFFIX)]
    return rp


def _students(grades_json_obj):
    g = grades_json_obj
    return g if isinstance(g, list) else (g.get("students") or [])


def _uid_of(s):
    return s.get("uid") or s.get("user_id")


def _explode_ground_truth(stage_a_grades_json, grades_obj):
    """PER-ITEM (per-student text-evidence) enforcement. Images/docs cover VISUAL
    answers; the textual grading evidence (a student's own code_src / reflection /
    elaboration) lives in the sibling `<code>_ground_truth.json` — but as ONE blob
    keyed by uid, so a single Read of it would falsely 'cover' every student. Here we
    EXPLODE it into one file per student — `<code>_evidence/<uid>.txt` — so the gate
    can require the AI to have opened EACH graded student's own evidence before posting
    (the M1QP1/Will hole: a copied score with the 2nd attempt never read). Returns the
    list of per-student evidence paths to add to the manifest (only students that have
    real text evidence — a pure-drawing answer has none and is covered by images)."""
    d = os.path.dirname(os.path.abspath(stage_a_grades_json))
    # THE CODE LABEL IS DATA — core.py writes `code` into the record's envelope. Read it, and
    # treat the filename as a fallback only. Chopping a fixed `"_grades.json"` suffix off the
    # name silently produced a wrong label the moment the record was renamed (and a wrong label
    # means the ground-truth file is not found, which turns this per-student gate OFF quietly).
    code = grades_obj.get("code") if isinstance(grades_obj, dict) else None
    if not code:
        stem = os.path.splitext(os.path.basename(stage_a_grades_json))[0]
        code = re.sub(r"_grades?(_[A-Za-z0-9]+)?$", "", stem) or stem
    # ground_truth is a REPORT-side artifact: it lives in grade_result/, one level above the
    # record's json/ folder. Accept either location so both layouts resolve.
    gt_path = next((p for p in (os.path.join(d, f"{code}_ground_truth.json"),
                                os.path.join(os.path.dirname(d), f"{code}_ground_truth.json"))
                    if os.path.exists(p)), None)
    if not gt_path:
        return []
    gt = json.load(open(gt_path))
    ev_dir = os.path.join(os.path.dirname(gt_path), f"{code}_evidence")
    os.makedirs(ev_dir, exist_ok=True)
    paths = []
    for s in _students(grades_obj):
        uid = _uid_of(s)
        if uid is None:
            continue
        rec = gt.get(str(uid)) or gt.get(uid) or {}
        code_src = (rec.get("code_src") or "").strip()
        refl = (rec.get("reflection") or "").strip()
        if not code_src and not refl:
            continue  # no text evidence (e.g. pure-drawing quiz answer) → images cover it
        body = f"# {code} — evidence for uid {uid}\n\n## code_src\n{code_src}\n\n## reflection / elaboration\n{refl}\n"
        p = os.path.join(ev_dir, f"{uid}.txt")
        with open(p, "w") as fh:
            fh.write(body)
        paths.append(_norm(p))
    return paths


# Extensions of artifacts a human must LOOK AT (or the engine extracted for looking at).
# Text the AI already receives inline is covered by the ground_truth evidence file instead.
_VIEWABLE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff",
                 ".pdf", ".docx", ".pptx", ".xlsx")


def _walk_artifact_paths(obj, out, seen=None):
    """Recursively collect every LOCAL viewable-artifact path in a student record.

    FIELD-NAME-AGNOSTIC ON PURPOSE (2026-07-28). Graders do not agree on where they put
    screenshots: quiz → `answer_images`/`answer_docs`, general & jshell → `images` +
    `items[].path`, nb → `image_paths`, gh → `screenshot_urls` (Canvas URLs, not local).
    build_manifest used to look ONLY at quiz's two field names while its own docstring
    claimed to be "universal" — so a `general`-graded assignment produced an EMPTY
    manifest, and view_gate.check() skips an empty manifest, meaning a submission could
    be posted without a single screenshot ever being opened.

    Matching on the VALUE (an absolute path to a viewable file that exists) instead of on
    the key name means a new grader is covered the day it is written, with no edit here.
    Canvas URLs are ignored — they are not Read-able paths; the engine's local copy is.
    """
    if seen is None:
        seen = set()
    if isinstance(obj, dict):
        if id(obj) in seen:
            return
        seen.add(id(obj))
        for v in obj.values():
            _walk_artifact_paths(v, out, seen)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _walk_artifact_paths(v, out, seen)
    elif isinstance(obj, str):
        s = obj.strip()
        if (s.startswith("/") and s.lower().endswith(_VIEWABLE_EXT)
                and os.path.isfile(s)):
            out.add(_norm(s))


def build_manifest(stage_a_grades_json, out_path):
    """Scan the Stage-A grades.json for every artifact the AI must have READ before a
    grade can be posted, write the deduped normalized list to out_path, return it:

      - VISUAL answers: EVERY local viewable artifact found anywhere in the student
        record (images, PDFs, Office docs) — matched by value, not by field name, so it
        covers every grader (see _walk_artifact_paths for why).
      - TEXTUAL grading evidence (PER-ITEM enforcement): the student's own code_src /
        reflection, exploded from `<code>_ground_truth.json` to one `<uid>.txt` per
        graded student (see _explode_ground_truth). Closes the text-assignment hole
        where an unread submission could still be posted (only images were gated before).

    Now genuinely universal: a grader is covered if it surfaces a local artifact path or
    writes a ground_truth — no per-grader field list to keep in sync."""
    g = json.load(open(stage_a_grades_json))
    want = set()
    for s in _students(g):
        # Whole record: top level + attempts + needs_ai_essay + review_content + items…
        _walk_artifact_paths(s, want)
    for p in _explode_ground_truth(stage_a_grades_json, g):
        want.add(p)
    manifest = sorted(want)
    # SELF-DESCRIBING (2026-07-30): the manifest says WHOSE it is. The poster can then
    # verify it belongs to the grades.json in hand instead of matching on file name —
    # name-matching is what silently disabled the gate when the file was named differently.
    # RUN ID — identifies the GATHER, not the conversation (2026-08-02). The proof of reading
    # used to be re-earned on every render, because the render re-parsed the live transcript:
    # fix one sentence in a comment a day later and 78 artifacts had to be opened again to say
    # something nobody disputed. Reading is a fact about MATERIAL, so bind it to the material.
    # This manifest is rebuilt only by grade_skill, once per Stage-A gather, so the id changes
    # exactly when the artifacts do — a re-gather invalidates the proof (correct: new files), a
    # re-render does not (also correct: the same files, already read).
    _code = (g.get("code") if isinstance(g, dict) else None)
    _built = datetime.now().isoformat(timespec="seconds")
    _runs = (g.get("stage_a_runs") if isinstance(g, dict) else None)
    # STORED FOLDED (2026-08-05) — `~/…` instead of this machine's absolute home, so the same
    # manifest reads correctly on either Mac sharing this Drive folder. Reads go back through
    # `_norm`, which resolves `~` before comparing, so nothing downstream changes. lib/paths.py
    json.dump({"code": _code,
               "grades_json": _paths.fold(stage_a_grades_json),
               "built_at": _built,
               "run_id": f"{_code}#{_runs}@{_built}",
               "artifacts": [_paths.fold(p) for p in manifest]},
              open(out_path, "w"), indent=1)
    return manifest


def _walk_read_paths(obj, out):
    """Recursively find every Read tool_use's file_path inside a transcript record."""
    if isinstance(obj, dict):
        if obj.get("type") == "tool_use" and obj.get("name") == "Read":
            fp = (obj.get("input") or {}).get("file_path")
            if fp:
                out.add(_norm(fp))
        for v in obj.values():
            _walk_read_paths(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _walk_read_paths(v, out)


def read_paths(transcript_path):
    """Parse a session .jsonl → set of normalized file_paths the AI opened with Read."""
    seen = set()
    with open(transcript_path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            _walk_read_paths(rec, seen)
    return seen


def find_transcript(hint_path=None):
    """Locate the CURRENT session transcript = the newest .jsonl in this project's
    ~/.claude/projects/<mangled-project-root>/ dir. `hint_path` is any path INSIDE the
    project (the poster passes the grades.json dir); DEFAULT is cwd. The transcript
    folder is the mangled PROJECT ROOT, which is a PREFIX of the mangled form of any
    subpath (e.g. .../<course> is a prefix of .../<course>/.claude/output/...), so we
    match the projects/ folder whose name is the longest prefix of the mangled hint —
    this works whether the caller runs from the code dir or the output dir. Returns None
    if none found (caller then FAILS CLOSED / needs an explicit --transcript)."""
    base = os.path.expanduser("~/.claude/projects")
    if hint_path is None:
        hint_path = os.getcwd()
    mangled = "".join(c if c.isalnum() else "-" for c in os.path.realpath(hint_path))
    exact = os.path.join(base, mangled)
    dirs = [exact] if os.path.isdir(exact) else []
    # EVERY matching prefix, longest first — not just the longest one (fixed 2026-08-01).
    # Taking only the most specific match silently returned None whenever that directory
    # existed but was EMPTY, which happens as soon as anyone has ever started a session from
    # a subfolder: `…/<course>--claude-output-grade-result` (0 transcripts) outranked
    # `…/<course>` (11 transcripts), so the gate reported "session transcript not found" and
    # blocked a post whose evidence was sitting right there. Specificity is still preferred;
    # it just no longer excludes the fallback.
    dirs += [os.path.join(base, d) for d in sorted(
        (d for d in os.listdir(base)
         if os.path.isdir(os.path.join(base, d)) and mangled.startswith(d)),
        key=len, reverse=True)]
    for d in dirs:                      # first directory that actually HAS a transcript wins
        files = glob.glob(os.path.join(d, "*.jsonl"))
        if files:
            return max(files, key=os.path.getmtime)
    return None


def check(manifest_path, transcript_path):
    """Return the list of manifest artifacts NOT found in the AI's Read set. Empty =
    everything was viewed (gate passes). Non-empty = graded without looking → ABORT."""
    want = json.load(open(manifest_path)).get("artifacts", [])
    seen = read_paths(transcript_path)
    return [p for p in want if _norm(p) not in seen]


def verify_and_stamp(manifest_path, transcript_path, out_path, grades_path=None):
    """Freeze the proof-of-reading to disk so POST-READY OUTLIVES THE SESSION.

    THE DEFECT THIS FIXES (2026-08-01). `check()` measures reading by parsing the CURRENT
    session transcript. So the record and the manifest are permanent files, but the proof
    that the manifest was satisfied died with the conversation: six assignments graded to
    post-ready could not be posted from a later session, because the Read calls lived in a
    .jsonl nobody was looking at any more. "Post-ready" was a property of the artifacts PLUS
    the chat that made them. A finished grading is a fact on disk; it has to be storable.

    Called at RENDER time (report_generator), i.e. in the same session that did the reading
    and immediately after it. Verifies against the live transcript exactly as `check()` does,
    and only if NOTHING is unread writes `<code>_view_verified.json`:

        {code, manifest, grades_json, verified_at, transcript, artifacts:[…confirmed…]}

    Returns (unread_list, out_path_or_None). Unread non-empty ⇒ nothing is written; there is
    no partial credit and no way to stamp a gate you did not pass.

    ⛔ WRITTEN BY CODE, NEVER BY THE AI. `ViewGate.md`: "a null it can write is a gate it can
    switch off." The AI must never be able to put this field in an authoring file — the same
    anti-pattern that got `_quote_candidates` deleted the same day (it handed the AI
    gate-passing values). The renderer produces it from a real transcript parse or not at all.
    """
    man = json.load(open(manifest_path))
    want = man.get("artifacts", [])
    seen = read_paths(transcript_path)
    unread = [p for p in want if _norm(p) not in seen]
    if unread:
        return unread, None
    # STORED FOLDED — see build_manifest. check_verified compares through _norm, which
    # resolves `~` (and a foreign home) before matching, so both notations still bind.
    json.dump({"code": man.get("code"),
               "manifest": _paths.fold(manifest_path),
               # WHICH GATHER was read. The proof stays valid for as long as the manifest still
               # carries this id — i.e. until Stage A runs again and the artifacts change.
               "run_id": man.get("run_id"),
               "grades_json": _paths.fold(grades_path) if grades_path
                              else man.get("grades_json"),
               "verified_at": datetime.now().isoformat(timespec="seconds"),
               "transcript": _paths.fold(transcript_path),
               "artifacts": sorted(_paths.fold(_norm(p)) for p in want)},
              open(out_path, "w"), indent=1)
    return [], out_path


def check_verified(manifest_path, verified_path, grades_path):
    """POST-time alternative to `check()` when the session that graded is gone. Returns the
    list of manifest artifacts NOT covered by the stored proof — empty means the gate passes.

    Every binding is re-checked here rather than trusted, because this file is the one thing
    standing between an unread submission and a posted grade:
      - the proof must name THIS grades.json (a stale or borrowed proof cannot stand in),
      - the proof must name THIS manifest,
      - and every artifact the manifest demands must appear in the proof's confirmed list.
    Anything missing ⇒ the manifest entry is reported unread ⇒ the poster aborts, exactly as
    if the transcript had been searched and come up short."""
    man = json.load(open(manifest_path))
    want = [_norm(p) for p in man.get("artifacts", [])]
    try:
        v = json.load(open(verified_path))
    except (OSError, ValueError):
        return want
    # RUN ID IS THE BINDING THAT MATTERS. When both sides carry one, it decides: same gather =>
    # same files => the reading still stands, whatever the file paths or the session were.
    # A mismatch is a re-gather, so the proof is void even if every path still lines up.
    if v.get("run_id") and man.get("run_id"):
        if v["run_id"] != man["run_id"]:
            return want
    else:
        # Older proofs have no id — fall back to the path bindings they were written with.
        # Both sides through _norm: the stored side may name another machine's home, and a
        # raw realpath comparison would then reject a proof that is perfectly valid here.
        if v.get("grades_json") and _norm(v["grades_json"]) != _norm(grades_path):
            return want
        if v.get("manifest") and _norm(v["manifest"]) != _norm(manifest_path):
            return want
    have = {_norm(p) for p in v.get("artifacts", [])}
    return [p for p in want if p not in have]
