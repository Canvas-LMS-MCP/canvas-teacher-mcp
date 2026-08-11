# CommitAuthenticity

What the engine computes about a commit history. What it COSTS is `GRADING.md` Part B §4.
Code: `lib/commit_inspect.py`, `graders/gh.py`; surfaced in Stage-A report Section 0 every run.

**The engine detects; Stage B sentences.** Every consequence is a Stage-B call on an engine flag.
Nothing here zeroes a row by itself.

## Trust the SERVER clock

Commit author and committer dates are client-set and forgeable. The authenticity clock is
repo `created_at` → the passing run's `created_at`, both GitHub-stamped. Commit dates are read only
to DETECT backdating — an author-claimed span far larger than the real server window means padded
dates.

## `authenticity(insp, repo_created_at, graded_run_created_at, first_run_created_at, instant_minutes=10.0)`

| Key | Meaning |
|---|---|
| `repo_to_pass_min` | server minutes, repo created → graded run (`None` if either is missing) |
| `single` | one commit, or an all-at-once first bulk with ≤2 commits |
| `backdated` | `author_span > repo_to_pass*3 + 15` |
| `verdict` | `clean` · `single-all-at-once` · `instant` · `no-commits-in-window` · `backdated` |
| `accepted` | `False` whenever the history is not proctorable |
| `flags` | human, instructor-facing |

- `single` or all-at-once ⇒ `accepted=False`, always. Under `instant_minutes` ⇒ `instant` (paste
  suspect); over it ⇒ `no-commits-in-window` (worked locally, process not in git).
- Multi-commit but under `instant_minutes` with `n_debug ≤ 1` ⇒ `instant`, not accepted.
- `compressed` (n≥2 inside a 10-minute author span) ⇒ a verify flag, not a rejection.
- `backdated` ⇒ not accepted regardless of count.
- `instant_minutes` is a HEURISTIC window, not a gate — difficulty varies.
- None-safe: a 404 repo or no passing run gives `repo_to_pass_min=None`, `verdict=clean`; a
  genuinely single commit still flags from `insp` alone.

## `pass_commit_analysis(commit_diffs, run_history, insp)`

Count and span answer "how much did they commit". They do not answer the question that decides the
row: **did the algorithm ever fail before it passed?**

Pairs the first `conclusion == "success"` run with the commit that produced it
(`head_sha` ↔ `sha`) and reads that commit's own diff.

| Key | Meaning |
|---|---|
| `sha` · `message` · `additions` · `deletions` · `passed_at` | the commit that turned it green |
| `added_share` | its share of every line the student added |
| `prior_failing_runs` | failing runs before it |
| `verdict` | `oneshot_bulk` (share ≥ 0.60) · `oneshot_trivial` (≤3 lines changed) · `real_fix` |
| `oneshot` | the two one-shot verdicts |

Returns `{}` when there is no passing run or the sha is not among the read commits — it never
guesses. `real_fix` is the finding that CLEARS a student.

## `classify_diff` + `commit_quality` — content × time × count

Diff SIZE cannot tell a semicolon from `&&` → `||`, so size alone once called an empty
"Trigger autograder" commit a substantive change.

- **`classify_diff(patches)`** → `logic_fix` · `syntax_fix` · `assembly` · `rewrite` · `empty`.
  Pairs each `-` line with its closest `+` line and reads the CHARACTER-level residual. An
  operator, numeric literal or index change is `logic_fix` even at one character — `i = 0` → `i = -1`
  is real debugging however fast it came. Punctuation and braces are `syntax_fix`. Additions with
  nothing replaced are `assembly`. The commit MESSAGE is never consulted; messages are gameable.
- **`inspect(commits, commit_diffs)`** also returns per-commit `content` and `gap_min`, plus
  `effective_cycles` — commits that carry real content AND sit ≥1 minute after the previous one.
  Twelve commits a minute apart are one cycle's evidence, not twelve.
- **`commit_quality(insp, pass_commit, difficulty)`** → the grid. Content picks the row, the
  time-filtered count picks the column. Time never decides alone: a fast student debugs fast.

| | cycles ≥ 3 | narrower |
|---|---|---|
| `logic_fix` ≥ 1 | 100% | 87.5% |
| `syntax_fix` only | 75% | 62.5% |
| purely additive | 62.5% | 50% |

`difficulty` applies the carve-outs — `trivial` WAIVES the grid (a sub-10-line assignment does not
require a debugging cycle), `normal` floors at 62.5%, `advanced` allows the full range. Unknown
difficulty invents no floor and sets `needs_difficulty`.

**Repair needs a deletion, not just a red run.** `_repairs_after_failure` credits a commit that
landed while the autograder was failing — but an INCOMPLETE program is red on every push too, so
the prerequisite is that the history deletes at least one line somewhere. A history that never
took anything back never repaired anything.

## `elab_commit_match` — the slot only a reader can fill

When the commits show no repair, the write-up is the only remaining evidence and the engine cannot
tell whether its account is true. Decide it; never skip it.

| Value | Meaning | Score |
|---|---|---|
| `corroborated` | the described errors are visible in the commits | full marks — the two records agree |
| `claimed_only` | described but not visible | −1 when it quotes what only a real run produces (exception text, the actual wrong output); −2 for general debugging talk |
| `absent` | no error account | the engine tier stands |

`report_generator.commit_tier_issues` REFUSES to render an `assembly` row with no
`elab_commit_match`, refuses `claimed_only` at full marks, and refuses any authoring that carries
no `commit_quality.engine_score` or awards above the tier with no written reason. That closes the
hole `coverage_issues` cannot: it only demands a reason for a BELOW-max row, and the un-consulted
answer is always FULL marks.

The comment for `claimed_only` ADVISES — commit the broken state, then the fix, and the history
will corroborate the write-up. It never accuses.

## Runtime-error evidence

`inspect()` returns `n_runtime_err` / `has_runtime_err` from commit-message markers, excluding
SyntaxError and indentation — a syntax-only fix is not a debug cycle. A passing history with
`has_runtime_err == False` cannot earn full commit marks. Message-based, so it is a signal, never
an auto-zero.
