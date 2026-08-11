# L2 — Java · JUnit 5 console launcher (T1–T4 tag groups)

Fills L1's `COMPILE` / `RUN` / `ASSERT` for **Java**. One skill covers both styles — the *callee*
differs, not the mechanism: JUnit compiles against the student's `Main` and calls it directly.

**Authority is the repo's `classroom.yml` (L1 CORE RULE).** Read its `command:` lines; run verbatim.

## ⛔ THE FILE SOURCE — diff against it before every build

```
$CANVAS_LMS_ROOT/.claude/skills/git-asmt-repo/languages/java-junit/template/
    .github/workflows/classroom.yml     <- the ONE true grader config
    + the harness files this model needs
```

An existing course repo is a COPY of an OLDER template and drifts silently. Diff the repo's
`classroom.yml` against this template BEFORE building or shipping, and never edit a repo's yml to
"fix" it — **change the template, then propagate** (local dir -> solution master -> Starter). Full
rule: `git-asmt-repo/SKILL.md` STEP 0b.

---

## ⛔ GATE L2-0 — decide the TEST STYLE before any repo is created

**No repo, no Starter, no config entry until the style is decided and written down.** Two styles:

| Style | Graded unit | Assertion |
|---|---|---|
| **function test** | a named method (`findGreatest`, `traverse`, `findMin`) | call it → assert the **return value / the array state it mutated** |
| **output test** | the whole program (`main`) before methods are taught | run `Main`, **capture stdout**, assert values in the captured text |

**How to decide** — read the assignment instruction:
- it names a method + parameters + return ⇒ **function test**
- it only says "write a program that prints …" ⇒ **output test**

**Default (implicit rule, now explicit): before the functions/methods chapter (≈ Ch6) = output test;
from the functions chapter on = function test.** The default is a fallback, not a licence to assume.

**If the instruction is ambiguous → STOP and ask the instructor which style.** Do not guess, do not
create the repo "and fix it later" — the style decides the test file, the stub shape, and the rubric.

---

## Slots

- **COMPILE** — `javac -cp lib/junit-platform-console-standalone-1.10.2.jar -d out src/*.java test/*.java`
- **RUN** — `java -cp out Main < data/input.txt`
- **ASSERT** — per tag group:
  `java -jar lib/junit-platform-console-standalone-1.10.2.jar execute -cp out --include-tag T<n> --scan-class-path --fail-if-no-tests`
  The console launcher exits non-zero if any item in that tag fails, so **one grader = one group**.

**Grader layout** (`autograding-command-grader@v1`): `Compile 10 + Run 10 + T1..T4 ×20 = 100`.

### ⛔ Java-specific killer: LITERAL jar path, never an `env:` var
The grader step does **not** receive the workflow/job `env:`. `javac -cp "$JUNIT" …` runs with an EMPTY
classpath → `package org.junit.jupiter.api does not exist` → **every student fails compile**. Hard-code
`lib/junit-platform-console-standalone-1.10.2.jar` in every `command:`. A local shell expands `$JUNIT`,
so **local success is not evidence** — only an Actions run is (L1 Part B).

### stdin is NOT a variant
Always ship `data/input.txt` and always redirect in the Run grader. A program that reads nothing is
unaffected; a program that reads stdin without the redirect throws `NoSuchElementException` → Run 0.
JUnit cases inject their own input (`System.setIn(new ByteArrayInputStream(...))`); `data/input.txt`
serves the Run grader only.

---

## Files this model requires (GATE A)

`src/Main.java` · `test/MainTest.java` · `lib/junit-platform-console-standalone-1.10.2.jar` (committed,
~2.6 MB) · `.github/workflows/classroom.yml` · `data/input.txt` · `.gitignore` (`out/`) · `README.md`.

Template: `languages/java-junit/template/` (the skeleton is owned HERE, not by a course).

---

## Test authoring

- 4 tag groups, each with REAL items: `@Test @Tag("T1")` … Add an item = add a method, **no yml change**.
- **function test** — call and assert the value:
  `assertEquals(30, Main.findGreatest(30, 25, 20));` · for a mutating method assert the resulting array
  state (`assertEquals(Arrays.asList(0,1,3,7,4,2,5,6), Main.visited)`).
- **output test** — capture and match loosely:
  ```java
  static String out() {
      PrintStream old = System.out;
      ByteArrayOutputStream b = new ByteArrayOutputStream();
      System.setOut(new PrintStream(b));
      try { Main.main(new String[0]); } finally { System.setOut(old); }
      return b.toString();
  }
  ```
  Assert **values, case-insensitively, as substrings in order** — never exact lines, never whitespace
  counts, never a label word the instruction did not require. When case IS the answer, do not lowercase.
- Edge coverage per L1 §3 (empty, single, negatives, duplicates, boundary, largest-N). One failing item
  fails its whole 20-pt group, so every item must be a case a correct solution passes and a
  plausible-wrong one fails.

### ⛔ SOURCE-constraint tests must read CODE, not comments (A61/A67, 2026-07-30)
A "don't use `Math.max` / `Arrays.sort`" test that greps `src/Main.java` reads the **comments too** — and
the starter's own instruction comment contains the forbidden name, so **correct students fail**. Strip
comments first, and prove both directions before shipping:
```java
static String code() { return src().replaceAll("(?s)/\\*.*?\\*/", " ").replaceAll("(?m)//.*$", " "); }
```
`token in a comment → group PASSES` · `token in real code → group FAILS`. Also grep the shipped starter
for the token: if the instruction text names it, either strip comments (above) or word the instruction
without the literal.

### GUI / Console variant — no JUnit
`JOptionPane` throws `HeadlessException` on CI and `System.console()` is null when stdin is piped, so the
program cannot be value-tested. Use the **pytest source-parser** model instead: `classroom.yml` =
`javac src/Main.java -d out` (20) + `pytest -rP -m T1..T4` (4 × 20), a `test_source.py` that reads
`src/Main.java` and asserts the lesson API is present (be lenient; accept alternatives), and `pytest.ini`
registering the markers. No JUnit jar, no `test/`. Same comment-stripping rule applies.

---

## §0 harness (how L1's fidelity check runs here)

- **Faithful** `Main.java` written from the instruction only → run every grader command verbatim →
  **expect 100**. A failing group = the test demands something the instruction never states (§2) or an
  unstated edge (§3).
- **Adversarial** `Main.java` (the plausible-wrong approach — e.g. `max = 0` init, a loop instead of
  recursion) → **expect the covering group to fail**; if it passes, the case is missing (§3).
Both live in `/tmp`, never committed.

---

## Cutting the Starter (Java specifics)

Stub **only** the method bodies the student must write: keep the `class Main`, the field declarations,
the method signature, and the driver in `main` so the **stub still compiles** (JUnit must resolve the
symbols — a stub that fails to compile makes every grader report a compile error instead of the intended
red). Replace the body with `// TODO: …`; a non-`void` method gets a neutral `return` value. Keep
`test/MainTest.java`, the jar, `classroom.yml`, `data/input.txt`, `.gitignore`, README (task only).
Expected shipped state: **Starter run = failure** (stub), **solution master run = success/100** (L1 GATE C/D).

Origin: <school> <course> `git-repo-build` (Java/JUnit, T1–T4), folded into L2 on 2026-07-30.
