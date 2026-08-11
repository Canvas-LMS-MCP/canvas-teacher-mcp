# L2 cpp-stdout TEMPLATE test harness — pytest reads the program's OUTPUT files.
#
# The Run grader executes data/run.sh, which compiles main.cpp and runs it once per input file,
# redirecting stdout to resultN.txt. Each test then reads the resultN.txt it cares about.
# Four marker groups (T1..T4), 20 points each; classroom.yml runs one grader per marker.
#
# RULES (see git-asmt-repo/languages/cpp-stdout.md and L1 §2/§3/§5):
#  - Match VALUES only, in order, as a forward search — never whole lines, never whitespace counts,
#    never a label word the instruction did not require the student to print.
#  - Use MORE THAN ONE input set (data1/data2/...) so a hard-coded print cannot pass.
#  - A group is NOT one test: add as many items per group as the problem needs, so every
#    case the spec implies is exercised. But only test edges the INSTRUCTION states —
#    an unstated case (e.g. negatives when the spec never allows them) is a trap; fix the
#    instruction first, then test it (L1 §3).
#  - The placeholders below FAIL on purpose. A placeholder that passes is a silent hole (L1 GATE A).
import pytest
import re


def regex_test(expected, lines):
    """Each token in `expected` must appear, in order, somewhere in `lines`."""
    i = 0
    match = 0
    for token in expected:
        for j in range(i, len(lines)):
            if re.search(token, lines[j]) is not None:
                i = j + 1
                match += 1
                break
        else:
            print(f'\033[91m Not Found: {token} \033[0m')
            assert False, f'Expect: {expected}'
    assert match == len(expected), f'Expect: {expected}'


def result(n=1):
    with open(f'result{n}.txt', 'r') as f:
        return [line.strip() for line in f.readlines()]


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
