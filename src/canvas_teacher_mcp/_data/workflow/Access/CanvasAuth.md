# CanvasAuth

How Canvas credentials are stored, chosen and refreshed. Calling Canvas → `Canvas.md`.

**Terms.** chrome-user-profile = the FOLDER Chrome keeps login state in. session = the
auth cookie exported OUT of that folder. They are different things.

## Where

- Put a token in `.claude/Canvas-Auth/<school>.json` — `{base_url, token, courses}`, flat `token`
  key, nothing nested.
- Put the Chrome profile (saved SSO password) in
  `.claude/Canvas-Auth/storageState/<school>/login-credential/`.
- Put the exported session cookie in `.claude/Canvas-Auth/storageState/<school>/cookies.json`.
  The Canvas auth cookie is session-scoped, so the profile drops it on close.
- Put the per-school SSO knobs in `.claude/Canvas-Auth/institutions.yaml` — domain, `sso_base`,
  the form selectors, `login_domain_for_check`. It is DATA, so it sits with the other per-school
  data and never ships inside the code.
- Keep one folder per school. Shared cookies produce the wrong `_csrf_token` and Canvas answers 422.
- Keep it per school, not per course. One Canvas server is one session, so one login serves every
  course on it.
- A school has whichever of these it needs. Do not expect both.

## Which credential

- Use the token when the school has one, the cookie otherwise. This is DERIVED from token presence —
  never write a per-school table.
- Resolve a token in order: `$<SCHOOL>_CANVAS_TOKEN`, then `Canvas-Auth/*.json`.
- Resolve cookies with `canvas_auth.session.read_profile_cookies(school, domain)`.
- Let `CanvasSession(school)` make the choice. Never hand-build an `Authorization` or `Cookie` header.

## Refresh

- Call `canvas_auth.login.login(school)` — the one routine, idempotent. Session alive ⇒ save state.
  Session dead ⇒ drop the stale session cookies, load a clean login page, let Chrome autofill, submit,
  export `cookies.json`.
- Let it happen by itself: `CanvasSession` calls `login()` once on any 401. There is no heartbeat.
- For unattended autofill, hold all three: biometric filling OFF during the login (`login()` restores
  the pref afterwards), a clean login page before the first `goto`, and no programmatic typing of the
  username — Chrome fills both fields or neither.
- Add a school by hand-editing `Canvas-Auth/institutions.yaml`. There is no auto-recon writer.
- Log in manually once per machine, accepting Chrome's "Save password" and "remember this device".
  Zero-touch from then on.

## Handling

- `chmod 600` every auth file. Re-apply after a sync to a new device.
- Keep `Canvas-Auth/` out of git. One in a history is a leak: revoke, re-login, rotate.
- Drive one school from one machine at a time. Concurrent writes lose a rotated token.
- Keep Canvas auth here and nowhere else. GitHub lives in the `gh` keyring, Google in `~/.config`.
