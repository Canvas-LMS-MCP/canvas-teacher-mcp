# RepoResolution

Map a Canvas student to their GitHub repo. `lib/repo_resolve.py`.

## The log is authoritative, and it is a BATCH

`<org>/classroom-admin/log/*.json` is the source of truth for who owns which repo. It is written
only by `log-build`, which drains the pending request issues on a schedule (05:00 PDT) or on
demand — so a repo provisioned after the last drain is still an open issue, not a log entry.

- Refresh the log ONCE per grading session, before Stage A (`skills/grade/SKILL.md` Step 1).
- Read absence from a STALE log as "not drained yet", never as "no repo", and never as the
  student's fault.
- Never drain per student. N concurrent drains re-create the branch-head contention the issue
  design removes.

## Resolve

```python
resolve(repo_link, name, email, *, org, repo_prefix, code, gh_get)
```

1. Take `repo_link` — `attachments.read(..., github_org=)` surfaces the link the student pasted.
   → `(repo_link, "body")`
2. No link ⇒ `resolve_repo_from_log(...)`: list the log, filter filenames to
   `{repo_prefix}-{code}-*`, match the Canvas student EMAIL (name is a word-set fallback).
   → `({org}/{repo}, "log")`
3. Neither ⇒ `(None, None)` ⇒ 0 and a flag. Two log matches ⇒ `None` and a multi-account flag.

Bridge on email — the school email is unique. A student who registered under a different email
than Canvas holds gets no match, and that is intended.

## Reconcile the two

| Submitted | In log | Do |
|---|---|---|
| — | repo | grade the log's repo, note that no link was submitted |
| same | repo | grade it |
| different | repo | **FLAG** — read the submitted one. Mistake, or a deliberate second repo? Never silently grade the other |
| repo | — | **FLAG unregistered** — read theirs |
| — | — | 0 and Section 0, but only against a CURRENT log |

## The CODE is copied, never derived

The marker is the page's repo-request link — `…/classroom/issues/new?template=request-<slug>.yml&assignment=A00`.
No such link means it is not a GitHub assignment.

- Copy the `assignment=` value verbatim, then confirm it is a key in `<org>/classroom/config.json`
  → `courses.<slug>.assignments`.
- STOP when it is not a key. The PAGE is wrong, and grading past it searches
  `{repo_prefix}-{code}-*` for repos that cannot exist — "0 matches" then looks exactly like
  "nobody made a repo" and the class scores 0 in silence.
- Never type the code from memory and never infer it from a title or a filename.

## Instructor exclusion

`github.instructor_logins(token)` = the token owner, plus `INFRA_BOT_LOGINS`. Everyone else who
wrote to the repo is the student — no roster, no login bridge.
