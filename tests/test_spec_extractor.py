"""Tests for natural language specification extraction."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from agent import mcp_server
from agent.metrics import Metrics
from agent.prompts.spec_extraction import build_extraction_prompt
from agent.spec_extractor import (
    _extract_json,
    _keyword_validation_errors,
    _scan_std_catalog_local,
    _validate_extracted_spec,
    extract_and_generate,
    extract_spec,
    validate_forge_task_spec,
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

VALID_MULTI_SPEC = {
    "task_id": "nl-bank-transfer",
    "target_file": "std/finance/bank_transfer.mm",
    "mode": "create",
    "atoms": [
        {
            "name": "debit_transfer",
            "description": "Debit a sender balance safely",
            "inputs": [
                {"name": "sender_balance", "type": "i64"},
                {"name": "amount", "type": "i64"},
            ],
            "return_type": "i64",
            "requires": "sender_balance >= amount && amount > 0",
            "ensures": "result == sender_balance - amount && result >= 0",
            "effects": ["State(balance)"],
        },
        {
            "name": "credit_transfer",
            "description": "Credit a receiver balance safely",
            "inputs": [
                {"name": "receiver_balance", "type": "i64"},
                {"name": "amount", "type": "i64"},
            ],
            "return_type": "i64",
            "requires": "receiver_balance >= 0 && amount > 0",
            "ensures": "result == receiver_balance + amount && result >= receiver_balance",
            "effects": ["State(balance)"],
        },
    ],
}


def test_extract_spec_basic() -> None:
    client = _mock_client(json.dumps(VALID_SPEC))

    result = extract_spec(client, "m", "安全な銀行送金機能")

    assert result == VALID_SPEC
    call = client.chat.completions.create.call_args
    assert call.kwargs["messages"][0]["role"] == "system"
    assert "安全な銀行送金機能" in call.kwargs["messages"][1]["content"]


def test_extract_spec_detects_ambiguity_when_enabled(caplog) -> None:
    client = _mock_client(json.dumps(VALID_SPEC))

    result = extract_spec(
        client,
        "m",
        "必要に応じて適切な検査を行う",
        detect_ambiguity=True,
        config=MagicMock(enable_ambiguity_detection=False),
    )

    assert result == VALID_SPEC
    assert "Ambiguity detected in specification" in caplog.text


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
    assert "atoms[0].description must be a non-empty string" in errors
    assert "atoms[0].return_type must be a non-empty string" in errors
    assert "atoms[0].requires must be a non-empty string" in errors
    assert "atoms[0].ensures must be a non-empty string" in errors
    assert "atoms[0].inputs[0].type must be a non-empty string" in errors
    assert "atoms[0].effects must be a list" in errors


def test_validate_extracted_spec_rejects_unsafe_paths_and_bad_optional_fields() -> None:
    spec = dict(
        VALID_SPEC,
        target_file="std/../secrets.mm",
        priority=True,
        max_retries=0,
        auto_commit="yes",
    )

    errors = _validate_extracted_spec(spec)

    assert "target_file must be a safe relative std/*.mm path" in errors
    assert "priority must be an integer when present" in errors
    assert "max_retries must be a positive integer when present" in errors
    assert "auto_commit must be a boolean when present" in errors


def test_validate_extracted_spec_rejects_bad_atom_names_and_effects() -> None:
    spec = dict(
        VALID_SPEC,
        atoms=[
            dict(VALID_SPEC["atoms"][0], name="bad-name", effects=["State(balance)", ""]),
            dict(
                VALID_SPEC["atoms"][0],
                name="bad-name",
                reference_patterns=["safe_subtract", ""],
            ),
        ],
    )

    errors = _validate_extracted_spec(spec)

    assert "atoms[0].name must match [A-Za-z_][A-Za-z0-9_]*" in errors
    assert "atoms[0].effects entries must be non-empty strings" in errors
    assert "atoms[1].name must match [A-Za-z_][A-Za-z0-9_]*" in errors
    assert "atoms[1].name must be unique within atoms" in errors
    assert "atoms[1].reference_patterns must be a list of non-empty strings" in errors


def test_validate_forge_task_spec_raises_with_feedback() -> None:
    spec = dict(VALID_SPEC, target_file="std/math/safe_add")

    try:
        validate_forge_task_spec(spec)
    except ValueError as exc:
        assert "invalid forge task spec" in str(exc)
        assert "safe relative std/*.mm path" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("validate_forge_task_spec should reject invalid specs")


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
    assert "Previous LLM output" in retry_prompt
    assert "not json" in retry_prompt


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


def test_build_extraction_prompt_expanded_domain_hints() -> None:
    financial = build_extraction_prompt("送金", domain_hint="financial")
    compliance = build_extraction_prompt("KYC分類", domain_hint="compliance")
    regtech = build_extraction_prompt("AML分類", domain_hint="regtech")
    data_structure = build_extraction_prompt("queue push", domain_hint="data_structure")
    math = build_extraction_prompt("絶対値", domain_hint="math")
    crypto = build_extraction_prompt("RSA署名検証", domain_hint="rsa signature")
    method_signature = build_extraction_prompt(
        "関数シグネチャ検証",
        domain_hint="method signature validation",
    )
    digital_signature = build_extraction_prompt(
        "デジタル署名検証",
        domain_hint="digital_signature verification",
    )

    assert "Financial domain conventions" in financial
    assert "CustomerType" in compliance
    assert "Compliance / KYC / AML / RegTech" in regtech
    assert "Boundary checks before indexing" in data_structure
    assert "Prevent overflow" in math
    assert "Cryptography domain conventions" in crypto
    assert "mod(pow(signature, public_key), n)" in crypto
    assert "mod(message, n)" in crypto
    assert "Cryptography domain conventions" not in method_signature
    assert "Cryptography domain conventions" in digital_signature


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


def test_extract_json_repairs_trailing_commas_comments_and_incomplete_closers() -> None:
    raw = """
    {
      // generated by model
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
        },
      ]
    """

    assert _extract_json(raw) == VALID_SPEC


def test_extract_json_repairs_single_quoted_json() -> None:
    raw = """
    {
      'task_id': 'nl-single-quote',
      'target_file': 'std/math/abs.mm',
      'mode': 'create',
      'atoms': [{
        'name': 'abs_i64',
        'description': 'Absolute value',
        'inputs': [{'name': 'x', 'type': 'i64'}],
        'return_type': 'i64',
        'requires': 'x > i64::MIN',
        'ensures': 'result >= 0',
        'effects': [],
      }],
    }
    """

    parsed = _extract_json(raw)

    assert parsed["task_id"] == "nl-single-quote"
    assert parsed["atoms"][0]["name"] == "abs_i64"


def test_extract_spec_retry_includes_validation_errors_and_previous_output() -> None:
    invalid_spec = {"task_id": "bad", "target_file": "not-std.mm", "atoms": []}
    client = _mock_client(json.dumps(invalid_spec), json.dumps(VALID_SPEC))

    result = extract_spec(client, "m", "安全な銀行送金機能", max_retries=2)

    assert result == VALID_SPEC
    retry_prompt = client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert "Previous LLM output" in retry_prompt
    assert "target_file must be a string starting" in retry_prompt
    assert '"target_file": "not-std.mm"' in retry_prompt


def test_extract_spec_multi_atom_requirement() -> None:
    client = _mock_client(json.dumps(VALID_MULTI_SPEC))

    result = extract_spec(
        client,
        "m",
        "銀行送金機能。送金と受取の両方を実装する。",
        domain_hint="financial",
    )

    assert [atom["name"] for atom in result["atoms"]] == [
        "debit_transfer",
        "credit_transfer",
    ]
    assert all("State(balance)" in atom["effects"] for atom in result["atoms"])


def test_extract_spec_preserves_temporal_and_state_effects() -> None:
    effect_spec = dict(VALID_MULTI_SPEC)
    effect_spec["task_id"] = "nl-settlement-effects"
    effect_spec["atoms"] = [
        dict(VALID_MULTI_SPEC["atoms"][0], effects=["Temporal(settlement)"]),
        dict(VALID_MULTI_SPEC["atoms"][1], effects=["State(balance)"]),
    ]
    client = _mock_client(json.dumps(effect_spec))

    result = extract_spec(client, "m", "時系列の決済と残高更新", domain_hint="financial")

    effects = [atom["effects"][0] for atom in result["atoms"]]
    assert effects == ["Temporal(settlement)", "State(balance)"]


def test_keyword_validation_additional_keyword_groups() -> None:
    copied_example = dict(VALID_SPEC, atoms=[dict(VALID_SPEC["atoms"][0], name="safe_add")])

    queue_errors = _keyword_validation_errors(
        copied_example,
        "Queue enqueue should respect capacity before insertion.",
    )
    list_errors = _keyword_validation_errors(copied_example, "List indexing checks bounds.")
    aml_errors = _keyword_validation_errors(copied_example, "AML sanction screening")
    overflow_errors = _keyword_validation_errors(copied_example, "Prevent overflow in math")

    assert queue_errors
    assert list_errors
    assert aml_errors
    assert overflow_errors


def test_keyword_validation_avoids_list_substring_false_positive() -> None:
    errors = _keyword_validation_errors(
        VALID_SPEC,
        "Create a realistic authentication handler.",
    )

    assert errors == []


def test_extract_and_generate_e2e_with_mumei_mock() -> None:
    client = _mock_client(json.dumps(VALID_SPEC))
    mumei_client = MagicMock()

    with patch("agent.spec_extractor.generate_code") as mock_generate:
        mock_generate.return_value = ("atom safe_transfer() body: 0;", True)
        code, verified, final_spec = extract_and_generate(
            client,
            "m",
            "安全な銀行送金機能",
            domain_hint="financial",
            mumei_client=mumei_client,
            max_extraction_retries=1,
            max_generation_retries=4,
            max_refinements=0,
        )

    assert code == "atom safe_transfer() body: 0;"
    assert verified is True
    assert final_spec["name"] == "safe_transfer"
    assert mock_generate.call_args.kwargs["mumei_client"] is mumei_client
    assert mock_generate.call_args.kwargs["config_max_retries"] == 4


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
