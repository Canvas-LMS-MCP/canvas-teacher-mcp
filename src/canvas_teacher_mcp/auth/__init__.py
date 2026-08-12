"""Canvas credentials — the one place that decides token or cookie.

`session` mints a session for a school and re-logs in once on a 401; `token` resolves and stores
an API token. Roll Call's LTI session is not here: it is cookie-only and does not ship.
"""
from .session import CanvasSession
from .login import NeedsLogin, login
from .token import get_token, whoami, register_school, verify_school, school_slug, config_path

__all__ = [
    "CanvasSession", "login", "NeedsLogin",
    "get_token", "whoami", "register_school", "verify_school", "school_slug", "config_path",
]
