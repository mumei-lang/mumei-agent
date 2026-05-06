---
name: proliferate
description: Run the autonomous proliferation loop: health baseline, gap analysis, generation, blast-radius checks, and summary health delta.
---

Given a Mumei checkout, autonomously analyze std gaps, generate candidates, validate blast radius, and write a structured summary.

# Step 1: Capture health baseline

Action:
    Run the **health** skill before proliferation.

Expectation:
    Baseline `health_score`, verified files, trusted atoms, TODO markers, and failed files are recorded.

Result:
    Proceed only when the baseline is captured.

```bash
python -m agent health --mumei-repo ../mumei --format json > pre_health.json
```

# Step 2: Run proliferation

Action:
    Invoke `python -m agent proliferate` with a bounded proposal count and output summary JSON.

Expectation:
    The agent analyzes gaps, builds specs, generates verified code, checks blast radius across existing std modules, optionally uses Lean fallback, and records results.

Result:
    `summary.json` captures pre/post health, health delta, processed proposals, and per-proposal details.

```bash
python -m agent proliferate \
  --mumei-repo ../mumei \
  --max-proposals 3 \
  --output-json summary.json
```

Dry-run preview:

```bash
python -m agent proliferate --mumei-repo ../mumei --max-proposals 3 --dry-run --output-json summary.json
```

# Step 3: Confirm summary and health delta

Action:
    Parse `summary.json`, inspect `health_delta`, and re-run **health** when needed.

Expectation:
    Successful proliferation improves or preserves proof health and does not regress existing std verification.

Result:
    Report proposals processed, successes/failures, files changed, and health delta.

```bash
python -m json.tool summary.json
python -m agent health --mumei-repo ../mumei --format json > post_health.json
```

# Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| mumei_repo | path | yes | | Mumei checkout containing `std/` |
| max_proposals | int | no | 3 | Maximum gap proposals to process |
| output_json | path | no | | Structured run summary |
| dry_run | flag | no | off | Analyze/plan without edits |
| enable_lean_fallback | flag | no | off | Try mumei-lean for unknown atoms when configured |
