"""course_config — the ONE reader for a course's coordinates.

Design + rationale: `CourseGlobalWorkflow/Where/CourseConfig.md`. Usage recipe: `code/README.md`.

STORED per course (5 fields): `canvas_url, school, pages_folder, db_path, github_org`.
  · NEW home  : `<school>/<org>/<COURSE>/.claude/course-config/<slug>.json`   (per-course, target)
  · OLD home  : `code/grade_engine/config/<slug>.json`  (14-field, read during migration)
Everything else is DERIVED (course_id/base_url/domain from `canvas_url`; token_env from `school`)
or a fixed RULE — a course config NEVER pre-declares an assignment type (that lives in grading).

    load(slug|course_id)  -> normalized dict (stored + derived + legacy keys)
    canvas_coords(x)      -> (base_url, token_env)     the two things a Canvas call needs
    course_id/base_url/domain/school/token_env/github_org/pages_folder/db_path(x) -> that field

Why here: canvas_rest / canvas_core must stay course-agnostic; a course identity is not a Canvas
resource. Everything under `code/` and the global skills import THIS — do not copy it.

`school` is STORED, not derived: a school name is not its Canvas subdomain, and one subdomain can
serve several colleges, so the URL cannot yield it.
"""
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from .canvas_root import root  # noqa: E402  — the tree root comes from the environment


def _course_glob():
    return os.path.join(str(root()), "*", "**", ".claude", "course-config", "*.json")


def _domain_of(s):
    m = re.search(r"https?://([^/]+)", s or "")
    return m.group(1) if m else None


def _course_id_of(url):
    m = re.search(r"/courses/(\d+)", url or "")
    return int(m.group(1)) if m else None


def _semester_of(db):
    m = re.search(r"-([A-Za-z]{2}\d{2})\.db$", db or "")
    return m.group(1).lower() if m else None


def _normalize(cfg, path):
    """Return a dict with the canonical fields AND every derived/legacy key a consumer expects.
    Accepts a NEW 5-field per-course file or an OLD 14-field file — both come out uniform.
    `path` locates a new file's course dir (for output_dir); old files keep their stored value."""
    out = dict(cfg)
    slug = os.path.basename(path)[:-5].lower()
    for k in ("db_path", "sqlite_db_path", "output_dir"):       # configs store $HOME/… — expand once
        if out.get(k):
            out[k] = os.path.expandvars(out[k])
    # canvas_url: new files store it; old files → synthesize from base_url + course_id
    url = out.get("canvas_url")
    if not url and out.get("canvas_base_url") and out.get("course_id"):
        url = "https://%s/courses/%s" % (_domain_of(out["canvas_base_url"]), out["course_id"])
        out["canvas_url"] = url
    # derived from canvas_url
    if url:
        dom = _domain_of(url)
        if out.get("course_id") is None:
            out["course_id"] = _course_id_of(url)
        out.setdefault("domain", dom)
        out.setdefault("canvas_base_url", "https://%s/api/v1" % dom)
    # token_env derived from school (verified vs all configs: <SCHOOL>_CANVAS_TOKEN)
    if out.get("school"):
        out.setdefault("canvas_token_env", "%s_CANVAS_TOKEN" % out["school"].upper())
    # db_path: new key; old files used sqlite_db_path
    if not out.get("db_path") and out.get("sqlite_db_path"):
        out["db_path"] = out["sqlite_db_path"]
    # ── legacy keys DERIVED, so a consumer that still reads them keeps working ──
    out.setdefault("course_slug", slug)
    if not out.get("output_dir"):
        # file lives at <course>/.claude/course-config/<slug>.json → course dir is 3 up
        course_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(path))))
        out["output_dir"] = os.path.join(course_dir, ".claude", "output")
    # `sqlite_db_path` is the OLD name for `db_path`; grade_engine still asks for it. Alias
    # both ways so neither name can silently resolve to None (a missing db_path opens no DB
    # and the grade DB writes vanish without an error).
    if out.get("db_path"):
        out.setdefault("sqlite_db_path", out["db_path"])
    sem = out.get("semester") or _semester_of(out.get("db_path"))
    if sem:
        out.setdefault("semester", sem)
        out.setdefault("repo_prefix", "%s-%s" % (slug, sem))
    out.setdefault("request_form", "request-%s.yml" % slug)
    return out


def _read(path):
    with open(path) as f:
        return _normalize(json.load(f), path)


def _index():
    """slug -> config path, from the per-course files ONLY; slug = filename stem.

    The dual-read (old `grade_engine/config/*.json` first, new files overriding) was the
    migration bridge. It ended 2026-07-28: every course carries its own file and the old dir
    is gone. Keeping the fallback after that point would be worse than useless — a course
    whose per-course file went missing would silently fall back to a stale 14-field copy
    instead of raising, which is exactly the "no silent default" rule this module enforces.
    """
    return {os.path.basename(p)[:-5].lower(): p
            for p in glob.glob(_course_glob(), recursive=True)}


def slugs():
    """Every course slug that has a config (new or old)."""
    return sorted(_index())


def load(course):
    """Normalized config dict for a course. `course` = a slug OR a Canvas course_id.
    Raises KeyError with the known slugs on no match — never a silent default."""
    s = str(course).strip().lower()
    idx = _index()
    if s in idx:
        return _read(idx[s])
    if s.isdigit():                                             # given a Canvas id — find whose it is
        want = int(s)
        for slug, p in idx.items():
            cfg = _read(p)
            if cfg.get("course_id") == want:
                return cfg
    raise KeyError("no course config for %r. Known: %s. A new course needs a 5-field "
                   "<slug>.json (Where/CourseConfig.md)." % (course, ", ".join(slugs())))


def canvas_coords(course):
    """(canvas_base_url, canvas_token_env) — what any Canvas call needs. Course-agnostic pair for
    canvas_rest / canvas_token_auth.get_token."""
    cfg = load(course)
    return cfg["canvas_base_url"], cfg["canvas_token_env"]


def course_id(course):
    return load(course)["course_id"]


def base_url(course):
    return load(course)["canvas_base_url"]


def domain(course):
    return load(course)["domain"]


def school(course):
    return load(course)["school"]


def token_env(course):
    return load(course)["canvas_token_env"]


def github_org(course):
    return load(course).get("github_org")


def db_path(course):
    return load(course).get("db_path")


# ── Drive folders — ALL OPTIONAL. A course may store a parent `drive_folder`; Pages/Slides are
# named subfolders derived from it. Everything here returns None when absent — NEVER an error.
# A consumer that needs a folder and gets None asks the user "where should I save this?".
def drive_folder(course):
    """The course's parent Google Drive folder id, or None if the course didn't set one."""
    return load(course).get("drive_folder")


def _subfolder_id(parent_id, name):
    """id of the `name` subfolder inside `parent_id`, or None (no parent / no such subfolder /
    Drive unreachable). Best-effort — never raises."""
    if not parent_id:
        return None
    try:
        from .richdoc import build  # gws-richdoc's gws client
        q = ("'%s' in parents and mimeType='application/vnd.google-apps.folder' and "
             "name='%s' and trashed=false" % (parent_id, name))
        files = build._gws(["drive", "files", "list"],
                           params={"q": q, "fields": "files(id,name)"}).get("files", [])
        return files[0]["id"] if files else None
    except Exception:      # noqa: BLE001 — folders are optional; a lookup failure is just "None"
        return None


def pages_folder(course):
    """id of the folder gdocs go in, or None. Level-robust + back-compat:
      · new file: `drive_folder`'s `Pages` subfolder if present, else `drive_folder` itself.
      · old file: the legacy `pages_folder` key (whatever level it already pointed at).
    None only when the course set no folder at all — the consumer then asks the user."""
    cfg = load(course)
    parent = cfg.get("drive_folder")
    if parent:
        return _subfolder_id(parent, "Pages") or parent
    return cfg.get("pages_folder")           # legacy old-file key


def slides_folder(course):
    """id of the `Slides` subfolder under the course's drive_folder, or None (optional)."""
    return _subfolder_id(drive_folder(course), "Slides")
