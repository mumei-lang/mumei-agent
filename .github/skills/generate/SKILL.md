---
name: generate
description: Generate verified Mumei .mm code from a JSON specification with uv run python -m agent generate --spec-file.
---

Given a forge task spec or atom specification JSON, generate `.mm` code and verify it with Mumei.

# Step 1: Prepare the spec JSON

Action:
    Create or locate a JSON spec file. It must be either a single-atom spec with `name`, or a multi-atom/forge spec with an `atoms` array whose entries include `name`.

Expectation:
    The spec is valid JSON and includes enough contract information for generation.

Result:
    If the spec validates, proceed to Step 2.

```bash
python -m json.tool spec.json >/dev/null
```

# Step 2: Run generation

Action:
    Invoke `uv run python -m agent generate --spec-file`, selecting an output `.mm` file and retry count.

Expectation:
    The agent calls the LLM, runs `mumei check`, runs `mumei verify --json`, and self-heals verification failures up to the retry limit.

Result:
    Output `.mm` is written. The command exits non-zero if verification does not succeed.

```bash
uv run python -m agent generate --spec-file spec.json --output out.mm --metrics
```

# Step 3: Confirm verification

Action:
    Run direct Mumei verification on the generated file and inspect metrics when requested.

Expectation:
    Verification succeeds and the generated code matches the requested spec.

Result:
    Report output path, verified status, and any metrics summary.

```bash
mumei verify out.mm --json
```

# Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| spec_file | path | yes | | JSON spec file |
| output | path | yes | | Generated `.mm` file |
| max_retries | int | no | config default | Maximum self-healing attempts |
| metrics | flag | no | off | Print JSON metrics summary |
