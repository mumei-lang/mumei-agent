"""Few-shot examples for precondition fixes."""

EXAMPLES = [
    {
        "before": (
            "atom safe_divide(a: i64, b: i64)\n"
            "    requires: true;\n"
            "    ensures: result == a / b;\n"
            "    body: a / b;"
        ),
        "after": (
            "atom safe_divide(a: i64, b: i64)\n"
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
            "atom check_age(age: i64)\n"
            "    requires: true;\n"
            "    ensures: result >= 0;\n"
            "    body: age;"
        ),
        "after": (
            "atom check_age(age: i64)\n"
            "    requires: age >= 0 && age <= 120;\n"
            "    ensures: result >= 0;\n"
            "    body: age;"
        ),
        "explanation": (
            "The ensures clause requires result >= 0 but age can be negative. "
            "Adding a range constraint ensures the postcondition is met."
        ),
    },
]
