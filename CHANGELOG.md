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

### Removed
- `canvas_root.record_root()` and the `~/.canvas-teacher-mcp/root` pointer it wrote.

## [0.1.0] - TBD

First release.
