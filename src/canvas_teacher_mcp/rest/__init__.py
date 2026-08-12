"""Generic Canvas REST (/api/v1).

Once logged in, a REST call is the same whatever the credential — the credential is only what you
attach. Every function takes `(base_url, auth, …)` and hardcodes nothing about a course.

  client     transport: get, get_raw, put, post, delete
  resources  Canvas reads and writes (fetch_*, create_*, update_*, post_submission_grade)
  html       strip: submission HTML -> plain text
  timefmt    UTC <-> local
  files      upload

These names are re-exported because callers use `rest.post(...)`; importing the subpackage alone
leaves them missing, which is exactly how the quiz builder broke.
"""
from .client import get, get_raw, put, post, delete
from .resources import (
    fetch_submissions, fetch_assignment, fetch_users, fetch_rubric, fetch_quiz,
    create_assignment, update_assignment, list_modules, add_module_item,
    get_page, update_page, create_page, create_announcement, post_submission_grade,
)
from .html import strip
from .timefmt import to_localtime, to_utc, set_timezone, get_timezone, to_pacific
from .files import upload_file

__all__ = [
    "get", "get_raw", "put", "post", "delete",
    "fetch_submissions", "fetch_assignment", "fetch_users", "fetch_rubric", "fetch_quiz",
    "create_assignment", "update_assignment", "list_modules", "add_module_item",
    "get_page", "update_page", "create_page", "create_announcement", "post_submission_grade",
    "upload_file", "strip",
    "to_localtime", "to_utc", "set_timezone", "get_timezone", "to_pacific",
]
