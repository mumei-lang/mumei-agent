"""Few-shot examples for postcondition fixes."""

EXAMPLES = [
    {
        "before": (
            "atom add_one(x: i64)\n"
            "    requires: x >= 0;\n"
            "    ensures: result > 0;\n"
            "    body: x - 1;"
        ),
        "after": (
            "atom add_one(x: i64)\n"
            "    requires: x >= 0;\n"
            "    ensures: result > 0;\n"
            "    body: x + 1;"
        ),
        "explanation": (
            "The ensures clause requires result > 0, but x - 1 can be negative "
            "when x = 0. Changing to x + 1 guarantees result > 0 for all x >= 0."
        ),
    },
]
