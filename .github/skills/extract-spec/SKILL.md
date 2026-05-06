---
name: extract-spec
description: Extract Mumei forge task specification JSON from natural-language requirements with python -m agent extract-spec.
---

Given natural-language requirements, produce a Mumei forge task spec JSON and optionally generate verified `.mm` code.

# Step 1: Prepare natural-language input

Action:
    Collect requirement text from an inline string or text file. Add a domain hint when available.

Expectation:
    The text states inputs, outputs, safety constraints, and desired postconditions clearly enough to extract a spec.

Result:
    If the text is ready and LLM config exists, proceed to Step 2.

# Step 2: Run extraction

Action:
    Invoke `python -m agent extract-spec --text` or `--text-file`, selecting an output JSON path.

Expectation:
    The agent asks the LLM for a forge task spec and validates the result against Mumei spec expectations.

Result:
    A spec JSON file is written.

```bash
python -m agent extract-spec \
  --text "amount must be non-negative and result preserves balance conservation" \
  --domain financial \
  --output spec.json
```

Generate in the same flow:

```bash
python -m agent extract-spec \
  --text-file requirements.txt \
  --output spec.json \
  --generate \
  --generate-output out.mm
```

# Step 3: Validate spec JSON

Action:
    Run JSON validation and inspect required fields such as `task_id`, `target_file`, `mode`, and `atoms`.

Expectation:
    The extracted spec is valid JSON and suitable for **generate** or **forge**.

Result:
    Report the spec path and route to **generate** if code is requested.

```bash
python -m json.tool spec.json >/dev/null
```

# Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| text | string | no | | Inline natural-language requirements |
| text_file | path | no | | File containing requirements |
| domain | string | no | `general` | `financial`, `regtech`, `security`, `data_structure`, or `general` |
| output | path | yes | | Extracted spec JSON path |
| generate | flag | no | off | Also generate and verify `.mm` code |
| generate_output | path | if `generate` | | Generated `.mm` output path |
