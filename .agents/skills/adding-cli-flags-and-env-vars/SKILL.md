---
name: adding-cli-flags-and-env-vars
description: "Use when adding, renaming, or removing a CLI flag, subcommand option, or environment variable"
---

# Adding CLI flags and environment variables

1. Read `docs/NAMING.md` and choose a name that follows its rules. Do not rename an existing name in place; add an alias and a deprecation note.
2. Add the CLI flag to the owning argparse parser. Keep its help text and parser defaults accurate.
3. Add each environment variable to `agent/env_reference.py` with its category, default, description, and `sensitive` classification.
4. Regenerate the committed CLI and environment references:
   ```sh
   PYTHONPATH=$PWD .venv/bin/python scripts/gen_reference_docs.py
   ```
5. Run the naming, reference, and config tests:
   ```sh
   PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_naming.py tests/test_reference_docs.py tests/test_config_report.py -q
   ```
6. Check `PYTHONPATH=$PWD .venv/bin/python -m agent config --all` to confirm the variable is reported correctly. For a sensitive variable, use a fake sentinel and confirm its value is absent from both text output and `PYTHONPATH=$PWD .venv/bin/python -m agent config --json`.

## PR checklist

- [ ] The new name follows `docs/NAMING.md`; an existing name remains available through an alias and deprecation note.
- [ ] Environment metadata includes category, default, description, and an explicit sensitive-value decision.
- [ ] CLI and environment references are regenerated and the naming, reference, and config tests pass.
- [ ] `config` output reports the setting correctly without printing any sensitive sentinel.
