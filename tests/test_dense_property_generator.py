"""Tests for high-density property generation."""
from __future__ import annotations

from unittest.mock import Mock

from agent.strategies.dense_property_generator import DensePropertyGenerator
from agent.strategies.generate_strategy import _apply_dense_properties


def test_dense_property_generator_initialization() -> None:
    """DensePropertyGenerator initializes."""
    assert DensePropertyGenerator() is not None


def test_extract_properties() -> None:
    """Existing properties are extracted from source."""
    generator = DensePropertyGenerator()
    source_code = """
    atom test(a: i64) -> i64
        requires: a > 0;
        ensures: result >= a;
        body: { a }
    """

    properties = generator._extract_properties(source_code)

    assert properties["requires"] == ["a > 0"]
    assert properties["ensures"] == ["result >= a"]


def test_generate_dense_properties_with_mock_llm() -> None:
    """Mock LLM output is decoded into properties."""
    generator = DensePropertyGenerator()
    spec = {
        "name": "test",
        "params": [{"name": "a", "type": "i64"}],
        "return_type": "i64",
    }
    source_code = (
        "atom test(a: i64) -> i64\n"
        "    requires: true;\n"
        "    ensures: true;\n"
        "    body: { a }\n"
    )

    mock_client = Mock()
    mock_response = Mock()
    mock_response.choices = [Mock()]
    mock_response.choices[0].message.content = (
        "requires: a > 0;\nensures: result >= a;"
    )
    mock_client.chat.completions.create = Mock(return_value=mock_response)

    dense_props = generator.generate_dense_properties(
        spec,
        source_code,
        mock_client,
        "test-model",
    )

    assert dense_props["requires"] == ["a > 0"]
    assert dense_props["ensures"] == ["result >= a"]


def test_apply_dense_properties_replaces_first_contracts() -> None:
    """Dense properties are applied to the first contract pair."""
    source_code = (
        "atom test(a: i64) -> i64\n"
        "    requires: true;\n"
        "    ensures: true;\n"
        "    body: { a }\n"
    )

    updated = _apply_dense_properties(
        source_code,
        {"requires": ["a > 0"], "ensures": ["result >= a"]},
    )

    assert "requires: a > 0;" in updated
    assert "ensures: result >= a;" in updated
