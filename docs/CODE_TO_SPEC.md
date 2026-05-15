# Code-to-Spec Extraction

`agent.code_to_spec` connects existing Rust/C/Go/Python/etc. source code to the
existing `extract_spec` pipeline:

1. Detect the source language from the file extension or simple code patterns.
2. Ask the configured OpenAI-compatible LLM for a natural-language behavioral spec.
3. Pass that natural-language spec to `agent.spec_extractor.extract_spec`.
4. Return the resulting forge task spec, detected language, warnings, and errors.

This avoids per-language transpilers. The LLM extracts intent, preconditions,
postconditions, side effects, and safety properties; the existing Mumei spec
pipeline then turns that description into a forge task JSON spec.

## CLI

```bash
python -m agent extract-spec \
  --code-file path/to/simple_add.rs \
  --output extracted_spec.json
```

Optional flags:

- `--code-language rust|c|go|python|javascript|typescript|java|cpp|unknown`
  overrides auto-detection.
- `--domain math|financial|security|...` supplies a domain hint to the existing
  natural-language spec extractor.
- Existing `extract-spec` flags such as `--generate`, `--forge`, and
  `--max-retries` continue to work.

## MCP

The MCP server exposes `extract_spec_from_code`:

```json
{
  "code_file": "/repo/src/simple_add.rs",
  "language": "rust",
  "domain_hint": "math",
  "generate": false,
  "mumei_repo": "/home/ubuntu/repos/mumei"
}
```

The response includes:

- `natural_language_spec`
- `detected_language`
- `spec`
- `warnings`
- optional `code`, `verified`, and `final_spec` when `generate=true`

## Configuration

Code-to-spec is enabled by default. Set `ENABLE_CODE_TO_SPEC=false` to disable
the feature through `AgentConfig.enable_code_to_spec`.
