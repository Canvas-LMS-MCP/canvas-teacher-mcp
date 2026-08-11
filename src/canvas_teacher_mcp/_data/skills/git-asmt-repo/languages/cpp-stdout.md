# L2 — C++ · stdout output test (pre-function chapters)

Fills L1's `COMPILE` / `RUN` / `ASSERT` slots for a **compiled C++ program that reads stdin and
prints**, tested by **capturing stdout** (the program exposes no callable return to the harness — a
binary can't be imported). Used for the pre-functions chapters (the L3 wrapper's curriculum map sends
`before-functions → this skill`).

**Authority is always the repo's `classroom.yml` (L1 CORE RULE).** The shapes below are the typical

## ⛔ THE FILE SOURCE — diff against it before every build

```
$CANVAS_LMS_ROOT/.claude/skills/git-asmt-repo/languages/cpp-stdout/template/
    .github/workflows/classroom.yml     <- the ONE true grader config
    + the harness files this model needs
```

An existing course repo is a COPY of an OLDER template and drifts silently. Diff the repo's
`classroom.yml` against this template BEFORE building or shipping, and never edit a repo's yml to
"fix" it — **change the template, then propagate** (local dir -> solution master -> Starter). Full
rule: `git-asmt-repo/SKILL.md` STEP 0b.
layout; read the yml and run its exact `command:` lines in its order.

## Slots

- **COMPILE** — `g++ -std=c++17 -fsanitize=address -Wall -Wextra -c main.cpp -o /tmp/main.o`
- **RUN** — `data/run.sh`: compiles then, for each n, `timeout 10 ./main < data/data<n>.txt > result<n>.txt`
  ```sh
  g++ -Wall -Wextra --std=c++17 main.cpp -o main
  timeout 10 ./main < data/data1.txt > result1.txt   # … data2/3/4 → result2/3/4.txt
  ```
- **ASSERT(case)** — `pytest -rP -m T<n>`: a `@pytest.mark.T<n>` test opens `result<n>.txt` and checks
  the **printed VALUES in sequence** with a forward-search regex — never whole-line/anchored, never a
  label word.
  ```python
  def regex_test(expected, lines):     # values only, in order, forward search
      i = 0
      for token in expected:
          for j in range(i, len(lines)):
              if re.search(token, lines[j]): i = j + 1; break
          else: assert False, f'Expect: {token}'
  ```

## ★ ORDER DEPENDENCY (the one trap of this model)
The `T<n>` graders read the `result<n>.txt` that **`data/run.sh` produced** → **RUN must run before
the T asserts**, in that order (Compile → Run → T1..T4), or pytest fails `no such file: result1.txt`.

## Files this model requires (GATE A)
`main.cpp` · `main_test.py` · `pytest.ini` · `data/run.sh` · `data/data*.txt` · `classroom.yml`.

## Output-matching rules (CS-house, forbidden list)
Values only, in sequence. **Forbidden:** `^…$`, `re.fullmatch`, `== "…"`, and label words
(`MAX`/`Total`/`Sum:`). Floats: `r'20\.\d+'`, not `r'20\.00'`.

## GATE D signature (silent harness bug)
`Compile`/`Run` = 0 while the `T`s look fine ⇒ the `data/run.sh` / stdin-redirect silent-fail →
report the STARTER as broken, not the student.

## §0 harness (how L1's fidelity check runs here)
- **Faithful** `main.cpp` prints exactly what the instruction says → `run.sh` + `pytest -m T*` → expect
  100. A T that fails = it greps a value/label the instruction never told the student to print (§2) or
  a case the instruction didn't state (§3).
- **Adversarial** `main.cpp` (plausible-wrong, e.g. `max=0`) → expect the covering T to fail; if it
  passes, add the data case (§3).

Origin: <course> `github-repo-test` (Ch2–5 model) + `github-repo-build` Part A.
