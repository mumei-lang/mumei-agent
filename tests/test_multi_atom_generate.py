"""Tests for P6-A: Multi-atom / Multi-file Generation."""
import json
from pathlib import Path
from unittest.mock import MagicMock

from agent.metrics import Metrics
from agent.strategies.generate_strategy import (
    _build_skeleton,
    _detect_dependencies,
    _build_multi_atom_prompt,
    _identify_failing_atoms,
    generate_code,
    generate_multi_atom,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(text: str) -> MagicMock:
    """Create a mock completion response."""
    message = MagicMock()
    message.content = text
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def _mock_client(response_text: str) -> MagicMock:
    """Create a mock OpenAI client that returns the given text."""
    client = MagicMock()
    client.chat.completions.create.return_value = _make_response(response_text)
    return client


MULTI_ATOM_SPEC = {
    "module_name": "math_utils",
    "atoms": [
        {
            "name": "safe_div",
            "inputs": [{"name": "a", "type": "i64"}, {"name": "b", "type": "i64"}],
            "requires": "b != 0",
            "ensures": "result * b == a",
            "effects": [],
        },
        {
            "name": "safe_sqrt",
            "inputs": [{"name": "x", "type": "i64"}],
            "requires": "x >= 0",
            "ensures": "result >= 0",
            "effects": [],
        },
        {
            "name": "safe_div_sqrt",
            "inputs": [{"name": "a", "type": "i64"}, {"name": "b", "type": "i64"}],
            "requires": "b != 0 && a >= 0",
            "ensures": "result >= 0",
            "effects": [],
            "description": "Divide a by b, then take safe_sqrt of the result. Depends on safe_div and safe_sqrt.",
        },
    ],
}


# ---------------------------------------------------------------------------
# Skeleton generation tests
# ---------------------------------------------------------------------------

def test_multi_atom_skeleton_generation():
    """Test that multi-atom skeleton generation produces valid concatenated skeletons."""
    atoms = MULTI_ATOM_SPEC["atoms"]
    deps = _detect_dependencies(atoms)
    combined = _build_multi_atom_prompt(atoms, deps)

    # All atoms should be present
    assert "atom safe_div(a: i64, b: i64)" in combined
    assert "atom safe_sqrt(x: i64)" in combined
    assert "atom safe_div_sqrt(a: i64, b: i64)" in combined

    # Each skeleton should have placeholders
    assert combined.count("requires: ___;") == 3
    assert combined.count("ensures: ___;") == 3


def test_single_atom_build_skeleton_still_works():
    """Test backward compatibility: single-atom skeleton generation."""
    spec = {"name": "add", "params": [{"name": "a", "type": "i64"}, {"name": "b", "type": "i64"}]}
    result = _build_skeleton(spec)
    assert "atom add(a: i64, b: i64)" in result
    assert "requires: ___;" in result
    assert "ensures: ___;" in result


# ---------------------------------------------------------------------------
# Dependency detection tests
# ---------------------------------------------------------------------------

def test_dependency_detection_between_atoms():
    """Test that atom B referencing atom A is detected as a dependency."""
    atoms = MULTI_ATOM_SPEC["atoms"]
    deps = _detect_dependencies(atoms)

    # safe_div_sqrt depends on safe_div and safe_sqrt via description
    assert "safe_div" in deps["safe_div_sqrt"]
    assert "safe_sqrt" in deps["safe_div_sqrt"]

    # safe_div and safe_sqrt have no dependencies
    assert deps["safe_div"] == []
    assert deps["safe_sqrt"] == []


def test_dependency_context_in_prompt():
    """Test that dependency context appears in the prompt for dependent atoms."""
    atoms = MULTI_ATOM_SPEC["atoms"]
    deps = _detect_dependencies(atoms)
    combined = _build_multi_atom_prompt(atoms, deps)

    # safe_div_sqrt section should include dependency context
    assert "Dependency: safe_div" in combined
    assert "Dependency: safe_sqrt" in combined


def test_no_self_dependency():
    """Test that an atom does not depend on itself."""
    atoms = [
        {"name": "foo", "requires": "foo > 0", "ensures": "foo > 0"},
    ]
    deps = _detect_dependencies(atoms)
    assert deps["foo"] == []


# ---------------------------------------------------------------------------
# Identify failing atoms tests
# ---------------------------------------------------------------------------

def test_identify_failing_atoms_single():
    """Test identifying a single failing atom from report."""
    report = {"atom": "safe_div"}
    result = _identify_failing_atoms(report, ["safe_div", "safe_sqrt"])
    assert result == ["safe_div"]


def test_identify_failing_atoms_multiple():
    """Test identifying multiple failing atoms from report."""
    report = {"atoms": ["safe_div", "safe_sqrt"]}
    result = _identify_failing_atoms(report, ["safe_div", "safe_sqrt", "safe_div_sqrt"])
    assert result == ["safe_div", "safe_sqrt"]


def test_identify_failing_atoms_fallback():
    """Test fallback to all atoms when report doesn't specify."""
    report = {"status": "failed"}
    result = _identify_failing_atoms(report, ["safe_div", "safe_sqrt"])
    assert result == ["safe_div", "safe_sqrt"]


# ---------------------------------------------------------------------------
# generate_code dispatch tests
# ---------------------------------------------------------------------------

def test_generate_code_dispatches_to_multi_atom():
    """Test that generate_code dispatches to generate_multi_atom for multi-atom specs."""
    generated = (
        "atom safe_div(a: i64, b: i64)\n"
        "    requires: b != 0;\n"
        "    ensures: result * b == a;\n"
        "    body: a / b;\n\n"
        "atom safe_sqrt(x: i64)\n"
        "    requires: x >= 0;\n"
        "    ensures: result >= 0;\n"
        "    body: x;\n"
    )
    client = _mock_client(f"```mumei\n{generated}\n```")
    metrics = Metrics()
    code, verified = generate_code(client, "m", MULTI_ATOM_SPEC, mumei_client=None, metrics=metrics)
    assert "safe_div" in code
    assert "safe_sqrt" in code
    assert verified is True


def test_generate_code_single_atom_still_works():
    """Test backward compatibility: single-atom spec still works through generate_code."""
    client = _mock_client("```mumei\natom add(a: i64, b: i64) body: a + b;\n```")
    spec = {"name": "add", "params": [{"name": "a", "type": "i64"}, {"name": "b", "type": "i64"}]}
    code, verified = generate_code(client, "m", spec, mumei_client=None)
    assert "atom add" in code
    assert verified is True


# ---------------------------------------------------------------------------
# Full generate_multi_atom pipeline (mock-based)
# ---------------------------------------------------------------------------

def test_generate_multi_atom_without_mumei_client():
    """Test multi-atom generation without mumei_client (no verification)."""
    generated = (
        "atom safe_div(a: i64, b: i64)\n"
        "    requires: b != 0;\n"
        "    ensures: result * b == a;\n"
        "    body: a / b;\n\n"
        "atom safe_sqrt(x: i64)\n"
        "    requires: x >= 0;\n"
        "    ensures: result >= 0;\n"
        "    body: x;\n"
    )
    client = _mock_client(f"```mumei\n{generated}\n```")
    metrics = Metrics()
    code, verified = generate_multi_atom(
        client, "m", MULTI_ATOM_SPEC, mumei_client=None, metrics=metrics,
    )
    assert "safe_div" in code
    assert "safe_sqrt" in code
    assert verified is True
    assert metrics.successes == 1


def test_generate_multi_atom_verified_on_first_try():
    """Test multi-atom generation that passes verification on first try."""
    generated = (
        "atom safe_div(a: i64, b: i64)\n"
        "    requires: b != 0;\n"
        "    ensures: result * b == a;\n"
        "    body: a / b;\n"
    )
    client = _mock_client(f"```mumei\n{generated}\n```")
    mumei = MagicMock()
    mumei.check.return_value = {"success": True, "stdout": "", "stderr": ""}
    mumei.verify.return_value = {
        "success": True,
        "report": {"status": "ok"},
        "stdout": "",
        "stderr": "",
    }

    metrics = Metrics()
    code, verified = generate_multi_atom(
        client, "m", MULTI_ATOM_SPEC,
        mumei_client=mumei, metrics=metrics,
    )
    assert verified is True
    assert metrics.successes == 1


def test_generate_multi_atom_fix_after_verify_failure():
    """Test that multi-atom generation retries with targeted fix on failure."""
    generated_bad = (
        "atom safe_div(a: i64, b: i64)\n"
        "    requires: true;\n"
        "    body: a / b;\n"
    )
    generated_fixed = (
        "atom safe_div(a: i64, b: i64)\n"
        "    requires: b != 0;\n"
        "    ensures: result * b == a;\n"
        "    body: a / b;\n"
    )
    client = MagicMock()
    client.chat.completions.create.side_effect = [
        _make_response(f"```mumei\n{generated_bad}\n```"),
        _make_response(f"```mumei\n{generated_fixed}\n```"),
    ]

    mumei = MagicMock()
    mumei.check.return_value = {"success": True, "stdout": "", "stderr": ""}
    mumei.verify.side_effect = [
        {
            "success": False,
            "report": {"atom": "safe_div", "failure_type": "precondition_violated"},
            "stdout": "Error",
            "stderr": "",
        },
        {
            "success": True,
            "report": {"status": "ok"},
            "stdout": "",
            "stderr": "",
        },
    ]

    metrics = Metrics()
    code, verified = generate_multi_atom(
        client, "m", MULTI_ATOM_SPEC,
        mumei_client=mumei, metrics=metrics,
    )
    assert verified is True
    assert "b != 0" in code

    # The fix prompt should have been targeted at the failing atom
    fix_call = client.chat.completions.create.call_args_list[1]
    fix_prompt = fix_call.kwargs["messages"][1]["content"]
    assert "safe_div" in fix_prompt


def test_generate_multi_atom_all_retries_exhausted():
    """Test that generate_multi_atom returns verified=False when all retries fail."""
    generated_bad = "atom bad() body: ;\n"
    client = MagicMock()
    client.chat.completions.create.side_effect = [
        _make_response(f"```mumei\n{generated_bad}\n```"),
        _make_response(f"```mumei\n{generated_bad}\n```"),
        _make_response(f"```mumei\n{generated_bad}\n```"),
    ]

    mumei = MagicMock()
    mumei.check.return_value = {"success": True, "stdout": "", "stderr": ""}
    mumei.verify.return_value = {
        "success": False,
        "report": {"failure_type": "postcondition_violated"},
        "stdout": "Error",
        "stderr": "",
    }

    metrics = Metrics()
    code, verified = generate_multi_atom(
        client, "m", MULTI_ATOM_SPEC,
        config_max_retries=2,
        mumei_client=mumei, metrics=metrics,
    )
    assert verified is False
    assert metrics.successes == 0


# ---------------------------------------------------------------------------
# Fixture file loading test
# ---------------------------------------------------------------------------

def test_multi_atom_spec_fixture_is_valid():
    """Test that the multi_atom_spec.json fixture is valid and loadable."""
    fixture_path = Path(__file__).parent / "fixtures" / "multi_atom_spec.json"
    spec = json.loads(fixture_path.read_text(encoding="utf-8"))

    assert "module_name" in spec
    assert spec["module_name"] == "math_utils"
    assert "atoms" in spec
    assert len(spec["atoms"]) == 3

    for atom in spec["atoms"]:
        assert "name" in atom
        assert "inputs" in atom
