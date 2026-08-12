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
- Registering a slug that exists ANYWHERE in the tree is refused and names the file that holds it.
  The index is slug → path, so a second file with the same stem decided the course by glob order.
- Credential files are written `0600`, and an existing world-readable one is corrected.
- `github_org` and `db_path` on an unregistered course raise naming the field instead of returning
  `None`, which surfaced far away as a silent no-op.

### Removed
- `canvas_root.record_root()` and the `~/.canvas-teacher-mcp/root` pointer it wrote.

## [0.1.0] - TBD

First release.
