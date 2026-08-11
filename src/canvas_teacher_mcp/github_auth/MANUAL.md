# github_auth — Manual

The GitHub login FOUNDATION — the GitHub-side mirror of `canvas_token_auth`. Sole owner of
GitHub token resolution and the token-owner identity. It depends on nothing above it;
`github_access` builds on it.

Two functions. That is the whole package.

| Function | Contract |
|---|---|
| `get_token()` | Resolve a GitHub token: env `GITHUB_TOKEN`, else `gh auth token`. **Raises `RuntimeError`** when neither works — never returns an empty string, so a missing token fails loudly at the call site instead of surfacing later as a 401. |
| `token_owner_login(token)` | The login of the account that owns the token (`GET /user`), lower-cased, cached per token. **Best-effort: returns `''` on failure**, never raises. |

## Where the token actually lives

**Not in a file we manage.** The GitHub credential is in the `gh` CLI keyring (or the
`GITHUB_TOKEN` env). `Canvas-Auth/` holds **Canvas tokens only** — do not put a GitHub token
there (`canvas_auth/README.md`).

## Why `token_owner_login` exists

Grading must exclude the instructor's own commits from a student's history. The grade runs under
the instructor's token, so **the token owner IS the instructor** — that is the one identification
that cannot be wrong. `grade_engine/lib/github.instructor_logins` builds the closed write-set from
it plus the infra-bot list; there is no roster lookup and no starter-author derivation
(`GradingEngine/RepoResolution.md`).

Its best-effort return is deliberate: a failed whoami must not abort a grading run — it degrades
to "no owner exclusion", which is visible, rather than crashing mid-batch.

```python
from github_auth import get_token, token_owner_login
tok = get_token()
me  = token_owner_login(tok)      # '' if the whoami call failed
```

## Rules

- **Never read a GitHub token by hand** and never shell out to `gh auth token` yourself — call
  `get_token()`. One resolver, one place to change.
- **Adding a function to this package means adding its row to this file in the same session.**
