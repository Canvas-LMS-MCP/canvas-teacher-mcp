"""Grader REGISTRY — the one place a grader name becomes a module.

WHY (2026-07-28). Nothing resolved grader names: `core.py` imported all five and held the
name→module table itself, and `graders/quiz.py` did `from . import gh as gh_grader` — a tier
reaching directly for a specific peer. That import is what made "the bottom tier is shared"
a claim rather than a fact: a quiz question could only ever be graded by `gh`, so a notebook
or flowchart question had nowhere to go, while quiz.py's own docstring advertised type
dispatch. One registry, used by every tier, is what makes the 3-tier assembly real:

    tier 0 core.py ─ get(designated_type)          → LEAF or COMPOSITE
    tier 1 quiz.py ─ get(type_of_this_question)    → the SAME modules core.py uses

WHAT EARNS A SLOT. A grader exists only to read a MACHINE artifact a human would otherwise
run by hand — an autograder run + commit history (gh), notebook execution (nb), a JShell
transcript (jshell) — or to iterate sub-units (quiz). Everything else is `general`, which
gathers the materials and lets AI Stage B score them against the assignment's own rubric.
`ad` (Algorithm Development) and `w5` (Workshop) failed that test and were deleted the same
day: a rubric hardcoded as percentages plus scoring by proxy (`ad` scored the FLOWCHART item
off a `has_visual` boolean — points for a drawing nobody opened).

REGISTRATION IS NOT LAZY, ON PURPOSE. Every module is imported at import time so a broken
grader fails at startup with its own name attached, not mid-run on some student's submission.
"""
from ..lib import contract
from . import general, gh, jshell, nb, quiz

# name → module. The ONLY table; no tier keeps a private one.
_REGISTRY = {
    "general": general,   # universal floor — no machine artifact, AI Stage B scores
    "gh": gh,             # GitHub autograder run + commit history
    "nb": nb,             # Colab/Jupyter execution + revision history
    "jshell": jshell,     # JShell transcript
    "quiz": quiz,         # COMPOSITE — iterates attempt × question, scores nothing itself
}

# The floor. Never a fallback for a FAILED type — only for an UNDESIGNATED one. A grader that
# was designated and then could not find its data must say so, not quietly become general.
FLOOR = "general"


class UnknownGrader(KeyError):
    """A name with no module. Lists what exists — never resolves to a default."""


def names():
    """Registered grader names, sorted."""
    return sorted(_REGISTRY)


def get(name):
    """name → module. Raises UnknownGrader on an unknown name — no silent default.

    A typo'd `--grader` must stop the run, not slide into `general` and produce a plausible
    report under the wrong grader. Use `get(FLOOR)` where the floor is genuinely intended.
    """
    try:
        return _REGISTRY[name]
    except KeyError:
        raise UnknownGrader(
            f"unknown grader {name!r} — registered: {', '.join(names())}") from None


def declares(name):
    """The grader's PRODUCES set, or contract.UNDECLARED. See lib/contract.py."""
    return contract.produces(get(name))
