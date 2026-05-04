"""Tests for natural language specification extraction."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from agent import mcp_server
from agent.prompts.spec_extraction import build_extraction_prompt
from agent.spec_extractor import (
    _validate_extracted_spec,
    extract_and_generate,
    extract_spec,
)


def _make_response(text: str) -> MagicMock:
    message = MagicMock()
    message.content = text
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def _mock_client(*responses: str) -> MagicMock:
    client = MagicMock()
    client.chat.completions.create.side_effect = [
        _make_response(response) for response in responses
    ]
    return client


VALID_SPEC = {
    "task_id": "nl-safe-transfer",
    "target_file": "std/finance/safe_transfer.mm",
    "mode": "create",
    "atoms": [
        {
            "name": "safe_transfer",
            "description": "Safe bank transfer with balance checks",
            "inputs": [
                {"name": "from_balance", "type": "i64"},
                {"name": "amount", "type": "i64"},
            ],
            "return_type": "i64",
            "requires": "from_balance >= 0 && amount > 0 && from_balance >= amount",
            "ensures": "result == from_balance - amount && result >= 0",
            "effects": [],
        }
    ],
}


def test_extract_spec_basic() -> None:
    client = _mock_client(json.dumps(VALID_SPEC))

    result = extract_spec(client, "m", "安全な銀行送金機能")

    assert result == VALID_SPEC
    call = client.chat.completions.create.call_args
    assert call.kwargs["messages"][0]["role"] == "system"
    assert "安全な銀行送金機能" in call.kwargs["messages"][1]["content"]


def test_validate_extracted_spec_valid() -> None:
    assert _validate_extracted_spec(VALID_SPEC) == []


def test_validate_extracted_spec_missing_fields() -> None:
    errors = _validate_extracted_spec({"atoms": []})

    assert "task_id must be a non-empty string" in errors
    assert 'target_file must be a string starting with "std/"' in errors
    assert 'mode must be one of "append", "create", or "replace"' in errors
    assert "atoms must be a non-empty list" in errors


def test_validate_extracted_spec_invalid_atoms() -> None:
    spec = dict(VALID_SPEC, atoms=[{"name": "", "inputs": [{"name": "x"}]}])

    errors = _validate_extracted_spec(spec)

    assert "atoms[0].name must be a non-empty string" in errors
    assert "atoms[0].return_type must be a non-empty string" in errors
    assert "atoms[0].requires must be a non-empty string" in errors
    assert "atoms[0].ensures must be a non-empty string" in errors
    assert "atoms[0].inputs[0].type must be a non-empty string" in errors


def test_extract_spec_retry_on_invalid_json() -> None:
    client = _mock_client("not json", json.dumps(VALID_SPEC))

    result = extract_spec(client, "m", "安全な加算", max_retries=2)

    assert result == VALID_SPEC
    assert client.chat.completions.create.call_count == 2
    retry_prompt = (
        client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    )
    assert "Previous extraction failed" in retry_prompt
    assert "invalid JSON" in retry_prompt


def test_extract_and_generate_integration() -> None:
    client = _mock_client(json.dumps(VALID_SPEC))

    with patch("agent.spec_extractor.generate_code") as mock_generate:
        mock_generate.return_value = ("atom safe_transfer() body: 0;", True)
        code, verified, final_spec = extract_and_generate(
            client,
            "m",
            "安全な銀行送金機能",
            max_extraction_retries=1,
            max_generation_retries=2,
            max_refinements=0,
        )

    assert code == "atom safe_transfer() body: 0;"
    assert verified is True
    assert final_spec == VALID_SPEC
    mock_generate.assert_called_once()
    assert mock_generate.call_args.kwargs["config_max_retries"] == 2


def test_extract_spec_with_domain_hint() -> None:
    prompt = build_extraction_prompt("送金", domain_hint="financial")

    assert "Domain: financial" in prompt


def test_extract_spec_with_existing_catalog() -> None:
    client = _mock_client(json.dumps(VALID_SPEC))
    mumei_client = MagicMock()
    mumei_client.list_catalog.return_value = {"atoms": [{"name": "safe_subtract"}]}

    result = extract_spec(
        client,
        "m",
        "安全な送金",
        domain_hint="financial",
        mumei_client=mumei_client,
        max_retries=1,
    )

    assert result == VALID_SPEC
    prompt = client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert "safe_subtract" in prompt
    assert "Domain: financial" in prompt


def test_extract_spec_mcp_tool() -> None:
    fake_config = MagicMock()
    fake_config.model = "m"
    fake_config.mumei_bin = "mumei"
    fake_config.create_client.return_value = MagicMock()

    with patch("agent.config.AgentConfig", return_value=fake_config), patch(
        "agent.mumei_client.create_mumei_client", return_value=None
    ), patch("agent.spec_extractor.extract_spec", return_value=VALID_SPEC):
        payload = json.loads(mcp_server.extract_spec("安全な銀行送金機能", "financial"))

    assert payload["status"] == "ok"
    assert payload["spec"] == VALID_SPEC
