"""Tests for natural language specification extraction."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from agent import mcp_server
from agent.metrics import Metrics
from agent.prompts.spec_extraction import build_extraction_prompt
from agent.spec_extractor import (
    _keyword_validation_errors,
    _scan_std_catalog_local,
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
    # Single-atom forge task specs are normalized into the flat single-atom
    # generation shape before being passed to the refinement loop.
    assert "atoms" not in final_spec
    assert final_spec["name"] == "safe_transfer"
    assert final_spec["target_file"] == "std/finance/safe_transfer.mm"
    assert final_spec["module_name"] == "std/finance/safe_transfer"
    mock_generate.assert_called_once()
    assert mock_generate.call_args.kwargs["config_max_retries"] == 2
    # The spec passed to generate_code must also be the normalized form so
    # the CLI and extract_and_generate pipelines stay in sync.
    forwarded_spec = mock_generate.call_args.args[2]
    assert "atoms" not in forwarded_spec
    assert forwarded_spec["name"] == "safe_transfer"


def test_extract_spec_with_domain_hint() -> None:
    prompt = build_extraction_prompt("送金", domain_hint="financial")

    assert "Domain: financial" in prompt
    assert "Financial domain conventions" in prompt
    assert "sender_balance >= amount" in prompt


def test_build_extraction_prompt_matches_domain_hint_substring() -> None:
    prompt = build_extraction_prompt("PUT API", domain_hint="public web endpoint")

    assert "Web API domain conventions" in prompt
    assert "result >= 100 && result <= 599" in prompt


def test_keyword_validation_rejects_example_copy() -> None:
    copied_example = dict(VALID_SPEC, task_id="nl-safe-add")
    copied_example["atoms"] = [
        {
            "name": "safe_add",
            "description": "Overflow-safe addition",
            "inputs": [
                {"name": "a", "type": "i64"},
                {"name": "b", "type": "i64"},
            ],
            "return_type": "i64",
            "requires": "a >= 0 && b >= 0",
            "ensures": "result == a + b",
            "effects": [],
        }
    ]

    errors = _keyword_validation_errors(
        copied_example,
        "KYC顧客分類。PEPは最高リスク。",
    )

    assert errors
    assert "do not copy the schema example" in errors[0]


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


def test_scan_std_catalog_local_from_mumei_repo_env(tmp_path, monkeypatch) -> None:
    repo = tmp_path / "mumei"
    std = repo / "std" / "math"
    std.mkdir(parents=True)
    (std / "safe.mm").write_text(
        "atom safe_add(a: i64, b: i64) -> i64\n"
        "trusted atom ffi_abs(x: i64) -> i64\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MUMEI_REPO", str(repo))
    mumei_client = MagicMock()
    mumei_client.mumei_bin = str(repo / "target" / "debug" / "mumei")

    catalog = _scan_std_catalog_local(mumei_client)

    assert "- std/math/safe.mm: safe_add, ffi_abs" in catalog


def test_scan_std_catalog_local_from_mumei_bin(tmp_path, monkeypatch) -> None:
    repo = tmp_path / "mumei"
    bin_dir = repo / "target" / "debug"
    std = repo / "std"
    bin_dir.mkdir(parents=True)
    std.mkdir()
    (std / "io.mm").write_text("trusted atom read_file(path: str) -> str\n", encoding="utf-8")
    monkeypatch.delenv("MUMEI_REPO", raising=False)
    mumei_client = MagicMock()
    mumei_client.mumei_bin = str(bin_dir / "mumei")

    catalog = _scan_std_catalog_local(mumei_client)

    assert "- std/io.mm: read_file" in catalog


def test_extract_spec_records_metrics() -> None:
    client = _mock_client("not json", json.dumps(VALID_SPEC))
    metrics = Metrics()

    result = extract_spec(client, "m", "安全な加算", max_retries=2, metrics=metrics)

    assert result == VALID_SPEC
    assert metrics.extraction_attempts == 2
    assert metrics.extraction_successes == 1
    assert metrics.extraction_success_rate == 0.5


def test_extract_spec_does_not_record_keyword_validation_failure_as_success() -> None:
    copied_example = dict(VALID_SPEC, task_id="nl-safe-add")
    copied_example["atoms"] = [
        {
            "name": "safe_add",
            "description": "Overflow-safe addition",
            "inputs": [
                {"name": "a", "type": "i64"},
                {"name": "b", "type": "i64"},
            ],
            "return_type": "i64",
            "requires": "a >= 0 && b >= 0",
            "ensures": "result == a + b",
            "effects": [],
        }
    ]
    valid_kyc_spec = {
        "task_id": "nl-kyc-risk",
        "target_file": "std/security/kyc.mm",
        "mode": "create",
        "atoms": [
            {
                "name": "classify_kyc_risk",
                "description": "Classify KYC customer risk",
                "inputs": [
                    {"name": "is_pep", "type": "i64"},
                    {"name": "has_sanction_hit", "type": "i64"},
                ],
                "return_type": "i64",
                "requires": "is_pep >= 0 && is_pep <= 1",
                "ensures": "result >= 0 && result <= 3",
                "effects": [],
            }
        ],
    }
    client = _mock_client(json.dumps(copied_example), json.dumps(valid_kyc_spec))
    metrics = Metrics()

    result = extract_spec(client, "m", "KYC顧客分類。PEPは最高リスク。", max_retries=2, metrics=metrics)

    assert result == valid_kyc_spec
    assert metrics.extraction_attempts == 2
    assert metrics.extraction_successes == 1


def test_extract_and_generate_shares_metrics_between_stages() -> None:
    client = _mock_client(json.dumps(VALID_SPEC))
    captured: dict[str, Metrics] = {}

    def fake_refinement(*args, **kwargs):
        captured["metrics"] = kwargs["metrics"]
        return ("atom safe_transfer() body: 0;", True, args[2])

    with patch("agent.spec_extractor.run_refinement_loop", side_effect=fake_refinement):
        extract_and_generate(
            client,
            "m",
            "安全な銀行送金機能",
            max_extraction_retries=1,
            max_generation_retries=1,
            max_refinements=0,
        )

    metrics = captured["metrics"]
    assert metrics.extraction_attempts == 1
    assert metrics.extraction_successes == 1


def test_extract_spec_mcp_tool() -> None:
    fake_config = MagicMock()
    fake_config.model = "m"
    fake_config.mumei_bin = "mumei"
    fake_config.create_client.return_value = MagicMock()

    def fake_extract(*args, **kwargs):
        metrics = kwargs.get("metrics")
        if metrics is not None:
            metrics.record_extraction_attempt()
            metrics.record_extraction_success()
        return VALID_SPEC

    with patch("agent.config.AgentConfig", return_value=fake_config), patch(
        "agent.mumei_client.create_mumei_client", return_value=None
    ), patch("agent.spec_extractor.extract_spec", side_effect=fake_extract):
        payload = json.loads(mcp_server.extract_spec("安全な銀行送金機能", "financial"))

    assert payload["status"] == "ok"
    assert payload["spec"] == VALID_SPEC
    assert payload["extraction_attempts"] == 1
    assert payload["extraction_successes"] == 1


def test_extract_spec_mcp_tool_uses_mumei_repo_binary_for_generate(tmp_path) -> None:
    fake_config = MagicMock()
    fake_config.model = "m"
    fake_config.mumei_bin = "mumei"
    fake_config.max_retries = 5
    fake_config.create_client.return_value = MagicMock()
    repo = tmp_path / "mumei"
    bin_dir = repo / "target" / "debug"
    bin_dir.mkdir(parents=True)
    mumei_bin = bin_dir / "mumei"
    mumei_bin.write_text("#!/bin/sh\n", encoding="utf-8")

    with patch("agent.config.AgentConfig", return_value=fake_config), patch(
        "agent.mumei_client.create_mumei_client", return_value=MagicMock()
    ) as mock_create, patch(
        "agent.spec_extractor.extract_and_generate",
        return_value=("atom safe_transfer() body: 0;", True, VALID_SPEC),
    ):
        payload = json.loads(
            mcp_server.extract_spec("安全な銀行送金機能", "financial", True, str(repo))
        )

    assert payload["status"] == "ok"
    assert payload["verified"] is True
    mock_create.assert_called_once_with(str(mumei_bin))
