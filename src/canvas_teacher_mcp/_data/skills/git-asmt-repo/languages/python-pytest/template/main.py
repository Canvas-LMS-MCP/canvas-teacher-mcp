# L2 python-pytest TEMPLATE — the graded unit is a FUNCTION's RETURN value (pytest imports this
# module and calls it). Per assignment: replace the function(s) below.
#
# Starter rule (L1 Part C): keep the signatures and the docstring/TODO, strip the body.
# Everything between the BEGIN/END SOLUTION markers is what gets stripped for the Starter.


def twice(n):
    """Return n doubled."""
    # === BEGIN SOLUTION ===
    return n * 2
    # === END SOLUTION ===


def main():
    # A program-style assignment RETURNS its result from main() so the test can assert on it.
    print("twice(21) =", twice(21))
    return twice(21)


if __name__ == '__main__':
    main()
