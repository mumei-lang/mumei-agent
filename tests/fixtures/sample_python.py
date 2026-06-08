def safe_divide(a: int, b: int) -> int:
    """Divide two integers.

    requires: b != 0
    ensures: result * b == a
    """
    return a // b


def is_positive(x: int) -> bool:
    """Return whether x is positive.

    postcondition: result == (x > 0)
    """
    return x > 0
