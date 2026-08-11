# L2 — Python · pytest (return-value test)

Fills L1's `COMPILE` / `RUN` / `ASSERT` for **Python**. Python is interpreted, so pytest **imports
`main` and calls it directly, asserting on the RETURN value** — for BOTH the non-function
(whole-program) and function styles. **One skill covers both** (unlike C++, which must split), because
both reduce to *import → call → check return*. The callee differs, not the mechanism.

**Authority is the repo's `classroom.yml` (L1 CORE RULE).** The <course> layout: `compile 10 + run 10

## ⛔ THE FILE SOURCE — diff against it before every build

```
$CANVAS_LMS_ROOT/.claude/skills/git-asmt-repo/languages/python-pytest/template/
    .github/workflows/classroom.yml     <- the ONE true grader config
    + the harness files this model needs
```

An existing course repo is a COPY of an OLDER template and drifts silently. Diff the repo's
`classroom.yml` against this template BEFORE building or shipping, and never edit a repo's yml to
"fix" it — **change the template, then propagate** (local dir -> solution master -> Starter). Full
rule: `git-asmt-repo/SKILL.md` STEP 0b.
+ T1..T4 ×20 = 100`.

## Slots

- **COMPILE** — no compile step; the "compile" grader is a syntax/import smoke (`python3 -c "import main"`).
- **RUN + ASSERT** — `pytest -rP -m T<n>`. The test `import main`, feeds stdin, swallows stdout, and
  asserts on the **return value**:
  ```python
  import main, io, sys
  @pytest.mark.T1
  def test_case():
      sys.stdout = io.StringIO()               # swallow prints (not the check)
      # sys.stdin = io.StringIO("40\n40\n20")  # inject input if the program reads stdin
      r = main.main()                          # non-function: main() RETURNS the answer
      # r = main.some_func(args)               # function style: the function RETURNS
      sys.stdout = sys.__stdout__
      assert r == EXPECTED                      # the RETURN value is the check
  ```

## The two styles (SAME mechanism — no split)
- **Non-function (whole-program, early chapters, method-2):** `main.main()` is written to **RETURN**
  the result (e.g. `return nums`); the test checks that return. (<course> A00Starter, A05.)
- **Function (method-1, most assignments):** `import main; r = main.<func>(args); assert r == expected`,
  one assert per case, edges covered. (<course> A51/A71/M-series/Final.)

The L3 wrapper only needs to say **which callee** (`main` vs a named function) — a parameter, not a
different skill.

## Files this model requires (GATE A)
`main.py` (with strip markers) · `main_test.py` (+ `pytest.ini`) · `classroom.yml`.

## §0 harness (how L1's fidelity check runs here)
- **Faithful** `main.py` (instruction-only) → `pytest -m T*` → expect 100. A T failing = it requires a
  return/behaviour the instruction never states (§2) or an unstated edge (§3).
- **Adversarial** `main.py` (plausible-wrong) → expect the covering T to fail; if it passes, add the
  case (§3).

## Note
Because Python asserts the RETURN directly (no stdout parsing), there is **no C++-Ch2–5-style output
word-hunting risk** for return-checked cases — the §2 concern shrinks to any test that *does* grep
printed text. Keep tests return-based where possible.

Origin: <course> `git-assignment` (Python/pytest, T1–T4). Folds in when <course> migrates to L3.
