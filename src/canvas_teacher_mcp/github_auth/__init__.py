"""github_auth — GitHub login foundation (mirrors canvas_token_auth).

Sole owner of GitHub token resolution + token-owner identity. The general
GitHub API client (github_access) builds on this.
"""
from .token import get_token, token_owner_login

__all__ = ["get_token", "token_owner_login"]
