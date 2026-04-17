"""Unit tests for Phase 2-B core.mm axiom injection in generate_strategy."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent.strategies import generate_strategy


SAMPLE_CORE_MM = """\
// std/core.mm — core axioms used throughout the mumei std library.

module core;

type Size = i64 where v >= 0;
type Index = i64 where v >= 0;
type NonZero = i64 where v != 0;
type BoundedIndex = i64 where v >= 0;

atom safe_to_non_negative(x: i64)
    requires: true;
    ensures: result >= 0;
    body: { if x < 0 then 0 else x };

atom checked_add(a: i64, b: i64, max_val: i64)
    requires: a >= 0 && b >= 0 && max_val >= 0 && a <= max_val && b <= max_val;
    ensures: result >= 0 && result <= max_val;
    body: { if a + b > max_val then max_val else a + b };

atom checked_sub(a: i64, b: i64)
    requires: a >= 0 && b >= 0 && a >= b;
    ensures: result >= 0 && result == a - b;
    body: { a - b };
"""


@pytest.fixture()
def core_mm_file(tmp_path: Path) -> Path:
    """Write a minimal std/core.mm to disk and return its path."""
    path = tmp_path / "core.mm"
    path.write_text(SAMPLE_CORE_MM, encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _clear_core_axiom_cache() -> None:
    """Reset the module-level cache between tests."""
    generate_strategy._CORE_AXIOM_CACHE.clear()


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestIsStdModule:
    @pytest.mark.parametrize(
        "key",
        ["output_path", "target_file", "module_name", "name"],
    )
    def test_detects_std_prefix(self, key: str) -> None:
        assert generate_strategy._is_std_module({key: "std/iter.mm"}) is True

    def test_detects_bare_std_module_name(self) -> None:
        assert generate_strategy._is_std_module({"module_name": "std/bitset"}) is True

    def test_rejects_non_std(self) -> None:
        assert generate_strategy._is_std_module({"target_file": "examples/foo.mm"}) is False

    def test_rejects_empty(self) -> None:
        assert generate_strategy._is_std_module({}) is False

    def test_normalises_leading_dot_slash(self) -> None:
        assert generate_strategy._is_std_module({"target_file": "./std/iter.mm"}) is True


class TestSummariseCoreAxioms:
    def test_extracts_type_definitions(self) -> None:
        summary = generate_strategy._summarise_core_axioms(SAMPLE_CORE_MM)
        assert "type Size = i64 where v >= 0;" in summary
        assert "type Index = i64 where v >= 0;" in summary
        assert "type NonZero = i64 where v != 0;" in summary
        assert "type BoundedIndex = i64 where v >= 0;" in summary

    def test_extracts_atom_signatures(self) -> None:
        summary = generate_strategy._summarise_core_axioms(SAMPLE_CORE_MM)
        assert "atom checked_add(a: i64, b: i64, max_val: i64)" in summary
        assert "atom checked_sub(a: i64, b: i64)" in summary
        assert "atom safe_to_non_negative(x: i64)" in summary

    def test_omits_body_blocks(self) -> None:
        summary = generate_strategy._summarise_core_axioms(SAMPLE_CORE_MM)
        # Body contents are not copied verbatim — they're replaced with
        # a signature-only rendering.
        assert "body:" not in summary
        assert "if a + b > max_val" not in summary


class TestLoadCoreAxiomContext:
    def test_returns_rendered_block(self, core_mm_file: Path) -> None:
        rendered = generate_strategy._load_core_axiom_context(core_mm_file)
        assert generate_strategy._CORE_AXIOM_HEADER in rendered
        assert "type Size = i64" in rendered
        assert "atom checked_add" in rendered

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        missing = tmp_path / "nope.mm"
        assert generate_strategy._load_core_axiom_context(missing) == ""

    def test_empty_path_returns_empty(self) -> None:
        assert generate_strategy._load_core_axiom_context("") == ""
        assert generate_strategy._load_core_axiom_context(None) == ""

    def test_caches_repeated_reads(self, core_mm_file: Path) -> None:
        first = generate_strategy._load_core_axiom_context(core_mm_file)
        with patch.object(Path, "read_text", side_effect=AssertionError("cache miss")):
            second = generate_strategy._load_core_axiom_context(core_mm_file)
        assert first == second


# ---------------------------------------------------------------------------
# Spec-aware injection decision
# ---------------------------------------------------------------------------


class TestBuildCoreAxiomContext:
    def test_std_module_injects_axioms(self, core_mm_file: Path) -> None:
        from agent.config import AgentConfig

        config = AgentConfig.__new__(AgentConfig)
        config.core_axiom_path = str(core_mm_file)
        config.inject_core_axioms = True
        spec = {"target_file": "std/iter.mm", "_agent_config": config}
        context = generate_strategy._build_core_axiom_context(spec)
        assert generate_strategy._CORE_AXIOM_HEADER in context
        assert "type Size = i64" in context

    def test_non_std_module_skips_injection(self, core_mm_file: Path) -> None:
        from agent.config import AgentConfig

        config = AgentConfig.__new__(AgentConfig)
        config.core_axiom_path = str(core_mm_file)
        config.inject_core_axioms = True
        spec = {"target_file": "examples/foo.mm", "_agent_config": config}
        assert generate_strategy._build_core_axiom_context(spec) == ""

    def test_disabled_flag_skips_injection(self, core_mm_file: Path) -> None:
        from agent.config import AgentConfig

        config = AgentConfig.__new__(AgentConfig)
        config.core_axiom_path = str(core_mm_file)
        config.inject_core_axioms = False
        spec = {"target_file": "std/iter.mm", "_agent_config": config}
        assert generate_strategy._build_core_axiom_context(spec) == ""

    def test_env_var_disable_without_config(
        self,
        core_mm_file: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("CORE_AXIOM_PATH", str(core_mm_file))
        monkeypatch.setenv("INJECT_CORE_AXIOMS", "false")
        spec = {"target_file": "std/iter.mm"}
        assert generate_strategy._build_core_axiom_context(spec) == ""

    def test_env_var_path_resolution_without_config(
        self,
        core_mm_file: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("CORE_AXIOM_PATH", str(core_mm_file))
        monkeypatch.delenv("INJECT_CORE_AXIOMS", raising=False)
        spec = {"target_file": "std/iter.mm"}
        context = generate_strategy._build_core_axiom_context(spec)
        assert "type Size = i64" in context


# ---------------------------------------------------------------------------
# End-to-end: generate_code injects axioms into the final prompt
# ---------------------------------------------------------------------------


def _build_mock_openai_client() -> MagicMock:
    client = MagicMock()
    message = MagicMock()
    message.content = (
        "```mumei\n"
        "atom stub(x: i64)\n"
        "    requires: true;\n"
        "    ensures: result >= 0;\n"
        "    body: { if x < 0 then 0 else x };\n"
        "```"
    )
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    client.chat.completions.create.return_value = response
    return client


class TestPromptInjectionSingleAtom:
    def test_std_spec_includes_axiom_block(self, core_mm_file: Path) -> None:
        from agent.config import AgentConfig

        config = AgentConfig.__new__(AgentConfig)
        config.core_axiom_path = str(core_mm_file)
        config.inject_core_axioms = True

        client = _build_mock_openai_client()
        spec = {
            "name": "stub",
            "target_file": "std/example.mm",
            "params": [{"name": "x", "type": "i64"}],
            "return_type": "i64",
            "requires": "true",
            "ensures": "result >= 0",
            "_agent_config": config,
        }
        generate_strategy.generate_code(
            client=client, model="test-model", spec=spec,
            config_max_retries=0, mumei_client=None,
        )
        call_args = client.chat.completions.create.call_args
        prompt_text = call_args.kwargs["messages"][1]["content"]
        assert generate_strategy._CORE_AXIOM_HEADER in prompt_text
        assert "type Size = i64" in prompt_text

    def test_non_std_spec_omits_axiom_block(self, core_mm_file: Path) -> None:
        from agent.config import AgentConfig

        config = AgentConfig.__new__(AgentConfig)
        config.core_axiom_path = str(core_mm_file)
        config.inject_core_axioms = True

        client = _build_mock_openai_client()
        spec = {
            "name": "stub",
            "target_file": "examples/not_std.mm",
            "params": [{"name": "x", "type": "i64"}],
            "return_type": "i64",
            "requires": "true",
            "ensures": "result >= 0",
            "_agent_config": config,
        }
        generate_strategy.generate_code(
            client=client, model="test-model", spec=spec,
            config_max_retries=0, mumei_client=None,
        )
        call_args = client.chat.completions.create.call_args
        prompt_text = call_args.kwargs["messages"][1]["content"]
        assert generate_strategy._CORE_AXIOM_HEADER not in prompt_text


class TestPromptInjectionMultiAtom:
    def test_std_multi_atom_spec_includes_axioms(self, core_mm_file: Path) -> None:
        from agent.config import AgentConfig

        config = AgentConfig.__new__(AgentConfig)
        config.core_axiom_path = str(core_mm_file)
        config.inject_core_axioms = True

        client = _build_mock_openai_client()
        spec = {
            "module_name": "std/iter",
            "target_file": "std/iter.mm",
            "atoms": [
                {
                    "name": "head",
                    "inputs": [{"name": "xs", "type": "List"}],
                    "return_type": "i64",
                    "requires": "true",
                    "ensures": "result >= 0",
                },
                {
                    "name": "tail_len",
                    "inputs": [{"name": "xs", "type": "List"}],
                    "return_type": "i64",
                    "requires": "true",
                    "ensures": "result >= 0",
                },
            ],
            "_agent_config": config,
        }
        generate_strategy.generate_multi_atom(
            client=client, model="test-model", spec=spec,
            config_max_retries=0, mumei_client=None,
        )
        call_args = client.chat.completions.create.call_args
        prompt_text = call_args.kwargs["messages"][1]["content"]
        assert generate_strategy._CORE_AXIOM_HEADER in prompt_text
        assert "type Size" in prompt_text

    def test_non_std_multi_atom_spec_omits_axioms(self, core_mm_file: Path) -> None:
        from agent.config import AgentConfig

        config = AgentConfig.__new__(AgentConfig)
        config.core_axiom_path = str(core_mm_file)
        config.inject_core_axioms = True

        client = _build_mock_openai_client()
        spec = {
            "module_name": "user_module",
            "target_file": "examples/user.mm",
            "atoms": [
                {
                    "name": "noop",
                    "inputs": [{"name": "x", "type": "i64"}],
                    "return_type": "i64",
                    "requires": "true",
                    "ensures": "result >= 0",
                },
            ],
            "_agent_config": config,
        }
        generate_strategy.generate_multi_atom(
            client=client, model="test-model", spec=spec,
            config_max_retries=0, mumei_client=None,
        )
        call_args = client.chat.completions.create.call_args
        prompt_text = call_args.kwargs["messages"][1]["content"]
        assert generate_strategy._CORE_AXIOM_HEADER not in prompt_text
