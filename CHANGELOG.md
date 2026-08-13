# Changelog

All notable changes to this project will be documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial scaffolding for a single package, `canvas-teacher-mcp`.
- Documentation in `docs/`: architecture, configuration, conventions.
- MIT license.
- Connect-time instructions state the root requirement when none is configured, naming the key,
  the per-client config file and the restart, so an assistant can act on it before calling a tool.

### Changed
- `CANVAS_LMS_ROOT` is required. The server no longer keeps a root of its own — the client's `env`
  block is the single visible source. Documentation previously promised that setup would ask for a
  root and record it; neither was implemented, and the design is now one source rather than two.
- Registering a course proposes `<ROOT>/<SCHOOL>/<COURSE_CODE>/`, putting the school in the path
  instead of only inside the file. Deeper trees still work; `course_dir` overrides the proposal.
- A course's `canvas_url` is stored as `https://<domain>/courses/<id>`, not as the URL pasted in.

- A course can be reached without being registered: `load` accepts a course URL or id and
  synthesizes coordinates, writing under `<ROOT>/.claude/output/<course_id>/`. Registration is
  what earns a slug, a folder, and the instructor-supplied fields. With several schools
  registered, a bare id is refused — only the URL says which Canvas it means.
- `setup` reports registered courses and, when there are none, what to do next. The schools
  branch already did; a report that stopped after "signed in as …" read as "nothing left to do".
- `setup` refuses a root that is a file or is not writable, instead of failing later somewhere else.
- `post_grades` states up front that posting needs Claude Code on a client that keeps no session
  transcript. The view gate cannot be satisfied there, and its "transcript not found" reads as a
  fixable bug when nothing is missing.

### Fixed
- Adding questions rebuilds the description summary and clears Canvas's stale counts. A quiz whose
  questions changed and whose description did not states the wrong number of questions and the
  wrong total, and `finalize_quiz` reads as an optional last step nobody has to take.
- The generated part of a description is fenced, so a rebuild replaces its own work and leaves the
  instructor's writing alone. A description written before the fence existed is treated as theirs
  in full.
- A course URL is enough to start. It names the school too, so an unknown school is registered
  from it and the URL is held beside the credential; once the token is in place the next `setup`
  registers the course without being told the URL again. Before, the instructor was sent away for
  a different URL — and the course URL is the only address a browser ever shows them.
- `parse_question_bank` says why it wrote nothing instead of returning a bare null. Three sessions
  read that null as "this course has no output directory" when the answer was that no course had
  been named.
- `parse_question_bank` takes `course` and `save`, and writes the source text, the quiz JSON and
  the preview into that course's `quiz_build/Ch<N>/` — what the command line has always written.
  The tool had no course, so it could not name an output directory, and the skill document went
  on describing files nobody was writing.
- Package-relative imports restored in seven places where an absolute, operational-tree module
  name stood instead: registering a course from its URL, the grading credential path, the report
  render, Stage-B prepare, and the question-bank writer. Most sat inside functions, so the package
  imported, the server started and all 69 tools listed while the first real call died. Four were
  introduced in 0.0.3 by a verbatim sync from the operational tree; three predated it.
- Registering a slug that exists ANYWHERE in the tree is refused and names the file that holds it.
  The index is slug → path, so a second file with the same stem decided the course by glob order.
- Credential files are written `0600`, and an existing world-readable one is corrected.
- `github_org` and `db_path` on an unregistered course raise naming the field instead of returning
  `None`, which surfaced far away as a silent no-op.

### Removed
- `canvas_root.record_root()` and the `~/.canvas-teacher-mcp/root` pointer it wrote.

## [0.1.0] - TBD

First release.
