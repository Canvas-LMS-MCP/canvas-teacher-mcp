# L2 — C++ · Catch2 unit test (functions-on chapters)

Fills L1's `COMPILE` / `RUN` / `ASSERT` for a **C++ program whose graded unit is a FUNCTION**. A
compiled binary can't be imported, so a **Catch2 harness (`tests.cpp`) links the student's function
and checks its RETURN value**. Used for the functions-on chapters (curriculum map:
`functions-on → this skill`).

**Authority is the repo's `classroom.yml` (L1 CORE RULE).** Read its `command:` lines; run verbatim.

## ⛔ THE FILE SOURCE — start every build by DIFFING against it

```
$CANVAS_LMS_ROOT/.claude/skills/git-asmt-repo/languages/cpp-catch2/template/
    main.cpp · main.hpp · tests.cpp · catch.hpp · Makefile · README.md · .gitignore
    .github/workflows/classroom.yml          ← the ONE true grader config
```

**Before building or shipping ANY repo: diff the repo's `classroom.yml` against this template.**
An existing course repo is usually a copy made from an OLDER template and has drifted. Do not
assume the repo is current, and do not edit a repo's yml to "fix" it — **change the template, then
propagate.** (2026-08-02: <course> A1102 / A1103 / FQSU26 all still carried the retired
`-fsanitize=address` grader; nobody noticed because nothing pointed here.)

Same layout for the other L2 skills: `languages/<cpp-stdout|python-pytest|java-junit>/template/`.

## Graders the template ships (6, summing to 100)

| # | step id | test-name | command | max |
|---|---|---|---|---|
| 1 | `compile_tests` | Compile tests.cpp (compile check) | `g++ -std=c++17 -Wall -Wextra main.cpp -o main && timeout 10 ./main` | 10 |
| 2 | `compile_harness` | Compile tests.cpp (harness builds) | `g++ -std=c++17 -Wall -Wextra -c tests.cpp -o /tmp/tests.o` | 10 |
| 3–6 | `t1`…`t4` | Basic test [T1] / T2 / T3 / T4 test | `make test ARGS="[T1]"` … `[T4]` | 20 each |

`runners: compile_tests,compile_harness,t1,t2,t3,t4`

⛔ **No `-fsanitize=address`, anywhere.** Grader 2 is a HARNESS-BUILD check, not a memory check —
it proves `tests.cpp` still compiles against the student's header. The sanitizer was dropped
because it is environment-sensitive and produced failures unrelated to the student's algorithm. A
repo still naming that grader `Sanitize Check` / `g++ -fsanitize=address (sanity check)` is on the
OLD template.

## Slots

- **COMPILE** — `g++ -std=c++17 -Wall -Wextra main.cpp -o main` (grader 1), and
  `g++ -std=c++17 -Wall -Wextra -c tests.cpp -o /tmp/tests.o` (grader 2).
- **RUN / ASSERT** — the yml's `make test`:
  ```
  make test   →   g++ --std=c++17 tests.cpp -o programtest   →   ./programtest $(ARGS)
  ```
  `tests.cpp` (Catch2) calls the student's function and `REQUIRE`s the return value; each `SECTION`
  is one case. There is no stdout-capture / `result*.txt` here — the **return value** is the check.

## Files this model requires (GATE A)
`main.cpp` · `tests.cpp` · `catch.hpp` · `Makefile` · `classroom.yml`.

## Test authoring (Part A §3 in Catch2 terms)
One `SECTION` per case, `REQUIRE(func(args) == expected)`. Cover the edges the spec implies (empty,
single, negatives, duplicates, boundary, largest-N). Never an empty `SECTION` / trivially-true
`REQUIRE`. One failing `SECTION` fails its grader group.

## §0 harness (how L1's fidelity check runs here)
- **Faithful** function (instruction-only) → `make test` → expect all `SECTION`s pass. A failing one =
  it requires behaviour the instruction never states (§2 semantics) or an unstated edge (§3).
- **Adversarial** function (plausible-wrong) → expect the covering `SECTION` to fail; if it passes, add
  the case (§3).

## Cutting the Starter (C++ specifics)
Stub the edited file(s): replace each function body whose first line is `// TODO` with a stub — keep the
signature + the TODO comment; non-`void` → add `return {};`. (The general rules — delete any file that
still holds the answer, `make clean`, verify the shipped Starter by SHA — live in L1 Part B/C.)

**A struct/class assignment has two traps `code/git_starter_build.py` now handles — verify both anyway
by reading the shipped `main.hpp`, because GATE C only checks that the file DIFFERS from the solution,
which a half-stripped file also does:**
- **A constructor takes no `return {};`** — it has no return type, so the stub would not compile
  ("constructor must not return a value").
- **Strip EVERY overload of a name, not the first.** `Scores()` and `Scores(int[], int)` share a name;
  stopping at the first leaves the second body — a shipped answer. *(Both hit 2026-08-02 on <course>
  A1102 / A1103, the course's first struct assignments.)*
- List every student-editable symbol in `--strip`, members included:
  `--strip "main.hpp:Ctor,method1,method2,func1,func2"`.

## Common miss (from the A31 proof)
A repo may ship a `Makefile` with a `test` target **and** pytest files but no `tests.cpp` — the yml
may actually run the pytest/stdout model instead. **Never infer the model from files present; read the
yml.** (If this repo's yml runs pytest+run.sh, use `cpp-stdout.md`, not this skill.)

Origin: <course> `github-repo-test` (Ch6+ Catch2 model).
