# L2 python-pytest TEMPLATE test harness — pytest imports main and asserts on RETURN values.
# Four marker groups (T1..T4), 20 points each; classroom.yml runs one grader per marker.
#
# RULES (see git-asmt-repo/languages/python-pytest.md and L1 §3/§5):
#  - Assert the RETURN value, not scraped stdout (swallow prints if the function is chatty).
#  - Use MORE THAN ONE input set so a hard-coded answer cannot pass.
#  - Cover the edges the spec implies: empty, single, negatives, duplicates, boundary, largest-N.
#  - A group is NOT one test: add as many items per group as the problem needs, so every
#    case the spec implies is exercised. But only test edges the INSTRUCTION states —
#    an unstated case (e.g. negatives when the spec never allows them) is a trap; fix the
#    instruction first, then test it (L1 §3).
#  - The placeholders below FAIL on purpose. A placeholder that passes is a silent hole (L1 GATE A).
import io
import sys

import pytest

import main


def call_quiet(fn, *args, stdin=None):
    """Call fn with stdout swallowed (and optional stdin injected); return its value."""
    old_out, old_in = sys.stdout, sys.stdin
    sys.stdout = io.StringIO()
    if stdin is not None:
        sys.stdin = io.StringIO(stdin)
    try:
        return fn(*args)
    finally:
        sys.stdout, sys.stdin = old_out, old_in


@pytest.mark.T1
def test_t1():
    pytest.fail('TODO: replace with real T1 checks for this assignment')


@pytest.mark.T2
def test_t2():
    pytest.fail('TODO: replace with real T2 checks for this assignment')


@pytest.mark.T3
def test_t3():
    pytest.fail('TODO: replace with real T3 checks for this assignment')


@pytest.mark.T4
def test_t4():
    pytest.fail('TODO: replace with real T4 checks for this assignment')
