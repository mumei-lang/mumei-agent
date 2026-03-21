"""Few-shot examples for linearity violation fixes."""

EXAMPLES = [
    {
        "before": (
            "atom use_twice(x: linear File)\n"
            "    effects: [File];\n"
            "    requires: true;\n"
            "    ensures: result >= 0;\n"
            "    body: {\n"
            "        perform File.write(x);\n"
            "        perform File.read(x);\n"
            "        0\n"
            "    };"
        ),
        "after": (
            "atom use_twice(x: linear File)\n"
            "    effects: [File];\n"
            "    requires: true;\n"
            "    ensures: result >= 0;\n"
            "    body: {\n"
            "        let x2 = clone(x);\n"
            "        perform File.write(x);\n"
            "        perform File.read(x2);\n"
            "        0\n"
            "    };"
        ),
        "explanation": (
            "The linear resource 'x' is consumed by File.write, so the "
            "subsequent File.read(x) violates linearity. Cloning 'x' before "
            "the first use gives each operation its own copy."
        ),
    },
    {
        "before": (
            "atom send_and_log(conn: linear Connection)\n"
            "    effects: [Network];\n"
            "    requires: true;\n"
            "    ensures: result >= 0;\n"
            "    body: {\n"
            "        perform Network.send(conn);\n"
            "        perform Network.log(conn);\n"
            "        0\n"
            "    };"
        ),
        "after": (
            "atom send_and_log(conn: linear Connection)\n"
            "    effects: [Network];\n"
            "    requires: true;\n"
            "    ensures: result >= 0;\n"
            "    body: {\n"
            "        let result_val = perform Network.send(conn);\n"
            "        perform Network.log(result_val);\n"
            "        0\n"
            "    };"
        ),
        "explanation": (
            "Instead of using 'conn' twice, restructure so the output of "
            "send is passed to log. Each linear value is consumed exactly once."
        ),
    },
]
