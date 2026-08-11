"""canvas_rest.timefmt — display Canvas times in a configurable local timezone, never raw UTC.

Canvas stores/returns `due_at` etc. in UTC (e.g. "2026-06-22T06:59:00Z"). Showing that raw is the
recurring date bug. `to_localtime` converts to a target timezone (DST + the label like PDT/EST handled
automatically by ZoneInfo). Pure function, no HTTP.

The timezone is NOT hardcoded — for the MCP / other users it must be configurable:
  - default = env `CANVAS_TZ` if set, else `America/Los_Angeles` (our courses are California / CCC),
  - override at runtime with `set_timezone("America/New_York")`,
  - or per call: `to_localtime(utc, tz="...")`.
"""
import os
from datetime import datetime
from zoneinfo import ZoneInfo

_DEFAULT_TZ = "America/Los_Angeles"
_TZ = os.environ.get("CANVAS_TZ") or _DEFAULT_TZ   # process-wide default (env-configurable)

_FMT = "%a %b %-d, %Y, %-I:%M %p %Z"


def set_timezone(tz):
    """Set the process-wide display timezone (IANA name, e.g. 'America/New_York')."""
    global _TZ
    _TZ = tz


def get_timezone():
    """The current process-wide display timezone (IANA name)."""
    return _TZ


def to_localtime(utc_iso, tz=None, fmt=_FMT):
    """ISO-8601 UTC string (e.g. '2026-06-22T06:59:00Z') -> local display string in `tz`
    (or the configured default / `CANVAS_TZ`), e.g. 'Sun Jun 21, 2026, 11:59 PM PDT'.
    Returns '' for None/empty/unparseable.

    The label (PDT/PST/EST/...) and offset are derived from the date via ZoneInfo, so DST is
    correct year-round — never a hardcoded offset.
    """
    if not utc_iso:
        return ""
    s = utc_iso.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(ZoneInfo(tz or _TZ)).strftime(fmt)


def to_pacific(utc_iso, fmt=_FMT):
    """DEPRECATED — use `to_localtime`. Pacific-pinned alias kept for back-compat."""
    return to_localtime(utc_iso, tz="America/Los_Angeles", fmt=fmt)


def to_utc(local_iso, tz=None):
    """INVERSE of to_localtime: a local wall-clock string in `tz` (default configured / `CANVAS_TZ`,
    i.e. Pacific) -> UTC ISO-8601 'Z' string for the Canvas API (`due_at`, `unlock_at`, …). This is
    how you SET a Canvas date — never hand-compute the UTC offset (DST makes that wrong half the year).
    Accepts 'YYYY-MM-DD HH:MM', 'YYYY-MM-DD HH:MM:SS', or the ISO 'T' form. '' for empty/unparseable.
    e.g. to_utc('2026-07-12 23:59') -> '2026-07-13T06:59:00Z' (PDT, UTC-7)."""
    if not local_iso:
        return ""
    s = local_iso.strip().replace("T", " ")
    dt = None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(s, fmt)
            break
        except ValueError:
            dt = None
    if dt is None:
        return ""
    dt = dt.replace(tzinfo=ZoneInfo(tz or _TZ))
    return dt.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")
