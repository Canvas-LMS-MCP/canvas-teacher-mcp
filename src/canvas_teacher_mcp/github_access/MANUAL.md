# github_access — Manual

The GitHub REST layer — the GitHub-side mirror of `canvas_rest`. Every function takes
`(token, repo, …)`. Nothing here logs in: the token comes from `github_auth.get_token()`
and is passed in.

`repo` is always the full `"{org}/{name}"` string (e.g. `"<org>/<course>-<term>-A61-<student-login>"`).

Policy is not restated here. Autograder / run-log mechanics:
`CourseGlobalWorkflow/Access/GitHub.md`. Student-repo provisioning + naming:
`Access/GitHub.md`. Grading rules: `GRADING.md` Part B.

## Scope — what is deliberately NOT here

- **Autograder RESULT parsing** (`totalPoints/maxPoints` out of the log zip) — grading-specific,
  lives in `grade_engine/lib/github.py` + `graders/gh.py`.
- **Student-commit filtering** (dropping infra bots + the token owner) — grading-specific, same place.
- **GitHub Classroom API calls** — intentionally absent. Classroom is retired; provisioning is the
  org-hub (`Access/GitHub.md`), whose request log is read as ordinary repo contents.

This package stays generic so it distills into a publishable GitHub resource layer later.

---

## client.py — transport

| Function | Use |
|---|---|
| `get(token, path, paginate=True)` | GET `https://api.github.com{path}`. Follows `Link` pagination and returns the concatenated list; `paginate=False` for a single object. |

`_http(url, headers, raw=False, retries=3)` is internal — retries transient failures.

## actions.py — repo reads

| Function | Returns |
|---|---|
| `list_runs(token, repo, branch=None)` | the 10 most recent Actions runs (a branch filter is optional). Each run carries `id`, `head_sha`, `conclusion`, `created_at` — `created_at` is the SERVER clock the commit-authenticity proctor trusts. |
| `list_commits(token, repo)` | all commits (per_page=100). |
| `get_commit(token, repo, sha)` | ONE commit's detail — includes `stats` (additions/deletions) and `files` (the per-file patch). **This is the diff** that commit-quality grading reads; count and message alone can never substitute for it. |
| `get_run_log(token, repo, run_id, cache_path)` | downloads the run-log ZIP, returns the local path (or `None`). Caches: an existing non-empty `cache_path` is returned directly. |

### `LOG_HARD_CAP_BYTES` = 500 MB

An absurd ceiling on the run-log **zip download** (compressed bytes, checked before the body is
read). It exists only to refuse a pathological runaway — no legitimate autograder log is near it,
so normal grading always downloads in full.

⚠️ **The MONITOR threshold is NOT here.** `graders/gh.py LOG_ALERT_BYTES` (5 MB, measured
**uncompressed**) raises a loud report alert without blocking. Both numbers are provisional
placeholders pending real data — see `Access/GitHub.md` (the standing TODO), which is the one
home for that decision.

---

## Typical call shape

```python
from github_auth import get_token
from github_access import list_runs, list_commits, get_commit, get_run_log

tok  = get_token()
runs = list_runs(tok, "<org>/<course>-<term>-A61-<student-login>")
sha  = runs[0]["head_sha"]
diff = get_commit(tok, "<org>/<course>-<term>-A61-<student-login>", sha)   # ["files"] = the patch
```

## Rules

- **Never hand-roll GitHub HTTP** (`curl`, `requests`, inline `urllib`) and never shell out to `gh`
  for something here. If a function lacks a field, add it here — do not bypass.
- **Never construct a student repo NAME from a pattern** — list and match (`gh repo list`).
  Re-accepts produce variants; a wrong name can destroy someone else's work
  (`Access/GitHub.md`).
- **Adding a function to this package means adding its row to this file in the same session.**
  A stale manual is a future-session hazard.
