---
name: git-asmt-repo
description: "GLOBAL, language-agnostic L1 abstract for building + testing a GitHub coding-assignment repo through the org-hub autograder. Owns the WHAT (audit → instruction-fidelity harness → prove 100/100 → ship the Starter → gates) with NO language mechanics. The HOW-to-compile/run/assert is delegated to an L2 language skill (git-asmt-repo/languages/*), and the course coordinates come from an L3 course wrapper (config). Use as the shared core every course's git build/test wrapper points to. NEVER re-implement this per course."
tools: [build_starter_repo, list_autograder_runs, get_autograder_log]
---

# git-asmt-repo — GLOBAL abstract (L1)

The **language-agnostic** core of "build + test a GitHub coding assignment for the org-hub." It owns
the procedure and the gates; it never says `g++`, `pytest`, or `Catch2`. Those live in **L2 language
skills**; the course id/org/prefix/curriculum live in the **L3 course wrapper**.

```
L1 (this)  git-asmt-repo/SKILL.md      ← WHAT: audit · fidelity · prove-100 · ship · gates
L2         git-asmt-repo/languages/    ← HOW in a language: compile/run/assert
              python-pytest.md · cpp-stdout.md · cpp-catch2.md
L3 (local) <course>/.claude/skills/…-git…   ← WHICH: org, prefix, language, chapter→model map (config)
```

**The seams L1 leaves lower layers** = four slots. Three are **L2** (language): `COMPILE`, `RUN`,
`ASSERT(case)`. One is **L3** (course + term): `PROVISION` — HOW the local dir → repo → Starter is
created, which differs per course and changes per semester (see Part C). L1 calls all four abstractly;
L2 fills compile/run/assert for the language, the L3 wrapper/config fills provision for the course.

**The CORE RULE (inherited by every L2):** `classroom.yml` **IS** the test spec — run its `command:`
lines **verbatim, in its order**. Never assume the method or infer it from the files present. Step 0
of any test is always: open the repo's `.github/workflows/classroom.yml` and read its graders + order.

**⛔ STEP 0b — DIFF THE REPO AGAINST ITS L2 TEMPLATE, EVERY BUILD.** The harness files have ONE
source, per language:

```
languages/<cpp-catch2|cpp-stdout|python-pytest|java-junit>/template/
        …/.github/workflows/classroom.yml   ← the true grader config
        + the harness files that model needs (tests, runner, Makefile, .gitignore, README)
```

An existing course repo is a COPY of some older template and drifts silently. Before building,
shipping, or "fixing" anything, diff the repo's `classroom.yml` against its template and say out
loud which graders differ. **Never edit a repo's yml to correct it — change the TEMPLATE, then
propagate** (local dir → solution master → Starter, all three, per Part C). The CORE RULE above
still governs how you RUN an already-released repo; this governs what a NEW one is built from.
*(2026-08-02: three <course> repos each carried a retired `-fsanitize=address` grader; the template
had dropped it long before, and no skill file said where the template lived.)*

---

## Inputs (from the L3 wrapper)

- `CODE` (e.g. `A71`) → the local dir, solution-master repo, Starter repo (naming = wrapper's).
- the **instruction source** (Canvas page / gDoc / gSlides) — read with the canonical readers
  (`grade_engine/lib/attachments.read()` / `gws` / `canvas_rest`), never hand-scraped.
- `language` + `test_model` (the wrapper picks these from its curriculum map → selects the L2 skill).
- course coordinates (`github_org`, `repo_prefix`, template base) — all from
  `course_config.load(<course>)`.

---

## Part A — DEV AUDIT (the heart) — language-agnostic

Tests exist to test the **ALGORITHM, not the output format.** Two silent failure modes break that:
one punishes correct students (over-strict format check), one passes wrong programs (missing edges).
Hunt both. Answer four questions — but drive them with the **active harness (§0) first**.

### §0 — INSTRUCTION-FIDELITY HARNESS (run BEFORE the manual questions) ⭐ NEW

Turn §2/§3 from "read the test and hope you spot it" into an **active, mechanical** check. Author TWO
throwaway solutions and run the repo's actual graders (via the L2 runner) against each:

1. **Faithful solution** — implement using **ONLY the instruction** (student's-eye): do exactly what
   it says, and — for output-style problems — print **exactly and only** what it says to print.
   - Run the yml graders (L2 `RUN` + `ASSERT`). **Expect 100.**
   - **Any FAILING grader = the test checks something the instruction never states.** Diagnose:
     - a label/format token not in the instruction → **§2 word-hunt** → strip it (values-only).
     - a legitimate edge the instruction didn't state → **§3** → make the instruction state it.
   - **Never rationalize a failure.** If a faithful solution cannot pass without information outside
     the instruction, that is a BUG in the test or the instruction — fix one of them.
2. **Adversarial solution** — the canonical *plausible-wrong* approach for this problem (e.g. a
   max-finder that inits `max = 0`).
   - Run the graders. **Expect the relevant case(s) to FAIL.**
   - **Any that PASS = a missing edge (§3)** → add that case.

Record both runs as the audit evidence: `faithful → 100 (or which grader failed & why)` and
`adversarial → which case caught it / slipped`. The two throwaway solutions live in `/tmp`, never
committed.

### §1 — Is the source correct?
The real solution compiles clean and its logic actually solves the spec (the *intended* algorithm,
not merely "an" answer). Compile/run via the L2 `COMPILE`/`RUN` slots.

### §2 — Do the instruction and the tests agree? (WORD-HUNTING)
The classic trap: a test greps a **label/format word** (`MAX`, `Total`, `Sum:`, `Average`) the
instruction never told the student to print. §0-a surfaces this automatically; a manual read of the
test is the backup. Fix: prefer **stripping the word-hunt** (match values only, in sequence, forward
search — never whole-line/anchored, never a label word); only pin an exact format if the format is
genuinely the graded skill and the instruction states it verbatim.

### §3 — Are the tests sufficient? (EDGE COVERAGE)

**T1..T4 are GROUPS, not four tests.** Each group holds as many `@Test` / `SECTION` / marked
functions as the problem needs — write the items so every case the spec implies is actually
exercised. Adding items never touches `classroom.yml`.

**But an edge case must be an edge the INSTRUCTION states.** A case the instruction never mentions
is a trap, not rigor: testing negative input when the spec never says the input may be negative
(and never says it must be positive) fails a student who followed the instruction exactly. The rule
is symmetric with §2 word-hunting — when you want that case, **fix the instruction first** (state the
range / the empty input / the duplicate handling), then test it. If the instruction cannot be changed
in time, drop the case; a silent trap costs more than a missing edge.
Missing edge cases silently pass wrong programs. Add the cases the spec implies: negatives, zero,
empty / single element, all-equal or duplicates, already-sorted / reverse-sorted, boundary and
largest-N. **The harder the algorithm, the more items.** §0-b surfaces gaps automatically. Each test
group must carry real cases — never an empty `assert True` / placeholder. One failing item fails its
whole group, so every item must be a case a correct solution passes **and** a plausible-wrong one
fails.

### §4 — Does every test actually validate?
No dead tests, no `assert True`, no marker/section that matches nothing. Order dependencies (a grader
that reads another grader's output) must hold — that's an L2 concern the L2 skill spells out.

### §5 — MANDATORY ARTIFACT: the SPEC↔TEST coverage map (blocks shipping)
Before cutting the Starter, write each required output/behaviour line and name the test that asserts
it. **An empty cell = do not ship.**
```
required by the spec        | asserted by
Number of characters: 10    | T2
First character: C          | T4     <-- was EMPTY; that was the bug
```
"Asserted by" means the test reads that line's VALUE. A length/character-count check standing in for a
missing assertion does not count.

> **Why §0-a alone is not enough — a missing test is always green** (CS-19A A24, 2026-07-10, real).
> The spec required four output lines; T4 asserted only `contains("california") && length() >= 20` and
> never looked at the fourth. `charAt(1)` printing `a` instead of `C` scored **100/100**; deleting the
> whole fourth line also scored **100/100**. The learning objective had zero tests. Only §5 + the
> adversarial proof below catch this — the faithful-solution run never can.
>
> Two failure modes, same cause, opposite blast radius: **too loose ⇒ everyone passes** (silent, found
> months later in the wrong students' grades) · **too strict ⇒ everyone fails** (instant catastrophe;
> on an exam, unrecoverable).

### §6 — Anti-solution proof (this is §0-b done properly)
A stub failing everything proves nothing — it fails for the wrong reason. Take the SOLUTION and break
**exactly one** requirement at a time, then run the graders: drop the length line → that group must go
red · change the index/offset → that group must go red · change ONLY a label's wording → **everything
must stay green**. Run these through the real runner, and read the reporter's per-group points
(`Total points for T4: 0.00/20`), never the step's colour.

**Deliverable of Part A:** fixes applied to the source/tests, the §5 coverage map, the §6 proof result,
**plus a written note to the instructor** of any instruction errors/ambiguities found (so the spec
students read gets fixed).

---

## Part B — PROVE 100/100 (via the L2 runner)

Do not trust "it should pass." **Test the SHIPPED artifact, not the solution dir** — running the
graders where the solution already sits proves nothing about what students receive. End to end:

1. **LOCAL on the SHIPPED Starter** — **download the Starter** to `/tmp` (`gh repo clone …Starter`),
   **drop the known-good solution into it**, then run the yml's graders **verbatim, in order** (the L2
   skill knows how) → **100 locally.** If the *shipped* Starter + solution can't reach 100, the Starter
   is broken — STOP. (`make test` in the solution dir is NOT this step.)
2. **SHIPPED (Actions)** — push, then verify the `classroom.yml` run is GREEN, selected by **your commit
   SHA, NEVER "latest"** (a Starter's stub run is *supposed* to fail; latest reports a false 0/100).
   Confirm BOTH: master(solution)=success by sha, **Starter(stub)=failure** (a passing stub = harness
   bug, GATE D).

Local pass ≠ runner pass — the Actions step does not expand the workflow `env:` and a local shell
expands globs/vars the runner won't. So the shipped run is mandatory.

---

## Part C — PROVISION + REGISTER (the `PROVISION` slot is L3, not L1)

### What a STARTER *is* (definition — no other reading is valid)

> A **Starter** is the repo a student receives: a **new repo with ONE commit** whose tree is the
> assignment **minus the answer**. It is **private + `is_template: true`**, it is the ONLY repo the
> org-hub clones on a request, and it is **not** a branch, a fork, or a copy of the solution master.

A Starter is COMPLETE only when **all six** hold — anything less is not a Starter:

| # | Property | How it is verified (GATE C) |
|---|---|---|
| 1 | **non-empty** — ≥ 1 commit, a `main` branch, the full file list | `gh api repos/<org>/<Starter>` + `…/contents` |
| 2 | **no answer** — every student-editable file is a stub; no other file holds the solution, **not even in history** (one fresh commit ⇒ no history to leak) | re-fetch the pushed source and diff vs the solution: it MUST differ |
| 3 | **compiles / imports** — the stub still builds so the graders report a real red, not a symbol error | run the L2 `COMPILE` on a fresh clone |
| 3′ | **OMIT MODE ONLY** — the Starter deliberately does **not** compile, because the student writes whole files from scratch | the omitted paths are absent by API; the red COMPILE is declared, not diagnosed |
| 4 | **carries the harness** — tests, workflow, test runner (jar / `pytest.ini` / `catch.hpp`), data files, `.gitignore`, README | file list check |
| 5 | **private + template** | `private: true`, `is_template: true` |
| 6 | **registered** in the org-hub config (exam/quiz: window-gated) | the request form resolves the CODE |

**Expected run state:** solution master = **success / 100 by SHA**; Starter (stub) = **failure**.
A Starter that PASSES its own tests means the answer shipped or the tests are empty — GATE D, stop.

### How a Starter is MADE (the only sanctioned sequence)

**Run `code/git_starter_build.py` — do not hand-execute these steps.** The script exists because the
sequence is mechanical and a skipped step is invisible: on 2026-07-30 `<COURSE>A612Starter` sat EMPTY
(0 commits) for nine days because the push step was never run for that one repo while its siblings
were fine. Hand-running is allowed only to debug the script, and then the verification below is still
mandatory.

```
1  local dir  → verify it is the audited solution (L2 COMPILE/RUN/ASSERT all green)
2  copy → /tmp, delete .git and build output
3  STRIP: stub every student-editable file (L2 owns the per-language rule), keep signatures/driver
4  verify the stub: L2 COMPILE succeeds, the graders' paths/jar/tags resolve, tests FAIL (as intended)
5  push the SOLUTION to the master repo (must already exist; missing → RAISE) → confirm green by SHA
6  fresh `git init` + ONE commit → `gh repo create <Starter> --private --source=. --push`
7  `gh repo edit <Starter> --template`
8  RE-FETCH the Starter: properties 1–5 above, by API — never assume the push worked
9  register: `ops/config.sh <org> add-assignment <course> <CODE> <Starter> [FROM] [UNTIL]`
10 final proof: template-clone the Starter into a throwaway repo, drop the solution in, push,
   read the run BY SHA → 100/100, then delete the throwaway
```

### `--strip` vs `--omit` — pick before step 3

`git_starter_build.py` ships the student's files one of two ways. This is a DECLARATION per
assignment, never a default:

| | `--strip file:sym[,sym]` | `--omit path` |
|---|---|---|
| what the Starter carries | the file with its **signatures kept**, bodies `// TODO` | **nothing** — the file is not in the tree |
| Starter COMPILE | **green** (property 3) | **red**, and that is correct (property 3′) |
| use when | the task is "fill in these functions" — the shape is given by the spec anyway | the task is "design and write these classes" — a stub would hand over every field and method signature, which IS what the rubric grades |
| leak sweep | same-named un-stripped copies | same-named copies **plus** any file carrying the omitted body under another name |

**`--strip` remains the default.** Reach for `--omit` only when handing over the signatures would
give away graded design — a final project, a from-scratch class-design task. Say so in the Part A
audit, because a red COMPILE on a Starter is otherwise read as GATE D (a harness bug).

*(Built 2026-08-05 for CSCI-19A `FP`: the tests call `Course`/`Student`/`Enrollment` directly, so a
compiling Starter would have had to ship all three class skeletons — 30 of the rubric's 80 structure
points, handed over.)*

**Never** `gh repo create <Starter> --template <solution-master>` — that stamps the solution's current
tree as the Starter's first commit. **Never** strip in place on `main` (the answer stays in history);
**never** rebase/force-push to "remove" it afterwards (reflog + dangling objects keep it).

**Invariant (all courses, L1 owns this):** end with a **private + template Starter** registered in the
org-hub, the **solution never leaked — not even in git history**, and (exam/quiz) the availability
window gated.

**Local-dir-first.** Edit the local dir, then commit/push → repo — never edit a repo directly. Before
working, make sure local ↔ repo are in sync; reconcile a divergent dir first.

**Starter must NOT contain:** (a) the solution — stub every student-editable file (whatever has
`// TODO`), and delete any OTHER file that still holds the answer (judge by CONTENT, not name — the
build files are the only ones that stay), from git history too; (b) build artifacts / junk (`main`,
`a.out`, `programtest`, `*.o`, caches). `make clean` before push, ship a `.gitignore`. Verify the pushed
tree = only the build's files (edited source + tests + workflow), no solution copy, no artifact.

**Strategy (`PROVISION`) — `master-strip` is the DEFAULT (below); L3 overrides ONLY when a course
differs.** The dir → repo → Starter mechanic is the <course> default for everyone; a course that deviates
(and it can change per semester) names its own `provision_strategy` in its L3 wrapper to override.
Named strategies:
- **`master-strip`** — a solution-master repo exists (`<COURSE>{CODE}`): push the audited solution to it
  (SHA green/100; missing master → RAISE, don't auto-create), then strip a `/tmp` copy to a compiling
  stub (keep signatures + driver), fresh `git init` + one commit, `gh repo create <Starter> --private
  --source=. --push`, mark `--template`. (Do NOT `--template <solution>` — stamps the solution as
  commit 1.) *(<course>, <course>.)*
- **`dir-to-starter`** — no master (a master would duplicate): build the Starter **directly from the
  local dir** (strip → fresh push), skip the master entirely. *(e.g. <course> reusing <course> dirs.)*
- **(add per course as they migrate — <course> / <course> / V15 each name their own.)**

Whatever the strategy, the invariant above still holds; L1 verifies it in GATE C.

**Register** — `ops/config.sh <org> add-assignment <course> <CODE> <Starter> [FROM] [UNTIL]`. Exam/quiz
repos MUST gate the window (`FROM`/`UNTIL`) and be private.

**Every repo ships a `README.md`** — one-line task, the outline of what to edit, and compile / run /
test as **separate commands (never chained with `&&`** — chaining hides the error-check students must
read). Task only; never the answer. Full spec lives on Canvas.

**Fixing a test after release = THREE places, in order:** `① local dir → ② solution master → ③ Starter`
(verify all three by `md5`). Miss one and the next accept gets the old test. **Do not patch
already-graded student repos** — the patch commit re-triggers every autograder and can flip a posted
grade; fix forward. (Patching UNGRADED student repos to unblock a broken test is allowed and is the
sanctioned exception in `Access/GitHub.md` §3 — verify each rerun by your commit SHA.)

---

## GATES (every gate BLOCKS — on fail STOP + report)

- **GATE A0 — instruction fidelity (§0):** faithful solution → **all graders 100**, adversarial →
  **fails the intended case(s)**. Either side wrong ⇒ fix the test or the instruction before continuing.
- **GATE A — audit done:** §1–§4 pass; word-hunt stripped (or instruction made explicit); edges added;
  no dead tests; instruction-error note written.
- **GATE B — 100/100:** local yml-verbatim run = 100 with the known-good solution **and** the Actions
  run for your SHA is green/100.
- **GATE C — shipped artifact:** solution-master remote exists (missing → RAISE) + green; the Starter
  satisfies **all six** properties of the Part C definition, checked by RE-FETCH (non-empty · stubbed ·
  compiles · harness present · private+template · registered). An empty or unregistered Starter is a
  FAILED build, not a "mostly done" one.
- **GATE D — no silent harness bug:** if `COMPILE`/`RUN` = 0 while asserts look fine (or the reverse),
  the runner/redirect silent-fail is present → report the STARTER as broken, do not pass it.

### Gate artifacts (absorbed 2026-08-09 from `CourseGlobalWorkflow/Discipline/Proof.md`)

A gate passes only when its artifact file exists and every `result`/`conclusion` inside it is
`pass`/`success`. Naming, folder and the required final line: `Discipline/Proof.md`.
Not yet slimmed — three phase names are carried over verbatim; map them onto the gates above
when this skill is next revised.

**`5-QA Check 1`** — source `gh run view <id> --json conclusion,jobs`. PASS only if `conclusion=success`
and every step's `conclusion=success`.
```json
{
  "run_url": "https://github.com/.../actions/runs/12345678",
  "run_id": 12345678,
  "conclusion": "success",
  "steps": [{"name": "compile_main", "conclusion": "success"}]
}
```

**`3-Git gate`** — required before the Starter is shipped and registered in the org-hub
(`code/git_starter_build.py`, GATE C). Artifact missing or any field empty → STOP, register nothing.
```json
{
  "local_test_log_path": "<absolute path>",
  "template_repo_sha": "<sha>",
  "github_contents_listing": [...]
}
```

**`2-PA`** — logs saved verbatim from `make test` / `pytest` stdout (use `tee`). FAIL if any log shows
`FAILED` / a non-zero exit / a missing tag.
```json
{
  "compile_log_path": "<absolute path>",
  "test_run_log_path": "<absolute path>",
  "tags_passed": ["T1","T2","T3","T4"],
  "all_passed": true
}
```

---

## Rules

- **One coherent run, same session** — hold CODE, repo names, SHA in one flow.
- **Never guess repo names** — resolve from the org-hub config map; confirm with one `gh api repos/…`
  call (404 → STOP).
- **Repo creation = Starter only.** The solution master pre-exists; missing → RAISE.
- **L1 owns no language mechanics.** If you catch yourself writing `g++`/`pytest`/`Catch2` here, it
  belongs in an L2 skill. If you catch yourself writing an org/prefix/course id, it belongs in L3 config.

## Layer references
- **L2 language skills:** `languages/python-pytest.md` · `languages/cpp-stdout.md` ·
  `languages/cpp-catch2.md` (fill `COMPILE`/`RUN`/`ASSERT`).
- **L3 course wrappers:** each course's `…-git-repo` skill (org, prefix, language, chapter→model map).
- **Policy:** `CourseGlobalWorkflow/GRADING.md` (rubric), `Access/GitHub.md` (autograder
  classroom.yml rules), `Access/GitHub.md`.
- **Origin ports being folded in:** <school> <course> `git-homework` (Java), <course> `git-assignment`
  (Python), <course> `github-repo-build`/`github-repo-test` (C++).
