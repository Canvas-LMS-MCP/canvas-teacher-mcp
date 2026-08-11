# Canvas

Auth (token vs cookie, where credentials live, how they refresh) → `CanvasAuth.md`.
Either credential rides the same REST API, so caller code never branches on school.

## How to call

- Go through the canonical layer: `canvas_token_auth` for the token, `canvas_rest` for
  `get`/`put`/`post`, `fetch_assignment`, `update_assignment`, `get_page`, or the per-task program
  that already wraps it.
- Build the DATA inline, keep the LOGIC canonical. `make_lab(lab, push=True, due_at=…, points=…)`
  sets description, due date and points in one call.
- Add a missing field to the canonical function. Never reach around it with a raw PUT.
- Extract links and embeds with `canvas_core.links.extract_links(html)` — it classifies every link
  and truncates nothing. For a whole page/module/quiz use `canvas_core.canvas_link_extractor`
  (a quiz hides embeds inside its questions).
- Read a module's items with `module_items.list(session, course_id, module_id)`. There is no CLI.

## Writing content

- Create and update with `published: false`. Only the instructor publishes.
- Back up before overwriting a description: GET the current HTML, save it, diff it, and carry over
  every iframe, `slide=id.X`, custom URL, embedded image and instructor note. Assignments have no
  revisions API — `/assignments/{id}/revisions` is 404 and an overwrite is final.
- Re-upload images when moving HTML between courses and repoint `src`. A
  `/courses/{old_id}/files/…` reference 404s in the new course.
- Send announcements through `canvas_core.announcements`. Preview with
  `python3 -m canvas_core.announcements <school> <course_id> <file.html>` — HTTP 400 is the
  tripwire meaning "would send, blocked", not an error. Send on the instructor's go with
  `send_announcement(CanvasSession(school), cid, title=…, message=…, confirm=SEND_CONFIRM)`.

## Formatting

- Style code inline; Canvas strips `<style>` blocks silently.
- Inline code: `<span style="font-family:'Courier New',monospace;font-weight:bold;background-color:#f2f2f2;padding:1px 5px;border-radius:3px;border:1px solid #e0e0e0;">`
- Code block: `<pre style="font-family:'Courier New',monospace;font-weight:bold;background-color:#f2f2f2;padding:10px 12px;border-radius:4px;border:1px solid #e0e0e0;line-height:1.4;overflow-x:auto;">`
- Keep code black on grey. Colour adds nothing the background already gives.
- Paste a Slides iframe URL exactly as stored — it is already `&amp;`-encoded, and re-encoding
  produces `&amp;amp;` and a silently broken query string. Keep `slide=id.X`; without it the deck
  opens on slide 1.
- Verify against the FINAL html: `re.search(r'<iframe[^>]+slide=id\.', html)` matches and
  `'&amp;amp;' in html` is False.

## Calls that return 200 and change nothing

- Send a grade form-encoded: `data={"submission[posted_grade]": …}`. As JSON it returns 200 and
  sets nothing.
- Send announcements, pages and assignments as JSON with `Content-Type: application/json`. A
  URL-encoded body drops fields such as `delayed_post_at`.
- Send the FULL payload on a quiz-question PUT — `question_type`, `points_possible`,
  `question_text`, `answers[]`. A partial payload returns 200 and applies nothing.
- Refresh a quiz after changing its questions: `PUT /quizzes/{qid}` with a no-op body. Until then
  `question_count` and `points_possible` stay cached.
- Order questions with `POST /courses/{cid}/quizzes/{qid}/reorder` (form-encoded
  `order[][id]`/`order[][type]`, 204 on success), after all question writes. `position` in a
  question payload is accepted and ignored — every GET returns `position: null`.
- Set lateness with `submission[late_policy_status]` = `none` or `late`, then send
  `seconds_late_override` in a SEPARATE call. Sent together, the override is ignored. `excused`
  is not a value — Canvas answers 422. (Late tiers and waivers: `GRADING.md`.)

## Finalizing a quiz grade

A quiz score is the sum of its per-question scores; `submission[posted_grade]` leaves the quiz at
`pending_review`, on the To-Do, with `needs_grading_count` above zero.

- GET the quiz submission for its `id` and `attempt`
  (`/courses/{cid}/quizzes/{qid}/submissions?per_page=100`).
- PUT per-question scores to `/courses/{cid}/quizzes/{qid}/submissions/{quiz_submission_id}`,
  form-encoded: `quiz_submissions[][attempt]`, `quiz_submissions[][questions][{qid}][score]`,
  optional `[comment]`. The bare `/quiz_submissions/{id}/questions` route is 404 for grading.
- Take `question_id`s from the assignment submission's `submission_data[]`. Text-only questions
  come back `correct: "no_score"` — skip them.

## Reading submissions

- Identify a student by Canvas `uid`. Names repeat.
- Fetch `<iframe src="…">` content before grading — the work is often inside it.
- Post a comment as HTML through
  `canvas_rest.post_submission_grade(…, comment=comment_render.comment_html(…))`. SpeedGrader
  renders tables, lists and entities.
- Verify comment rendering in the UI. `GET …?include[]=submission_comments` returns a
  text-extracted, flattened copy for EVERY html comment, so a flattened API value proves nothing.
