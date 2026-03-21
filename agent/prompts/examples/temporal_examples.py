"""Few-shot examples for temporal effect fixes."""

EXAMPLES = [
    {
        "before": (
            "atom bad_file_usage(x: i64)\n"
            "    requires: x >= 0;\n"
            "    ensures: result >= 0;\n"
            "    effects: [File];\n"
            "    body: {\n"
            "        perform File.write(x);\n"
            "        perform File.open(x);\n"
            "        x\n"
            "    };"
        ),
        "after": (
            "atom valid_file_usage(x: i64)\n"
            "    requires: x >= 0;\n"
            "    ensures: result >= 0;\n"
            "    effects: [File];\n"
            "    body: {\n"
            "        perform File.open(x);\n"
            "        perform File.write(x);\n"
            "        perform File.close(x);\n"
            "        x\n"
            "    };"
        ),
        "explanation": (
            "File effect requires the state machine order: open -> write/read -> close. "
            "Writing before opening violates the Closed -> Open transition."
        ),
    },
]
