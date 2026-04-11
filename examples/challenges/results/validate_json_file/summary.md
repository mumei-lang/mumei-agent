# validate_json_file -- Zero-Human Challenge Result

- **Status**: PENDING (dry-run validated, awaiting full execution)
- **Difficulty**: High
- **Type**: Single-atom with effects
- **Verification Target**: FFI + capability security combination

## Description

Verified JSON file validator with capability security. Uses `SafeFileRead` effect to read files only from `/tmp/` with path traversal prevention. This challenge combines FFI interaction with the effect system to demonstrate compile-time security enforcement.

## Spec

```json
{
  "name": "validate_json_file",
  "params": [{"name": "path", "type": "Str"}],
  "effects": ["SafeFileRead(path)"],
  "requires": "starts_with(path, \"/tmp/\") && not_contains(path, \"..\")",
  "ensures": "result >= 0 && result <= 1"
}
```

## Expected Verification

- Z3 enforces `starts_with(path, "/tmp/")` at all call sites
- Path traversal prevention: `not_contains(path, "..")` prevents directory escape
- Effect tracking: `SafeFileRead(path)` is declared and verified by the effect system
- Boolean return: result is always 0 (invalid) or 1 (valid)

## Challenges for AI Generation

- Must correctly declare and use the `SafeFileRead` effect
- Must understand FFI boundary between mumei and external JSON parsing
- Must satisfy both the capability constraint and the functional postcondition
- Effect mismatch is the most common failure mode for this spec

## How to Execute

```bash
# Full execution (requires OPENAI_API_KEY)
python -m examples.challenges.run_challenge examples/challenges/verified_json_validator_spec.json

# Or via GitHub Actions
# Go to Actions > Zero-Human Challenge > Run workflow
```
