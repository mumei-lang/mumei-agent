"""Few-shot examples for path safety fixes."""

EXAMPLES = [
    {
        "before": (
            "atom read_user_file(user_id: Str)\n"
            "    effects: [SafeFileRead(path)]\n"
            "    requires: true;\n"
            "    ensures: result >= 0;\n"
            "    body: {\n"
            "        let path = \"/tmp/\" + user_id + \"/data.txt\";\n"
            "        perform SafeFileRead.read(path);\n"
            "        1\n"
            "    }"
        ),
        "after": (
            "atom read_user_file(user_id: Str)\n"
            "    effects: [SafeFileRead(path)]\n"
            "    requires: not_contains(user_id, \"..\") && not_contains(user_id, \"\\0\");\n"
            "    ensures: result >= 0;\n"
            "    body: {\n"
            "        let path = \"/tmp/\" + user_id + \"/data.txt\";\n"
            "        perform SafeFileRead.read(path);\n"
            "        1\n"
            "    }"
        ),
        "explanation": (
            "Without constraints on user_id, a directory traversal attack is possible "
            "(e.g. user_id = '../../etc'). Adding not_contains(user_id, '..') prevents this."
        ),
    },
]
