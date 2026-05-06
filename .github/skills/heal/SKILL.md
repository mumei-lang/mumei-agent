---
name: heal
description: Run the mumei-agent self-healing loop on failing .mm source using mumei verify JSON feedback and LLM repair attempts.
---

Given a `.mm` source file and optional verifier error report, repair it through the self-healing loop until Mumei verification succeeds or retry limits are exhausted.

# Step 1: Prepare source and error report

Action:
    Locate the `.mm` source file. If an error report is provided, keep it alongside the source; otherwise the agent will run `mumei verify --json`.

Expectation:
    The file exists, is safe to modify, and the environment has `LLM_API_KEY` or `OPENAI_API_KEY` for non-dry-run repair.

Result:
    If inputs and LLM config are ready, proceed to Step 2.

# Step 2: Run the self-healing loop

Action:
    Invoke `python -m agent heal`, optionally selecting retry count and strategy.

Expectation:
    The loop backs up the original file, runs Mumei verification, asks the LLM for a repair using structured feedback, writes the candidate, and re-verifies.

Result:
    The command exits successfully when the repaired file verifies.

```bash
python -m agent heal input.mm --max-retries 3
python -m agent heal input.mm --strategy multi-stage
```

MCP equivalent:

```text
heal_file(source_code, error_report)
```

# Step 3: Confirm repair

Action:
    Re-run Mumei verification directly and inspect the diff.

Expectation:
    `mumei verify --json` reports success. The patch is minimal and preserves intended contracts.

Result:
    Report the fix, backup path, and verification evidence.

```bash
mumei verify input.mm --json
```

# Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| source_file | path | no | `examples/sword_test.mm` | `.mm` file to repair |
| error_report | JSON/string | no | | Existing verification report |
| max_retries | int | no | config default | Maximum repair attempts |
| strategy | string | no | `AGENT_STRATEGY`/`single` | `single` or `multi-stage` |
