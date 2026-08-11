---
name: create-announcement
description: "GLOBAL, config-driven — generate a weekly Canvas announcement from a module's contents for ANY course. Use when the user says make/write the weekly announcement, week N announcement, or announce this week. Reads the module, summarizes what to read/watch/do/submit, lists graded items with due dates, and closes warmly. Course coordinates come from course_config.load(<course_slug>) (course_id, school, token) — nothing hardcoded. PREVIEW-first; sends emails only on the instructor's explicit go. Invoke with the course_slug + week or module id."
---

# Weekly Canvas Announcement (GLOBAL, config-driven)

Generate the **weekly Canvas announcement** for a module — a friendly, beginner-facing "here's your week"
note. The email sibling of the **`agenda-wrapup`** skill: all three (Agenda, Wrap-up, Announcement) are
derived from the **same module read**, but this one **sends email to every student**, so it lives in its
own skill and is invoked deliberately — never automatically bundled with the pages.

> **Course coordinates are NEVER hardcoded.** Read them from `course_config.load(<course_slug>)`:
> `course_id`, `school`, `canvas_base_url`, `canvas_token_env`. e.g. `<course>` → school `<school>`, course
> `58774`, token `<SCHOOL>_CANVAS_TOKEN`; `<course>` → school `<school>`, course `69095`. The user names the
> `course_slug` (or you infer it from the working directory); everything else comes from the config.

## Step 1 — read the module ONCE (via `canvas_rest`)
Let `base = cfg["canvas_base_url"]`, `cid = cfg["course_id"]`, `tok = canvas_token_auth.get_token(cfg["canvas_token_env"], base)`.
1. **Find the module**: `cr.list_modules(base, tok, cid)` → match the week (`[Week N]`, `Week N`), or the user
   gives the module id. A week can span multiple modules → collect all.
2. **Items**: `cr.get(base, tok, f"/courses/{cid}/modules/{mid}/items")`.
3. **Categorize** by item `type` + SubHeader labels: Readings/Slides, Videos, Pages/guides, Assignments,
   Quizzes, Exams.
4. **Due dates**: Assignment → `cr.fetch_assignment(base, tok, cid, content_id).due_at`; Quiz →
   `cr.fetch_quiz(...).due_at`. **ALWAYS `cr.to_localtime(due)` → PDT/PST, never raw UTC.** Null → "No due date set".

## Step 2 — write the announcement (these parts, in order)

### 1. Friendly overview — "your week at a glance"
A kind, plain-English guide. Cover:
- **가) Everything this week, summarized** — what to **read**, what to **watch**, what to **do**, what to
  **submit** — all in one short scannable list.
- **나) What you'll learn / the goal** — what you learn this week, and **what you'll be able to do by the end
  of the week** (concrete outcome, motivating).
- **다) Skill check** — a short "can you do this now?" check at the end: if you can, that's **the skill you
  gained this week.** (Frame success as a checkpoint they can self-verify.)

### 2. What to submit — a TABLE (check this against the module)
Verify the graded items and list them:
| Type | Title | Due |
|---|---|---|
| Assignment | … | <PDT date> |
| Exam / Quiz | … (a brief one-line guide to its content) | <PDT date> |
Every due date via `to_localtime` (PDT). For exams/quizzes, add a light one-line hint of what's covered.

### 3. Cheer up — warm closing
Encouragement + an easy **"reach out anytime — happy to help"** line + kind words. **Vary it — do NOT use the
same formulaic closing every week.** Sound human, not templated. (This is why the announcement is
AI-authored prose, not a deterministic render like the agenda's mechanical table.)
- **★ Sign with the instructor's real name — `Kyu Lee`.** NEVER a generic placeholder like "Your instructor",
  "Your teacher", or "The instructor". The name is the signature; end the announcement with `Kyu Lee`.

## Mechanics — ★ use the CANONICAL engine, NEVER hand-code the API
**All sending goes through `canvas_core/announcements.py`** (+ `canvas_auth.session.CanvasSession`). Do NOT
hand-roll `POST /discussion_topics` / raw `urllib` / a Bearer token in a scratchpad script — that is a
canonical bypass (RULE #0e). **Canvas REJECTS a `published:false` announcement (HTTP 400) → there is NO draft
state**, so the engine model is **PREVIEW → instructor "go" → SEND** (no `delayed_post_at`, no draft — those
are not in the engine; do not hand-code them):
1. **Write the announcement to a `.html` file**: `<!-- title: ... -->` frontmatter + the HTML body.
2. **Preview (safe — HTTP 400, 0 emails):**
   `python3 -m canvas_core.announcements <school> <course_id> <file.html>`
   (school + course_id from the config; or `announcements.post_announcement(s, cid, title=T, message=M, published=False)`).
3. **Send LIVE — instructor "go" ONLY:** call the function directly (ONE existing call, do not re-derive):
   `announcements.send_announcement(CanvasSession(school), course_id, title=T, message=M, confirm=announcements.SEND_CONFIRM)`
   (`post_announcement(..., published=True)` is the same send). Report the returned id / url.
   - **If this call is refused in auto-mode = NOT a code problem** (the preview already proved the
     code, auth, and HTML are good). **Fix: the instructor switches to manual/plan permission mode,
     then the same call runs.** Do NOT edit code, reword, or build a driver.
- `CanvasSession(school)` supplies the credential automatically (the config's school; token schools use the
  Bearer token) — never paste a token.
- Plain Canvas HTML, inline styles only (Canvas strips `<style>`). Code font on any command/path. No emoji.
- Back up before overwriting an existing announcement; merge rather than blind-replace.

## ★ Change-trigger — announcements are DOWNSTREAM of the module (keep in sync)
This announcement is **derived from** the module's pages/assignments/quizzes/exams + their due dates. So it is
a **downstream dependency**: whenever any of those change, this announcement is **stale and must be
regenerated.** The course is a small network — one edit ripples.
**Re-run this skill (regenerate the week's announcement) whenever, in that week's module, any of these change:**
- an assignment/quiz/exam is **added, removed, renamed, or its due date changes**;
- a page/reading/slide item is **added, removed, or retitled**;
- the module is **reordered** in a way that changes what's "this week".
(The same trigger applies to the weekly Agenda/Wrap-up pages — they share this module-derived data.)

## Reference
- `agenda-wrapup` skill — the page sibling (Agenda + Wrap-up) built from the same module read.
- Per-course config = `course_config.load(<course_slug>)` (course_id, school, token_env, base).
- Canvas HTML/upload policy (inline styles, code font, no emoji, back-up-before-overwrite) —
  `CourseGlobalWorkflow/Access/Canvas.md`.
