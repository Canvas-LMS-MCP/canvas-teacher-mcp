"""course_config — the ONE reader for a course's coordinates.

Design + rationale: `CourseGlobalWorkflow/Where/CourseConfig.md`. Usage recipe: `code/README.md`.

STORED per course (5 fields): `canvas_url, school, pages_folder, db_path, github_org`.
  · NEW home  : `<school>/<org>/<COURSE>/.claude/course-config/<slug>.json`   (per-course, target)
  · OLD home  : `code/grade_engine/config/<slug>.json`  (14-field, read during migration)
Everything else is DERIVED (course_id/base_url/domain from `canvas_url`; token_env from `school`)
or a fixed RULE — a course config NEVER pre-declares an assignment type (that lives in grading).

    load(slug|course_id|url) -> normalized dict (stored + derived + legacy keys)
    canvas_coords(x)         -> (base_url, token_env)  the two things a Canvas call needs
    course_id/base_url/domain/school/token_env/github_org/pages_folder/db_path(x) -> that field

Registration is not a precondition for reaching a course. Authentication is per SCHOOL, so a
course on a registered school's domain resolves whether anyone registered it or not: `load`
SYNTHESIZES coordinates for it, marked `registered: False`, with an output_dir under the root
instead of under a course folder. Registration is what earns a slug, a folder, and the fields
only an instructor can supply (`db_path`, `github_org`, `pages_folder`); a caller needing one of
those then fails naming THAT field, which says what to do — unlike "course not registered".

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

from .canvas_root import root  # the tree root comes from the environment


def _course_glob():
    return os.path.join(str(root()), "*", "**", ".claude", "course-config", "*.json")


def _domain_of(s):
    m = re.search(r"https?://([^/]+)", s or "")
    return m.group(1) if m else None


def _safe(name):
    """A path segment from a Canvas-supplied name — no separators, no surprises."""
    return re.sub(r"[^A-Za-z0-9._-]", "-", name)


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
    out.setdefault("registered", True)     # a file on disk IS the registration; load() overrides
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


def _fetch_course(base_url, domain, course_id):
    """The course's own name and code, read from Canvas. Credentials resolve by domain."""
    from .auth.token import get_token, whoami  # noqa: PLC0415 — keep this module importable
    import urllib.request                      #   without credentials

    token = get_token("%s_CANVAS_TOKEN" % domain.split(".")[0].upper(), base_url=base_url)
    whoami(base_url, token)                                # fail early, with a clear reason
    req = urllib.request.Request("%s/courses/%s" % (base_url, course_id),
                                 headers={"Authorization": "Bearer %s" % token})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def register_course(course_url, *, slug=None, course_dir=None, school=None, course_code=None):
    """Write a course's config from its Canvas URL. See `Where/CourseConfig.md`.

    Everything is PROPOSED and overridable, because only the instructor knows the tree's shape:
      slug        <- the course code, lowercased
      course_dir  <- <ROOT>/<SCHOOL>/<COURSE_CODE>
      school      <- the domain's first label; one domain can serve several colleges, so this
                     is a guess the instructor confirms

    The school goes in the PATH, not only inside the file. Every wrong-school incident this
    project has had was a coordinate that looked right because nobody could see it; a folder
    name is seen without opening anything. Deeper trees are fine — `_index()` does not care how
    many levels there are — so a tree that groups by department passes `course_dir` and keeps it.

    An existing config is never overwritten, and a slug already registered ANYWHERE is refused:
    `_index()` is a slug -> path dict, so a second file with the same stem would decide the
    course by glob order.

    Returns {"status": "registered" | "already_registered", "path", "slug", "course_dir",
             "school", "course_code", "name"}.
    """
    domain = _domain_of(course_url)
    course_id = _course_id_of(course_url)
    if not domain or not course_id:
        raise ValueError("not a Canvas course URL: %r (want https://<domain>/courses/<id>)"
                         % course_url)
    base_url = "https://%s/api/v1" % domain

    if not course_code:
        info = _fetch_course(base_url, domain, course_id)
        course_code = info.get("course_code") or info.get("name") or str(course_id)
        name = info.get("name")
    else:
        name = course_code

    slug = (slug or re.sub(r"[^a-z0-9]", "", course_code.lower()) or str(course_id))
    school = school or domain.split(".")[0]
    course_dir = course_dir or os.path.join(str(root()), _safe(school.upper()),
                                            _safe(course_code))
    if not os.path.isabs(course_dir):
        course_dir = os.path.join(str(root()), course_dir)

    # The slug is the key every tool passes, so it has to be unique across the whole tree —
    # not merely absent from the directory we happen to be writing to.
    held = _index().get(slug)
    path = os.path.join(course_dir, ".claude", "course-config", "%s.json" % slug)
    if held or os.path.exists(path):
        return {"status": "already_registered", "path": held or path, "slug": slug,
                "course_dir": course_dir, "school": school, "course_code": course_code,
                "name": name}

    # Store the course's address, not the page the instructor happened to be looking at:
    # `…/courses/<id>/modules` parses to the same id but says something untrue, and two
    # registrations of one course would then disagree on what its URL is.
    canvas_url = "https://%s/courses/%s" % (domain, course_id)

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump({"canvas_url": canvas_url, "school": school}, f, indent=2)
        f.write("\n")
    return {"status": "registered", "path": path, "slug": slug, "course_dir": course_dir,
            "school": school, "course_code": course_code, "name": name}


def _registered_schools():
    """{school: domain} for every school that has a credential file, read from the file's own
    base_url. The filename is a human label — a school on its own domain would not survive
    being rebuilt from it."""
    out = {}
    auth = root() / ".claude" / "Canvas-Auth"
    if not auth.is_dir():
        return out
    for p in sorted(auth.glob("*.json")):
        try:
            dom = _domain_of(json.loads(p.read_text()).get("base_url"))
        except Exception:                                       # noqa: BLE001 — skip a damaged file
            continue
        if dom:
            out[p.stem] = dom
    return out


def _unregistered(course_id, domain=None):
    """Coordinates for a course nobody registered. Same shape as a stored config, minus what
    only registration supplies, and `registered: False` so a caller can tell.

    With no domain (a bare id), the school is unambiguous only when exactly one is registered.
    Two schools and a bare number cannot say which, and guessing picks someone's Canvas at
    random — so it raises and asks for the URL instead.
    """
    schools = _registered_schools()
    if domain:
        school = next((s for s, d in schools.items() if d == domain), domain.split(".")[0])
    elif len(schools) == 1:
        school, domain = next(iter(schools.items()))
    elif not schools:
        raise KeyError("no school is registered, so course %s cannot be reached. Register the "
                       "school first with its Canvas URL." % course_id)
    else:
        raise KeyError("course %s is not registered and %d schools are (%s), so which Canvas it "
                       "lives on is unknown. Give the full course URL, or register the course."
                       % (course_id, len(schools), ", ".join(sorted(schools))))
    out = {"canvas_url": "https://%s/courses/%s" % (domain, course_id),
           "school": school, "registered": False,
           "output_dir": os.path.join(str(root()), ".claude", "output", str(course_id))}
    return _normalize(out, os.path.join(str(root()), "%s.json" % course_id))


def load(course):
    """Normalized config dict for a course. `course` = a slug, a Canvas course_id, or a course URL.

    A registered course is read from its file. An unregistered one is SYNTHESIZED — reaching a
    course needs the school's credential, not a config (`Where/CourseConfig.md`). Raises rather
    than defaulting whenever the answer would be a guess.
    """
    s = str(course).strip().lower()
    idx = _index()
    if s in idx:
        return _read(idx[s])

    url_id, domain = _course_id_of(s), _domain_of(s)
    want = url_id if url_id else (int(s) if s.isdigit() else None)
    if want is None:
        raise KeyError("no course config for %r, and it is neither a Canvas id nor a course URL. "
                       "Known: %s." % (course, ", ".join(slugs()) or "none"))

    for slug, p in idx.items():                                 # a registered course, by its id
        cfg = _read(p)
        if cfg.get("course_id") == want:
            return cfg
    return _unregistered(want, domain)


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


def _instructor_field(course, key):
    """A field only registration can supply. Absent because the course was never registered is a
    different answer from absent because the instructor left it out, and only the first one tells
    the caller what to do."""
    cfg = load(course)
    if cfg.get(key) is None and not cfg.get("registered", True):
        raise KeyError("%s is unknown for course %s: it is not registered, and %s is a field "
                       "registration supplies. Register it to set one."
                       % (key, cfg.get("course_id"), key))
    return cfg.get(key)


def github_org(course):
    return _instructor_field(course, "github_org")


def db_path(course):
    return _instructor_field(course, "db_path")


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
        import sys as _sys
        _sk = os.path.join(str(root()), ".claude", "skills", "gws-richdoc")
        if _sk not in _sys.path:
            _sys.path.insert(0, _sk)
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
