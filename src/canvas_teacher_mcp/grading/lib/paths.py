"""Portable path notation for anything this engine WRITES TO DISK.

WHY. The tree can be one synced folder mounted on more than one machine, each with its own
home directory. Every record this engine writes stores `os.path.realpath()` output, so each
file carries the home of whichever machine happened to run it. Read back on the other machine
those paths name a home that does not exist. A grade record written on one machine held an
absolute `view_manifest` path; the render took it, could not open it, printed one SKIPPED line
and reported success on a record with no proof.

THE NOTATION IS `~`, NOT `$HOME`. `$HOME` is expanded by a shell; Python is not a shell, so
`open("$HOME/x")` simply fails and every read site would have to remember `expandvars` —
one miss breaks silently. `~` has a standard expander (`os.path.expanduser`) and survives a
JSON round-trip unchanged.

TWO BOUNDARIES, AND ONLY TWO:

    fold(p)      real path  ->  stored value.   Call immediately before serializing.
    resolve(p)   stored value -> real path.     Call immediately before touching the file.

Comparisons stay FOLDED — two machines then produce the same string for the same file.
File access is the only place that unfolds, because the kernel needs a real path.

`resolve` also ABSORBS a foreign home: a stored `/Users/<someone>/rest` that does not exist
is retried as `~/rest`. That is what makes the ~150 already-written records on disk work
without rewriting any of them (the instructor's decision: fix the code, not the data). It
never guesses a file into existence — when nothing resolves it hands back the original, so
the caller's `os.path.exists` still fails and the gate still refuses.
"""
import os
import re

_FOREIGN_HOME = re.compile(r"^/Users/[^/]+/(.*)$")


def resolve(p):
    """Stored value -> a real path on THIS machine. Call before open/exists/isfile.

    1. expand `~`
    2. if that exists, done
    3. otherwise treat it as another machine's home and re-root it under ours
    4. if that does not exist either, return the expanded original — the caller's
       existence check must be the one to fail, never a path invented here.
    """
    if not p:
        return p
    q = os.path.expanduser(p)
    if os.path.exists(q):
        return q
    m = _FOREIGN_HOME.match(q)
    if m:
        cand = os.path.join(os.path.expanduser("~"), m.group(1))
        if os.path.exists(cand):
            return cand
    return q


def fold(p):
    """Real path -> stored value with the home written as `~`. Call before serializing.

    IDEMPOTENT: `resolve` runs first, so folding an already-folded value is a no-op
    instead of the corruption `realpath("~/x")` would produce (it treats `~` as a
    relative directory name and glues the cwd in front of it).

    `realpath` is kept — it collapses symlinks, `..`, `//` and `/./` so that two spellings
    of one file compare equal. Dropping it to "just fold the string" would break the
    view-gate, whose whole job is matching a manifest path against a transcript path.
    """
    if not p:
        return p
    rp = os.path.realpath(resolve(p))
    home = os.path.expanduser("~")
    if rp == home:
        return "~"
    if rp.startswith(home + os.sep):
        return "~" + rp[len(home):]
    return rp                      # outside the home (/tmp, /Volumes) — stays absolute
