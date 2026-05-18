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

# Live E2E testing

Use this section when verifying the real LLM-backed extraction path rather than mocks.

## Devin Secrets Needed

- `OPENAI_API_KEY`: OpenAI API key used by the live integration tests and CLI extraction flow.

## Step 1: Run focused local tests

Action:
    Run the focused P11-adjacent local suite before relying on live LLM behavior.

```bash
python -m pytest tests/test_spec_extractor.py tests/test_extract_spec_to_forge.py tests/test_mcp_server.py -v
```

Expectation:
    The suite passes locally. These tests do not prove live LLM extraction, but they verify validator, CLI, and MCP behavior around extraction.

## Step 2: Run live integration tests

Action:
    Run the live extraction E2E tests with both the integration marker and the repository opt-in flag.

```bash
python -m pytest tests/test_spec_extractor_e2e.py -m integration --run-integration -v
```

Expectation:
    Tests should execute rather than skip. If `--run-integration` is omitted, `tests/conftest.py` skips integration tests even when `OPENAI_API_KEY` is present.

## Step 3: Run manual CLI smoke extraction

Action:
    Exercise the public CLI with a representative domain hint and validate the output.

```bash
python -m agent extract-spec \
  --text "安全な銀行送金機能。送金額は正の整数のみ。残高不足は拒否し、送金後の送金元残高と受取人残高の合計は保存される。" \
  --domain financial \
  --output /home/ubuntu/p11_live_cli_financial_spec.json
```

Expectation:
    The command exits 0, writes JSON, and extraction metrics show at least one success. Validate that `target_file` is a safe `std/**/*.mm` path, atoms are present, schema validation returns no errors, and domain-relevant safety constraints are represented.

# Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| text | string | no | | Inline natural-language requirements |
| text_file | path | no | | File containing requirements |
| domain | string | no | `general` | `financial`, `regtech`, `security`, `data_structure`, or `general` |
| output | path | yes | | Extracted spec JSON path |
| generate | flag | no | off | Also generate and verify `.mm` code |
| generate_output | path | if `generate` | | Generated `.mm` output path |
