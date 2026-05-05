"""Live E2E tests for natural-language forge task extraction."""
from __future__ import annotations

import os

import pytest

from agent.config import AgentConfig
from agent.spec_extractor import _validate_extracted_spec, extract_spec


pytestmark = pytest.mark.integration


_LLM_ENV_VARS = ("LLM_API_KEY", "OPENAI_API_KEY")


def _has_llm_credentials() -> bool:
    return any(os.environ.get(name) for name in _LLM_ENV_VARS)


def _llm_config() -> AgentConfig:
    if not _has_llm_credentials():
        pytest.skip("LLM credentials not available (set LLM_API_KEY or OPENAI_API_KEY)")
    return AgentConfig()


def _assert_valid_forge_task_spec(spec: dict[str, object]) -> None:
    assert _validate_extracted_spec(spec) == []
    target_file = spec["target_file"]
    atoms = spec["atoms"]
    assert isinstance(target_file, str)
    assert target_file.startswith("std/")
    assert spec["mode"] in {"append", "create", "replace"}
    assert isinstance(atoms, list)
    assert atoms
    for atom in atoms:
        assert isinstance(atom, dict)
        assert atom["name"].strip()
        assert atom["return_type"].strip()
        assert atom["requires"].strip()
        assert atom["ensures"].strip()
        assert isinstance(atom["effects"], list)
        assert atom.get("inputs") or atom.get("params")


@pytest.mark.parametrize(
    ("natural_language", "domain_hint"),
    [
        (
            "安全な銀行送金機能。残高不足はエラーにする。"
            "送金額は正の整数のみ。送金後の残高は非負。",
            "financial",
        ),
        (
            "KYC顧客分類。Individual, Corporate, Government, PEP の4タイプ。"
            "各タイプにリスクレベルを割り当て。PEPは最高リスク。",
            "regtech",
        ),
        (
            "絶対値関数。負の入力は正に変換。ゼロはゼロのまま。"
            "結果は常に非負。",
            "",
        ),
    ],
)
def test_extract_spec_examples_return_valid_forge_task_specs(
    natural_language: str,
    domain_hint: str,
) -> None:
    config = _llm_config()

    spec = extract_spec(
        config.create_client(),
        config.model,
        natural_language,
        domain_hint=domain_hint,
        max_retries=3,
    )

    _assert_valid_forge_task_spec(spec)


def test_extract_spec_regtech_domain_is_accepted_by_cli_parser() -> None:
    from agent.extract_spec import build_parser

    args = build_parser().parse_args(
        [
            "--text",
            "KYC顧客分類。PEPは最高リスク。",
            "--domain",
            "regtech",
            "--output",
            "/tmp/kyc_spec.json",
        ]
    )

    assert args.domain == "regtech"
