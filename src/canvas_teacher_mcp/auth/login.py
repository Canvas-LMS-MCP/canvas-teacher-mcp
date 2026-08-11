"""canvas_auth.login — create/refresh the Canvas session via Playwright (auto-login).

Port of canvas_via_playwright/canvas_relogin.js → playwright-python (NO node). HEADED, because
Chrome autofill needs a visible window; every other module (data, rollcall) stays headless.

Idempotent single routine (no "first time?" branch, no asking):
  - session already alive   → save storageState, done
  - session dead (bounced)  → drop STALE Canvas session cookies (keep remember-device) so we hit a
    CLEAN login page → Chrome autofills (do NOT type — typing suppresses autofill) → submit → wait
    for Canvas landing → save. (A clean login page is what makes Chrome autofill fire reliably; a
    stale session cookie blocks it — verified 2026-07-01.)
  - autofill genuinely never fires → raise NeedsLogin. Operator does the one-time manual login
    (log in + accept "Save password" + check "remember this device") and re-runs login().

Paths are config-injectable; defaults are operational (Claude Code). For the MCP, pass
profile_dir = platformdirs.user_data_dir("canvas-lms")/"profiles"/school. Cookies persist in
that folder (no json export). Stdlib + playwright only; institutions.yaml parsed without PyYAML.
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from .session import canvas_profile_dir, cookies_json_path

# Per-school SSO knobs — DATA, so it sits with the other per-school data (tokens, cookie
# profiles) under Canvas-Auth, not in the code. Adding a cookie school = adding an entry here.
def _institutions_path():
    from ..canvas_root import auth_dir
    return auth_dir() / "institutions.yaml"

AUTOFILL_WAIT_S = 3      # settle time after navigation before checking session state
PASSWORD_BOX_WAIT_S = 15 # wait for EITHER the login box OR an SSO auto-signin landing on Canvas
AUTOFILL_POLL_S = 15     # poll the password field until Chrome autofill fires (on a clean login page)
SUBMIT_WAIT_S = 90       # after autofill+Enter, wait to land back on Canvas (machine-fast)
MANUAL_LOGIN_BUDGET_S = 180   # autofill didn't fire → keep the window open for a human to log in

# Canvas session cookies dropped before relogin so we hit a CLEAN login page (keep remember-device).
SESSION_COOKIES = ("canvas_session", "log_session_id", "_csrf_token")


class NeedsLogin(Exception):
    """No saved credential / autofill didn't fire → a human must log in once.

    The operator catches this, guides the user (log in + Save password + remember device),
    then re-runs login(). Never block/poll waiting for the human inside the code.
    """


def _load_institutions(path: Path | None = None) -> dict:
    """Minimal parser for institutions.yaml (flat `- id:` blocks) — avoids a PyYAML dep."""
    path = path or _institutions_path()
    insts: dict = {}
    cur = None
    for line in Path(path).read_text().splitlines():
        s = line.strip()
        if s.startswith("- id:"):
            cur = {"id": s.split(":", 1)[1].strip()}
            insts[cur["id"]] = cur
        elif cur and ":" in s and not s.startswith(("#", "-")):
            key, val = s.split(":", 1)
            cur[key.strip()] = val.strip().strip("'\"")
    return insts


def _on_site(url: str, domain: str, sso_base: str) -> bool:
    return (url.startswith(f"https://{domain}")
            and sso_base not in url
            and not any(x in url for x in ("/login", "/sso", "/auth")))


def has_saved_password(school: str, profile_dir: Path | None = None) -> bool:
    """True if the Chrome profile already stores the school's SSO password (autofill ready)."""
    k = _load_institutions().get(school, {})
    dom = k.get("login_domain_for_check") or k.get("sso_base", "")
    ld = Path(profile_dir or canvas_profile_dir(school)) / "Default" / "Login Data"
    if not ld.exists() or not dom:
        return False
    try:
        out = subprocess.run(
            ["sqlite3", str(ld), f"SELECT origin_url FROM logins WHERE origin_url LIKE '%{dom}%' LIMIT 1"],
            capture_output=True, text=True,
        ).stdout
        return bool(out.strip())
    except Exception:
        return False


# --- biometric autofill toggle -------------------------------------------------
# macOS Chrome requires Touch ID to autofill a password unless this profile pref is off. An
# unattended login can't press the sensor, so login() turns it OFF for the duration and RESTORES
# the user's original value after Chrome closes (leave the profile exactly as we found it). The
# file edit only holds while Chrome is NOT running (a live Chrome locks/rewrites Preferences).

def _prefs_path(profile_dir) -> Path:
    return Path(profile_dir) / "Default" / "Preferences"


def _get_biometric(prefs: Path):
    """Current biometric_authentication_filling value (True/False), or None if file/key absent."""
    if not prefs.exists():
        return None
    try:
        return json.loads(prefs.read_text()).get("password_manager", {}).get(
            "biometric_authentication_filling")
    except Exception:
        return None


def _set_biometric(prefs: Path, value) -> None:
    """Set biometric_authentication_filling to value (True/False), or remove the key if value is None.
    No-op if the Preferences file is missing. Chrome must be closed or the change is clobbered."""
    if not prefs.exists():
        return
    try:
        d = json.loads(prefs.read_text())
        pm = d.setdefault("password_manager", {})
        if value is None:
            pm.pop("biometric_authentication_filling", None)
        else:
            pm["biometric_authentication_filling"] = value
        prefs.write_text(json.dumps(d, separators=(",", ":")))
    except Exception:
        pass


def login(school: str, *, profile_dir=None, headless: bool = False) -> dict:
    """Refresh/create the Canvas session in the per-school Chrome profile; returns a status dict.

    Cookies persist in the profile folder automatically — NO storageState json export
    (see CourseGlobalWorkflow/Access/CanvasAuth.md REDESIGN).
    Raises NeedsLogin if a one-time manual login is required (operator handles + re-runs).
    """
    k = _load_institutions().get(school)
    if not k:
        raise RuntimeError(f"no institutions.yaml entry for school {school!r}")
    domain, sso = k["domain"], k["sso_base"]
    profile_dir = Path(profile_dir or canvas_profile_dir(school))
    profile_dir.mkdir(parents=True, exist_ok=True)

    from playwright.sync_api import sync_playwright

    # Unattended autofill can't press Touch ID, so turn biometric-fill OFF for this login and RESTORE
    # the user's original value after Chrome closes (leave the profile setting exactly as we found it).
    prefs = _prefs_path(profile_dir)
    orig_biometric = _get_biometric(prefs)   # save original (insurance) BEFORE changing
    _set_biometric(prefs, False)             # OFF — Chrome not launched yet
    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                str(profile_dir), headless=headless, channel="chrome", no_viewport=True,
                args=["--disable-blink-features=AutomationControlled"],
                ignore_default_args=["--enable-automation"],
            )
            try:
                pg = ctx.pages[0] if ctx.pages else ctx.new_page()

                # 1) ALIVE-CHECK FIRST (pure HTTP on the profile session — no navigation, no autofill).
                #    If the session is still valid, use it as-is: do NOT clear cookies, do NOT autofill.
                #    (Clearing a live session just to autofill = the flaky path; skip it when unneeded.)
                probe = ctx.request.get(f"https://{domain}/api/v1/users/self")

                if not probe.ok:
                    # 2) DEAD → CLEAN login page (drop stale session cookies) → let Chrome autofill
                    #    (do NOT type the username — typing suppresses autofill). Keep remember-device.
                    keep = [c for c in ctx.cookies() if c["name"] not in SESSION_COOKIES]
                    ctx.clear_cookies()
                    ctx.add_cookies(keep)
                    pg.goto(f"https://{domain}/", wait_until="domcontentloaded", timeout=60000)
                    pg.wait_for_timeout(AUTOFILL_WAIT_S * 1000)

                    if not _on_site(pg.url, domain, sso):
                        # The login form can sit among MANY hidden password inputs — one real portal
                        # carries 42 (set-password, security-question forms).
                        # Target the FIRST VISIBLE password field = the actual login box, so a generic
                        # selector doesn't hit strict-mode (42 matches) and we read/submit the right box.
                        pw = pg.locator('input[type="password"]:visible').first
                        # A live remember-device SSO re-authenticates on its own and lands back on
                        # Canvas without ever showing a login box. Race the two outcomes — waiting only
                        # for the box hangs forever exactly when the credential is still good.
                        deadline = time.monotonic() + PASSWORD_BOX_WAIT_S
                        while (time.monotonic() < deadline
                               and not _on_site(pg.url, domain, sso)
                               and not pw.is_visible()):
                            pg.wait_for_timeout(500)

                    if not _on_site(pg.url, domain, sso):
                        pval = ""
                        deadline = time.monotonic() + AUTOFILL_POLL_S
                        while time.monotonic() < deadline:
                            pval = (pw.input_value() or "") if pw.is_visible() else ""
                            if pval:
                                break
                            pg.wait_for_timeout(500)
                        if pval:
                            # autofill fired → submit, machine-fast budget
                            pw.press("Enter")
                            budget = SUBMIT_WAIT_S
                        else:
                            # 3) autofill did NOT fire → MANUAL fallback: keep the window open and let a
                            #    human log in (headed). Patient budget; this is NOT a failure.
                            print(f">>> {school}: autofill did not fire — LOG IN MANUALLY in the Chrome "
                                  f"window now (up to {MANUAL_LOGIN_BUDGET_S}s).")
                            budget = MANUAL_LOGIN_BUDGET_S
                        deadline = time.monotonic() + budget
                        while time.monotonic() < deadline:
                            pg.wait_for_timeout(1000)
                            if _on_site(pg.url, domain, sso):
                                break
                        if not _on_site(pg.url, domain, sso):
                            raise NeedsLogin(f"{school}: did not reach Canvas (at {pg.url[:80]})")

                # verify + EXPORT storageState. The Canvas auth cookie is session-scoped and the profile
                # folder DROPS it on close, so dump it to cookies.json (readers load THIS).
                r = ctx.request.get(f"https://{domain}/api/v1/users/self")
                ok = r.ok
                name = (r.json().get("name") if ok else None)
                if ok:
                    cj = cookies_json_path(school)
                    cj.parent.mkdir(parents=True, exist_ok=True)
                    ctx.storage_state(path=str(cj))
            finally:
                ctx.close()
    finally:
        _set_biometric(prefs, orig_biometric)   # restore original (Chrome now closed)

    return {
        "profile": str(profile_dir),
        "verified": bool(ok),
        "name": name,
        "password_saved": has_saved_password(school, profile_dir),
    }
