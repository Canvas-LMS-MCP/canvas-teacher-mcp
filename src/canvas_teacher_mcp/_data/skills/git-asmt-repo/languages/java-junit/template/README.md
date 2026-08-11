# src — <course> assignment source template (copy-from)

The **copy-source** for every <course> GitHub assignment. Never handed to students directly;
each assignment is built by copying this dir, then editing `src/Main.java` + `test/MainTest.java`.

## What stays vs. changes
| File | Per assignment |
|---|---|
| `.github/workflows/classroom.yml` | **UNCHANGED** (compile + run + T1..T4 + reporter) |
| `lib/junit-platform-console-standalone-1.10.2.jar` | **UNCHANGED** (JRE test runner) |
| `.gitignore` | **UNCHANGED** |
| `src/Main.java` | **EDIT** — the assignment's program (class stays `Main`) |
| `test/MainTest.java` | **DEVELOP** — fill ALL 4 tag groups with real `@Test` items (never an empty `assertTrue(true)`; split a small task into 4 checks) |

## Test model (4 groups, JUnit `@Tag`)
`classroom.yml` runs 4 groups: `--include-tag T1 … T4`. Each group is one grader (20 pts),
and **each group holds many `@Test` items** sharing that tag — add items by adding tagged
methods, no yml change. Format mirrors the latest <course> `classroom.yml` (autograding-command-grader);
the JUnit/JRE invocation (console-standalone jar, stdout capture) mirrors <COURSE>-Starter.

## Local test (before pushing a starter)
```bash
javac -cp lib/junit-platform-console-standalone-1.10.2.jar -d out src/*.java test/*.java
java -cp out Main
java -jar lib/junit-platform-console-standalone-1.10.2.jar execute -cp out --include-tag T1 --scan-class-path
```

See the project skill `.claude/skills/git-homework-creation.skill.md` for the full workflow + strip policy.
