# Proof

State a result only as a file. Write the artifact, then point at it.

A phase passes when its artifact exists, matches the schema its own owner defines, and every
`result` / `conclusion` inside it says pass. No artifact, no phase.

Name it `{Code}_{phase}_{YYYYMMDD-HHMM}.json` in the QA artifacts folder (`Where/CourseConfig.md`).

End the phase with exactly this line:

```
phase=<name> result=<pass|fail> artifact=<absolute path>
```

Quote the artifact verbatim to say anything about the outcome.

Each phase's schema lives with whoever runs it — grading in `skills/grade/SKILL.md`, repo build in
`skills/git-asmt-repo/SKILL.md`.
