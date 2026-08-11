# GitHub

## Reading an autograder run

- Fetch failed steps with `gh api /repos/{repo}/actions/runs/{run_id}/jobs --jq '.jobs[0].steps[] | select(.conclusion=="failure")'`, and the failing log with `gh run view {run_id} --repo {repo} --log-failed`.
- Parse the score from the run-log ZIP (`github_access.get_run_log` → `gh.parse_total_points_from_log_zip`).
- Refuse a zip over `LOG_HARD_CAP_BYTES` (500 MB), checked on `Content-Length` before reading the body.
- Alert, do not block, when the UNCOMPRESSED log exceeds `LOG_ALERT_BYTES` (5 MB): grade in full,
  write `⚠⚠ LARGE AUTOGRADER LOG` at the top of the report, store `oversized_log`. Measure
  uncompressed — a stdout flood compresses to a tiny zip and a zip-size check misses it.
- ⏳ Both thresholds are placeholders set without data. Replace them once real `oversized_log`
  alerts accumulate, and decide then whether the alert becomes a block.
- Trust the Reporter's result over the step status. All steps green + `Autograding Reporter` failed +
  log line `##[error]Some tests failed.` means a `*_RESULTS` variable was "failed" — usually a
  starter-config bug, not a student bug.

## classroom.yml — three ways it fails everyone silently

Each of these records failure for every student while the workflow looks fine.

- **Redirect stdin when the program reads it.** `timeout 10 ./main` blocks on `cin`, hits the
  timeout, and the command-grader records a failure though the unit tests pass. Write
  `… && timeout 10 ./main < data/data.txt`, and ship that file in the repo.
- **Hard-code every path in a `command:`.** The `autograding-command-grader` step does not receive
  workflow or job-level `env:`, so `javac -cp "$JUNIT"` runs with an empty classpath and nothing
  compiles. Globs do expand — a shell is present — so the symptom looks junit-only.
- **Verify on Actions after any change.** A local shell expands `$VAR` and globs, so a broken
  grader yml passes locally and fails on the runner. Template-clone the starter, drop the solution
  in, push, and confirm the run reports 100/100.

## Patching student repos in bulk

- Patch each repo's file through the Contents API from ONE verified golden copy
  (`gh api -X PUT …/contents/.github/workflows/classroom.yml`). Never hand-edit per repo.
- Confirm the results with `code/hw_status.py --course <slug> --code <CODE>`.
- Tell students to `git pull` once — their local is now one commit behind and a plain push is rejected.
- This is the one sanctioned Contents-API edit: student repos are disposable, per-student, and have
  no local clone.

## Instructor content and template repos

- Keep a local clone of every content repo (`PythonCH07`, slide repos, lab content). No clone ⇒ find
  it or recreate it before editing.
- Edit the local clone, commit, push to all configured remotes.
- Ask the instructor first if a direct GitHub edit is genuinely needed, and get explicit confirmation.
- Propagate to every sibling clone in the same change — the same content is copied across courses
  (<school> `<course>/NB/PythonCH07` → <school> `<course>/NB/PythonCH07`), and one sibling drifting means one
  course's students see stale content.
- Check before any edit: where is the clone, what remotes does it push to, do other courses share it.
  Unclear ⇒ stop and ask.

---

# Starter-Hub — student-repo provisioning

Our self-hosted replacement for GitHub Classroom: plain GitHub Issues + Actions, no server.
Implementation: `$CANVAS_LMS_ROOT/GitHub-Starter-Hub/` (read `workflow/readytogo.md` there).

## Model

- Per school, two repos: `<org>/classroom` (PUBLIC — issue forms, workflows, `config.json`, no PII)
  and `<org>/classroom-admin` (PRIVATE — roster, logs). Both from the `gh-classroomless` templates.
- A student opens a pre-filled issue from a Canvas deep-link; an Action creates
  `<org>/<course>-<term>-<asmt>-<handle>` (private) from the assignment's starter template, invites
  them, logs it, closes the issue. Five workflows: register · request · myrepos · gen-forms · report.
- Deploy a school with `GitHub-Starter-Hub/ops/deploy.sh <ORG>`, set `JOIN_CODE` and `ORG_PAT`, then
  `ops/config.sh <ORG> add-course` / `add-assignment` — a config push regenerates the request forms.

## Deployed orgs

Keep the roster here, one row per org — this is its only home. Read an org's courses and
assignments from its own `<org>/classroom/config.json`, never from a list in prose. Mark an org
LIVE only after a smoke test (register → one request → bot replies); `actions/permissions.enabled`
proves nothing.

| Org | State |
|---|---|
| <org> | live |
| <org> | live |
| <org> | live |
| Ventura-CSV | deployed, not operational |
| <org> | deployed, not operational |

## Student-repo names — resolve, never construct

Repos are `<course>-<term>-<asmt>-<github-handle>`, but repeat
or malformed requests produce variants — suffixes, `--semester`, a trailing `-`. For any real
operation on a student repo (clone, patch, grade), list and match via `gh repo list`. One extra API
call costs under 300 ms; a wrong repo name can destroy someone else's work.
