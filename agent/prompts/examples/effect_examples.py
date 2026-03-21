"""Few-shot examples for effect mismatch and propagation fixes."""

EXAMPLES = [
    {
        "before": (
            "atom write_and_log(msg: i64)\n"
            "    effects: [Log];\n"
            "    requires: msg >= 0;\n"
            "    ensures: result == msg;\n"
            "    body: {\n"
            "        perform Log.info(msg);\n"
            "        perform FileWrite.write(msg);\n"
            "        msg\n"
            "    };"
        ),
        "after": (
            "atom write_and_log(msg: i64)\n"
            "    effects: [Log, FileWrite];\n"
            "    requires: msg >= 0;\n"
            "    ensures: result == msg;\n"
            "    body: {\n"
            "        perform Log.info(msg);\n"
            "        perform FileWrite.write(msg);\n"
            "        msg\n"
            "    };"
        ),
        "explanation": (
            "The body uses FileWrite.write but only [Log] is declared. "
            "Adding FileWrite to the effects list resolves the mismatch."
        ),
    },
]
