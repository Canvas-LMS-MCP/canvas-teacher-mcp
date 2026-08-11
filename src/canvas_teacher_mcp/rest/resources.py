"""canvas_rest.resources — general Canvas API resource wrappers (login-free).

Thin wrappers over canvas_rest.client for the common Canvas objects: submissions,
assignment, users, rubric (reads) + assignment create/update and module placement
(writes). Signatures are (base_url, token, course_id, ...) — no grading/GitHub
coupling. (Canvas<->GitHub repo-mapping bridges are grading-specific and stay in
the grade engine, not here.)
"""
from .client import get, put, post


def fetch_submissions(base_url, token, course_id, asmt_id):
    """Fetch all submissions for a Canvas asmt with the standard includes."""
    return get(
        base_url,
        token,
        f"/courses/{course_id}/assignments/{asmt_id}/submissions",
        params=[
            ("per_page", "100"),
            ("include[]", "submission_comments"),
            ("include[]", "submission_history"),
            ("include[]", "user"),
            ("include[]", "attachments"),
        ],
    )


def fetch_assignment(base_url, token, course_id, asmt_id):
    """Fetch one assignment metadata."""
    return get(
        base_url,
        token,
        f"/courses/{course_id}/assignments/{asmt_id}",
        paginate=False,
    )


def fetch_users(base_url, token, course_id):
    """Fetch enrolled students with sis_user_id / login_id / email when available.

    Some Canvas instances strip these fields without admin scope. The caller
    treats null fields as "not available" and falls through to other matching
    keys (sortable_name, etc.).
    """
    return get(
        base_url,
        token,
        f"/courses/{course_id}/users",
        params=[
            ("per_page", "100"),
            ("enrollment_type[]", "student"),
            ("include[]", "email"),
            ("include[]", "enrollments"),
        ],
    )


def fetch_rubric(base_url, token, course_id, asmt_id):
    """Fetch rubric attached to a Canvas assignment.

    Returns a dict {item_label: max_pts} or empty dict if no rubric is attached.
    Tries Canvas Rubric API first; if absent, returns empty (caller may parse
    description HTML separately, or fall back to a default).
    """
    a = get(
        base_url,
        token,
        f"/courses/{course_id}/assignments/{asmt_id}",
        params=[("include[]", "rubric_assessment")],
        paginate=False,
    )
    if not a:
        return {}
    rubric = a.get("rubric") or []
    out = {}
    for row in rubric:
        label = (row.get("description") or "").strip()
        pts = row.get("points")
        if label and pts is not None:
            out[label] = pts
    return out


# --- writes: assignment create/update + module placement ---

def create_assignment(base_url, token, course_id, fields):
    """Create a Canvas assignment. POST /courses/{cid}/assignments.

    `fields` = the assignment body, e.g.:
        {"name": "...", "points_possible": 100, "description": "<html>",
         "submission_types": ["online_text_entry", "online_url"],
         "due_at": "2026-06-21T23:59:00-07:00",   # explicit offset — NEVER naive/UTC
         "published": True}
    Returns the created assignment dict (has 'id'); raises RuntimeError on failure.
    """
    status, body = post(base_url, token, f"/courses/{course_id}/assignments",
                        {"assignment": fields})
    if not isinstance(body, dict) or "id" not in body:
        raise RuntimeError(f"create_assignment failed (HTTP {status}): {body}")
    return body


def update_assignment(base_url, token, course_id, asmt_id, fields):
    """Update a Canvas assignment (partial). PUT /courses/{cid}/assignments/{aid}.

    `fields` = the fields to change, e.g. {"description": "<html>"} or
    {"due_at": "2026-06-21T23:59:00-07:00"}. Returns (status, body).
    """
    return put(base_url, token, f"/courses/{course_id}/assignments/{asmt_id}",
               {"assignment": fields})


def list_modules(base_url, token, course_id):
    """List a course's modules (id + name). GET /courses/{cid}/modules.
    Find a module by name in the caller (e.g. next(m for m in mods if m['name']==...))."""
    return get(base_url, token, f"/courses/{course_id}/modules",
               params=[("per_page", "100")])


def add_module_item(base_url, token, course_id, module_id, item):
    """Place an item in a module. POST /courses/{cid}/modules/{mid}/items.

    `item` = e.g. {"type": "Assignment", "content_id": <asmt_id>}. Returns the
    created module-item dict; raises RuntimeError on failure.
    """
    status, body = post(base_url, token,
                        f"/courses/{course_id}/modules/{module_id}/items",
                        {"module_item": item})
    if not isinstance(body, dict) or "id" not in body:
        raise RuntimeError(f"add_module_item failed (HTTP {status}): {body}")
    return body


def fetch_quiz(base_url, token, course_id, quiz_id):
    """Fetch one quiz's metadata. GET /courses/{cid}/quizzes/{qid}.
    Returns the quiz dict (has `due_at`, `title`, `points_possible`, ...)."""
    return get(base_url, token, f"/courses/{course_id}/quizzes/{quiz_id}",
               paginate=False)


# --- pages (agenda etc.) ---

def get_page(base_url, token, course_id, slug):
    """Fetch a Canvas page. GET /courses/{cid}/pages/{slug}.
    Returns the page dict (`title`, `url`, `body` HTML, `published`, ...)."""
    return get(base_url, token, f"/courses/{course_id}/pages/{slug}",
               paginate=False)


def update_page(base_url, token, course_id, slug, fields):
    """Update an existing Canvas page. PUT /courses/{cid}/pages/{slug}.
    `fields` = e.g. {"body": "<html>", "published": False}. Returns (status, body).
    (Wraps the `{"wiki_page": ...}` envelope so callers don't.)"""
    return put(base_url, token, f"/courses/{course_id}/pages/{slug}",
               {"wiki_page": fields})


def create_page(base_url, token, course_id, fields):
    """Create a Canvas page. POST /courses/{cid}/pages.
    `fields` = e.g. {"title": "...", "body": "<html>", "published": False}.
    Returns the created page dict; raises RuntimeError on failure."""
    status, body = post(base_url, token, f"/courses/{course_id}/pages",
                        {"wiki_page": fields})
    if not isinstance(body, dict) or "url" not in body:
        raise RuntimeError(f"create_page failed (HTTP {status}): {body}")
    return body


# --- announcements (a discussion_topic with is_announcement) ---

def create_announcement(base_url, token, course_id, fields, *, session=None):
    """Create a Canvas announcement. POST /courses/{cid}/discussion_topics.

    An announcement is just a discussion_topic with is_announcement=True (forced
    here). `fields` = the topic body (NO envelope — sent top-level), e.g.:
        {"title": "...", "message": "<html>",
         "published": True,                              # must be True to go live
         "delayed_post_at": "2026-06-25T09:00:00-07:00"} # optional → schedule;
                                                         #   omit = post (email) now
    delayed_post_at: explicit offset, NEVER naive/UTC.

    Transport (auth is just what you attach — see package docstring):
      - token school → pass (base_url, token); Bearer over canvas_rest.client.
      - token-less school → pass session=<canvas_auth CanvasSession>;
        same REST call over cookie+CSRF. (base_url/token may be None then.)

    Returns the created topic dict (has 'id'); raises RuntimeError on failure.
    (Safety — dry-run vs send-now vs schedule — is the CALLER's choice.)
    """
    body_fields = dict(fields)
    body_fields["is_announcement"] = True
    path = f"/courses/{course_id}/discussion_topics"
    if session is not None:
        r = session.post(f"/api/v1{path}", data=body_fields, csrf=True, xhr=True)
        status = r.status_code
        body = r.json() if r.content else {}
    else:
        status, body = post(base_url, token, path, body_fields)
    if not isinstance(body, dict) or "id" not in body:
        raise RuntimeError(f"create_announcement failed (HTTP {status}): {body}")
    return body


# --- grade posting (assignment AND quiz — uniform; NEVER quiz fudge_points) ---

def post_submission_grade(base_url, token, course_id, assignment_id, user_id,
                          score, comment=None, late_policy_status=None,
                          seconds_late_override=None):
    """Post a final grade to a student's submission.
    PUT /courses/{cid}/assignments/{aid}/submissions/{uid}.

    Works for BOTH assignments and quizzes/exams — for a quiz, pass the quiz's
    UNDERLYING assignment id. Sets `posted_grade` (overrides/sets the final score).
    NEVER uses quiz `fudge_points` (an offset added to the auto score → wrong totals).
    `user_id` must be the exact Canvas user id (no fuzzy name matching).

    LATE: pass `late_policy_status='none'` (+ `seconds_late_override=0`) to tell Canvas
    NOT to apply a late penalty — REQUIRED when grading a resubmission whose FIRST
    submission was on time (GRADING.md §3.5: late = the INITIAL submission). If omitted,
    Canvas penalizes off the LATEST submitted_at. Pass `'late'` + seconds to penalize.
    Returns (status, body).
    """
    payload = {"submission": {"posted_grade": score}}
    if late_policy_status is not None:
        payload["submission"]["late_policy_status"] = late_policy_status  # 'none' | 'late'
    if seconds_late_override is not None:
        payload["submission"]["seconds_late_override"] = seconds_late_override
    if comment:
        payload["comment"] = {"text_comment": comment}
    return put(base_url, token,
               f"/courses/{course_id}/assignments/{assignment_id}/submissions/{user_id}",
               payload)
