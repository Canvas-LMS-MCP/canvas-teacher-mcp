"""System tools — the workflow documents, and what the install still needs.

`get_doc` exists because a skill references `GRADING.md` and the page formats, and a client
with no filesystem has no other way in.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from ..canvas_root import ROOT_MISSING, root

TOOLS = ("get_doc", "setup")

# Shipped copy. Inside the package directory, so one path works from a source checkout and from
# an installed wheel alike.
_PACKAGE_WORKFLOW = Path(__file__).resolve().parent.parent / "_data" / "workflow"


def _workflow_dir() -> Path | None:
    try:
        tree = root() / ".claude" / "CourseGlobalWorkflow"
    except Exception:  # noqa: BLE001 — no root yet is a normal pre-setup state
        tree = None
    if tree is not None and tree.is_dir():
        return tree
    return _PACKAGE_WORKFLOW if _PACKAGE_WORKFLOW.is_dir() else None


def get_doc(path: str) -> str:
    """Read a workflow document, e.g. `GRADING.md` or `Access/Canvas.md`.

    `path` is relative to CourseGlobalWorkflow/.
    """
    base = _workflow_dir()
    if base is None:
        return "No workflow directory yet. Run `setup` first."
    target = (base / path).resolve()
    if not target.is_relative_to(base.resolve()):
        raise ValueError(f"{path} points outside the workflow directory")
    if not target.is_file():
        available = sorted(p.name for p in base.iterdir())
        return f"No such document: {path}. Top level holds: {', '.join(available)}"
    return target.read_text(encoding="utf-8")


def setup(canvas_url: str | None = None, token: str | None = None,
          course_url: str | None = None, slug: str | None = None,
          course_dir: str | None = None) -> str:
    """Set this install up, one step per call. Relay the answer to the instructor.

    Call with no arguments to see where things stand. Pass `canvas_url` to register a SCHOOL —
    that writes the config with an empty token and reports the file to paste one into; pass
    `token` as well only if the instructor prefers that, since the token then stays in this
    conversation's record. Pass `course_url` to register a COURSE, optionally overriding the
    proposed `slug` and `course_dir`.
    """
    from ..auth import token as token_auth

    try:
        tree = root()
    except Exception:  # noqa: BLE001 — the requirement is the answer
        return (
            ROOT_MISSING
            + "\n\nUntil then the skill tools and get_doc still work — they read the copy inside "
              "this package — but nothing can reach Canvas."
        )

    if canvas_url:
        return _register(token_auth, canvas_url, token)

    if course_url:
        return _register_course(course_url, slug, course_dir)

    problem = _root_problem(tree)
    if problem:
        return problem

    lines = [f"course root: {tree}" + ("" if tree.is_dir() else "  (does not exist yet — the "
                                       "first registration creates it)")]
    for label, path in (
        ("skills", tree / ".claude" / "skills"),
        ("workflow", tree / ".claude" / "CourseGlobalWorkflow"),
    ):
        lines.append(f"{label}: {'in the course root' if path.is_dir() else 'read from this package'}")

    auth = tree / ".claude" / "Canvas-Auth"
    schools = sorted(p.stem for p in auth.glob("*.json")) if auth.is_dir() else []
    if not schools:
        lines += [
            "schools: none registered",
            "",
            "Next: ask the instructor for their Canvas address — the one they log in at, e.g. "
            "https://myschool.instructure.com — and call setup again with canvas_url set.",
        ]
        return "\n".join(lines)

    finished = _finish_pending(auth)     # a token arrived; the course it was waiting on can go in
    lines.append("schools: " + ", ".join(schools))
    for path in sorted(auth.glob("*.json")):
        # The file's own base_url, never a domain rebuilt from the filename — the filename is a
        # label, and a school on its own domain would not survive the round trip.
        try:
            cfg = json.loads(path.read_text())
            if not cfg.get("token"):
                lines.append(f"  {path.stem}: waiting for a token in {path}")
                continue
            identity = token_auth.whoami(cfg["base_url"], cfg["token"])
            lines.append(f"  {path.stem}: signed in as {identity.get('name')}")
        except Exception as exc:  # noqa: BLE001 — per-school status, not a failure of setup
            lines.append(f"  {path.stem}: not usable yet — {exc}")

    if finished:
        lines += ["", "courses that were waiting on a token:"] + finished
    lines += _course_status()
    lines += [
        "",
        "Skills and the workflow work whether or not they are copied into the course root. "
        "Copy them only to CHANGE them: the packaged copy is replaced on every version update, "
        "so an edit there is lost, while an edit in the course root survives.",
    ]
    return "\n".join(lines)


def _remember_pending(auth_path, course_url: str) -> None:
    """Hold the course URL beside the credential it is waiting on.

    The instructor gave the URL once; asking for it again after the token would be asking for
    something already said. Removed as soon as the course registers.
    """
    p = Path(auth_path)
    cfg = json.loads(p.read_text())
    cfg["pending_course_url"] = course_url
    p.write_text(json.dumps(cfg, indent=2) + "\n")
    os.chmod(p, 0o600)


def _finish_pending(auth: Path) -> list:
    """Register any course that was waiting on a token that has since arrived."""
    from .. import course_config

    out = []
    for path in sorted(auth.glob("*.json")):
        try:
            cfg = json.loads(path.read_text())
        except Exception:  # noqa: BLE001 — a damaged credential is reported by the school loop
            continue
        url = cfg.get("pending_course_url")
        if not url or not cfg.get("token"):
            continue
        try:
            result = course_config.register_course(url)
        except Exception as exc:  # noqa: BLE001 — say why, leave the URL for the next attempt
            out.append(f"  {path.stem}: {url} still not registered — {exc}")
            continue
        cfg.pop("pending_course_url")
        path.write_text(json.dumps(cfg, indent=2) + "\n")
        os.chmod(path, 0o600)
        out.append("  %s: registered %s as '%s' — %s"
                   % (path.stem, result.get("course_code"), result["slug"], result["path"]))
    return out


def _root_problem(tree) -> str | None:
    """A root that cannot hold a tree, said now rather than as a failure three calls later."""
    if tree.exists() and not tree.is_dir():
        return (f"The course root {tree} is a file, not a folder. Point CANVAS_LMS_ROOT at a "
                "folder in this client's server declaration, then restart the client.")
    probe = tree if tree.is_dir() else tree.parent
    if probe.is_dir() and not os.access(probe, os.W_OK):
        return (f"The course root {tree} is not writable, so no course or credential can be "
                "stored there. Choose a writable folder in this client's server declaration, or "
                "fix the folder's permissions, then restart the client.")
    return None


def _course_status() -> list:
    """Registered courses, and what to do when there are none.

    A course is not required to READ Canvas — an unregistered one resolves from its URL — but it
    is what gives the tools a slug, a folder for output, and the instructor-supplied fields. The
    schools branch above says what to do next when it is empty; this says the same for courses,
    because a status report that ends after 'signed in as …' reads as 'nothing left to do'.
    """
    from .. import course_config

    try:
        known = course_config.slugs()
    except Exception:  # noqa: BLE001 — a root that cannot be listed is reported above
        return []
    if not known:
        return ["courses: none registered",
                "",
                "Next: ask the instructor for the course's Canvas URL — the address bar on the "
                "course, e.g. https://myschool.instructure.com/courses/12345 — and call setup "
                "again with course_url set. Reading a course works from its URL without this; "
                "registering is what gives it a short name and a folder of its own."]
    out = ["courses: " + ", ".join(known)]
    for slug in known:
        try:
            cfg = course_config.load(slug)
            out.append(f"  {slug}: course {cfg['course_id']} on {cfg['school']}")
        except Exception as exc:  # noqa: BLE001 — per-course status, not a failure of setup
            out.append(f"  {slug}: unreadable — {exc}")
    return out


def _register_course(course_url: str, slug: str | None, course_dir: str | None) -> str:
    """One course, from its Canvas URL. Everything else is proposed and overridable.

    The course URL is the only address an instructor has — it is what the browser shows — and it
    names the school too. So a course URL for an unknown school registers the school from it and
    asks for the token, rather than sending the instructor away for a different URL. The URL is
    kept beside the credential so the next call finishes the job without being told again.
    """
    from .. import course_config
    from ..auth import token as token_auth

    try:
        result = course_config.register_course(course_url, slug=slug, course_dir=course_dir)
    except Exception as exc:  # noqa: BLE001 — the reason is the answer
        # Naming the course needs one Canvas call, so a missing or unusable token stops here.
        # The school comes out of this same URL; register it and hold the URL for the retry.
        try:
            reg = token_auth.register_school(course_url)
            _remember_pending(reg["path"], course_url)
        except Exception:  # noqa: BLE001 — fall through to the plain reason below
            return f"Could not register {course_url}: {exc}"
        return (
            f"Created {reg['path']} for this course's school.\n\n"
            "Its token is empty, and naming the course needs one Canvas call, so the course is "
            "not registered yet.\n\n"
            "Paste the token into that file's empty \"token\" field and call setup again — this "
            "URL is remembered, so the course finishes by itself. (Or tell me the token and I "
            "will store it; it then lives in this conversation's record as well as the file.)\n\n"
            "The token comes from Canvas: Account -> Settings -> + New Access Token."
        )

    if result["status"] == "already_registered":
        return (
            f"{result['slug']} is already registered at {result['path']}.\n"
            "Nothing was changed."
        )

    return (
        f"Registered {result.get('name') or result['course_code']} as slug "
        f"'{result['slug']}'.\n"
        f"Config: {result['path']}\n"
        f"School: {result['school']} (guessed from the domain — say so if it is wrong)\n\n"
        f"Tools now take course='{result['slug']}'. To use a different folder or slug, call "
        "setup again with course_dir or slug set; nothing is overwritten, so move or delete the "
        "old config first."
    )


def _register(token_auth, canvas_url: str, token: str | None) -> str:
    """One school, registered the way the instructor chose."""
    try:
        result = token_auth.register_school(canvas_url, token)
    except Exception as exc:  # noqa: BLE001 — a rejected token is the answer, not a crash
        return (
            f"That token was refused by {canvas_url}: {exc}\n"
            "Nothing was stored. Check it was copied whole, and that it has not expired."
        )

    path, status = result["path"], result["status"]

    if status == "registered":
        note = ""
        if token:
            note = ("\n\nNote: the token passed through this conversation, so it is in the "
                    "record. Revoke and re-issue it in Canvas if that matters.")
        return (
            f"Registered {result['base_url']} as {result.get('identity')}.\n"
            f"Stored in {path}.{note}\n\n"
            "Next: add a course. Give me the course's Canvas URL."
        )

    if status == "already_registered":
        return (
            f"{result['base_url']} is already registered in {path}.\n"
            "Nothing was changed. To replace the stored token, edit that file directly."
        )

    return (
        f"Created {path}.\n\n"
        "Two ways to finish, and the first keeps the token out of this conversation:\n"
        f"  1. Open that file and paste the token into its empty \"token\" field, then call "
        "setup again — I will verify it.\n"
        "  2. Tell me the token and I will store it. It will then live in this conversation's "
        "record as well as the file.\n\n"
        "The token comes from Canvas: Account -> Settings -> + New Access Token.\n"
        "If the environment already defines <SCHOOL>_CANVAS_TOKEN, that wins over this file."
    )


def register(server) -> None:
    server.add_tool(get_doc)
    server.add_tool(setup)
