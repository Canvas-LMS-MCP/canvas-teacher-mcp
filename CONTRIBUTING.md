# Contributing

Thanks for considering a contribution. This project is small and friendly to changes; here's the lay of the land.

## Repo layout

One package, `canvas-teacher-mcp`, under `src/canvas_teacher_mcp/`:

- `auth/` `rest/` `core/` — credentials, one REST client, Canvas objects.
- `pages/` `quiz/` `richdoc/` — authoring.
- `grading/` — the grading engine.
- `servers/` — one MCP sub-server per package above; `server.py` mounts them.

`skills/`, `workflow/` and `hooks/` ship as data and are copied into the user's tree at setup —
see `docs/ARCHITECTURE.md`. Documentation lives in `docs/`.

## Dev setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

For browser-based login during cookie-mode development, you'll also need:

```bash
playwright install chromium
```

## Testing

(To be filled in when packages have tests.)

## Pull requests

- Keep PRs focused on one concern.
- Update the relevant `docs/` file if you change behavior.
- Don't include local config, session files, or anything from `.dev/`.

## Reporting bugs / asking questions

Open a GitHub issue. Include the package version, Python version, OS, and a minimal reproduction if possible.

## Security

Security-sensitive issues: see [SECURITY.md](SECURITY.md).
