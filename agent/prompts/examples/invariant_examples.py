"""Few-shot examples for invariant violation fixes."""

EXAMPLES = [
    {
        "before": (
            "atom check_range(x: i64) -> i64\n"
            "    requires: x > 10 && x < 5;\n"
            "    ensures: result == x;\n"
            "    body: x;"
        ),
        "after": (
            "atom check_range(x: i64) -> i64\n"
            "    requires: x > 5 && x < 10;\n"
            "    ensures: result == x;\n"
            "    body: x;"
        ),
        "explanation": (
            "The original requires 'x > 10 && x < 5' is unsatisfiable — "
            "no value of x can be both greater than 10 and less than 5. "
            "Swapping to 'x > 5 && x < 10' creates a valid range."
        ),
    },
    {
        "before": (
            "atom bounded_increment(x: i64) -> i64\n"
            "    requires: x >= 0 && x <= 100;\n"
            "    ensures: result >= 0 && result <= 100;\n"
            "    body: x + 1;"
        ),
        "after": (
            "atom bounded_increment(x: i64) -> i64\n"
            "    requires: x >= 0 && x < 100;\n"
            "    ensures: result >= 0 && result <= 100;\n"
            "    body: x + 1;"
        ),
        "explanation": (
            "When x = 100, x + 1 = 101 which violates ensures result <= 100. "
            "Tightening requires to 'x < 100' ensures the postcondition holds."
        ),
    },
]
