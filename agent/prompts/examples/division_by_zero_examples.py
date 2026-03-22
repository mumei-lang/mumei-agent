"""Few-shot examples for division-by-zero fixes."""

EXAMPLES = [
    {
        "before": (
            "atom safe_divide(a: i64, b: i64) -> i64\n"
            "    requires: true;\n"
            "    ensures: result == a / b;\n"
            "    body: a / b;"
        ),
        "after": (
            "atom safe_divide(a: i64, b: i64) -> i64\n"
            "    requires: b != 0;\n"
            "    ensures: result == a / b;\n"
            "    body: a / b;"
        ),
        "explanation": (
            "The divisor 'b' can be zero when requires is 'true'. "
            "Adding 'requires: b != 0' prevents division by zero."
        ),
    },
    {
        "before": (
            "atom average(total: i64, count: i64) -> i64\n"
            "    requires: total >= 0;\n"
            "    ensures: result >= 0;\n"
            "    body: total / count;"
        ),
        "after": (
            "atom average(total: i64, count: i64) -> i64\n"
            "    requires: total >= 0 && count > 0;\n"
            "    ensures: result >= 0;\n"
            "    body: total / count;"
        ),
        "explanation": (
            "The divisor 'count' can be zero. Adding 'count > 0' to the "
            "requires clause prevents division by zero while keeping the "
            "existing constraint on 'total'."
        ),
    },
]
