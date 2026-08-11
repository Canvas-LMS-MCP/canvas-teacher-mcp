# Data — what we store

- Store two things: `students.accommodation` (+ `notes`) and `late_waivers`. Read everything else
  live — Canvas for assignments and submissions, GitHub and the org-hub log for repos.
- Store no grade.
- Keep the DB path in the project `.mcp.json` only. A same-named `sqlite` server in
  `~/.claude.json` shadows it and every query hits the wrong DB.
- Open read-only. The instructor writes rows by hand.
- Key both tables by their Canvas ids — `uid`, `canvas_id` — never the engine's `code`.

```sql
CREATE TABLE students     (uid INTEGER PRIMARY KEY, accommodation TEXT, notes TEXT);
CREATE TABLE late_waivers (canvas_id INTEGER, uid INTEGER, grace_until TEXT, reason TEXT,
                           PRIMARY KEY (canvas_id, uid));
```
