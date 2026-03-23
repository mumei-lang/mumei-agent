"""Tests for the E2E demo pipeline (examples/run_e2e_demo.py)."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from examples.run_e2e_demo import validate_spec, run_e2e


# ---------------------------------------------------------------------------
# validate_spec tests
# ---------------------------------------------------------------------------

class TestValidateSpec:
    """Tests for spec JSON validation."""

    def test_valid_spec_with_params(self):
        spec = {
            "name": "safe_add",
            "params": [
                {"name": "a", "type": "i64"},
                {"name": "b", "type": "i64"},
            ],
            "constraints": {"requires": "a >= 0", "ensures": "result == a + b"},
        }
        assert validate_spec(spec) == []

    def test_valid_spec_with_effects(self):
        spec = {
            "name": "fetch_github_user",
            "params": [{"name": "username", "type": "Str"}],
            "effects": ["SecureHttpGet"],
            "constraints": {"requires": "len(username) > 0", "ensures": "len(result) >= 0"},
        }
        assert validate_spec(spec) == []

    def test_valid_spec_with_inputs_fallback(self):
        spec = {
            "name": "legacy",
            "inputs": [{"name": "x", "type": "i64"}],
        }
        assert validate_spec(spec) == []

    def test_missing_name(self):
        spec = {"params": [{"name": "a"}]}
        errors = validate_spec(spec)
        assert any("name" in e for e in errors)

    def test_empty_name(self):
        spec = {"name": "", "params": [{"name": "a"}]}
        errors = validate_spec(spec)
        assert any("name" in e for e in errors)

    def test_params_not_list(self):
        spec = {"name": "bad", "params": "not_a_list"}
        errors = validate_spec(spec)
        assert any("list" in e for e in errors)

    def test_param_missing_name_key(self):
        spec = {"name": "bad", "params": [{"type": "i64"}]}
        errors = validate_spec(spec)
        assert any("params[0]" in e for e in errors)

    def test_constraints_not_dict(self):
        spec = {"name": "bad", "params": [], "constraints": "not_a_dict"}
        errors = validate_spec(spec)
        assert any("constraints" in e for e in errors)

    def test_effects_not_list(self):
        spec = {"name": "bad", "params": [], "effects": "not_a_list"}
        errors = validate_spec(spec)
        assert any("effects" in e for e in errors)

    def test_minimal_valid_spec(self):
        spec = {"name": "minimal"}
        assert validate_spec(spec) == []

    def test_no_constraints_is_valid(self):
        spec = {"name": "no_constraints", "params": [{"name": "x"}]}
        assert validate_spec(spec) == []


# ---------------------------------------------------------------------------
# Spec JSON file loading tests
# ---------------------------------------------------------------------------

class TestSpecFiles:
    """Verify the shipped spec JSON files are well-formed."""

    @pytest.fixture(params=["e2e_demo_spec.json", "simple_add_spec.json"])
    def spec_file(self, request):
        return Path(__file__).parent.parent / "examples" / request.param

    def test_spec_file_is_valid_json(self, spec_file):
        with open(spec_file, encoding="utf-8") as f:
            spec = json.load(f)
        assert isinstance(spec, dict)

    def test_spec_file_passes_validation(self, spec_file):
        with open(spec_file, encoding="utf-8") as f:
            spec = json.load(f)
        assert validate_spec(spec) == []

    def test_e2e_demo_spec_has_effects(self):
        path = Path(__file__).parent.parent / "examples" / "e2e_demo_spec.json"
        with open(path, encoding="utf-8") as f:
            spec = json.load(f)
        assert "effects" in spec
        assert "SecureHttpGet" in spec["effects"]

    def test_simple_add_spec_has_no_effects(self):
        path = Path(__file__).parent.parent / "examples" / "simple_add_spec.json"
        with open(path, encoding="utf-8") as f:
            spec = json.load(f)
        assert spec.get("effects", []) == []

    def test_simple_add_spec_has_constraints(self):
        path = Path(__file__).parent.parent / "examples" / "simple_add_spec.json"
        with open(path, encoding="utf-8") as f:
            spec = json.load(f)
        constraints = spec.get("constraints", {})
        assert "requires" in constraints
        assert "ensures" in constraints


# ---------------------------------------------------------------------------
# run_e2e dry-run tests
# ---------------------------------------------------------------------------

class TestRunE2EDryRun:
    """Test the dry-run mode (no LLM or mumei invocation)."""

    def test_dry_run_with_valid_spec(self):
        spec_path = str(Path(__file__).parent.parent / "examples" / "simple_add_spec.json")
        result = run_e2e(spec_path=spec_path, dry_run=True)
        assert result["dry_run"] is True
        assert result["errors"] == []
        assert result["code"] == ""
        assert result["verified"] is False

    def test_dry_run_with_e2e_spec(self):
        spec_path = str(Path(__file__).parent.parent / "examples" / "e2e_demo_spec.json")
        result = run_e2e(spec_path=spec_path, dry_run=True)
        assert result["dry_run"] is True
        assert result["errors"] == []

    def test_dry_run_with_invalid_spec(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump({"params": "not_a_list"}, f)
            f.flush()
            result = run_e2e(spec_path=f.name, dry_run=True)
        assert len(result["errors"]) > 0


# ---------------------------------------------------------------------------
# run_e2e with mocked LLM + MumeiClient
# ---------------------------------------------------------------------------

class TestRunE2EMocked:
    """Test the full pipeline with mocked dependencies."""

    def test_generate_only_mode(self, mock_openai_client):
        """When no mumei binary is available, generation-only mode is used."""
        spec_path = str(Path(__file__).parent.parent / "examples" / "simple_add_spec.json")
        generated = (
            "atom safe_add(a: i64, b: i64)\n"
            "    requires: a >= 0 && b >= 0;\n"
            "    ensures: result == a + b;\n"
            "    body: a + b;\n"
        )
        mock_client = mock_openai_client(f"```mumei\n{generated}```")
        mock_config = MagicMock()
        mock_config.create_client.return_value = mock_client
        mock_config.model = "test-model"
        mock_config.mumei_bin = ""

        # Patch at the source modules so deferred imports resolve to mocks
        with patch("agent.config.AgentConfig", return_value=mock_config), \
             patch("examples.run_e2e_demo._mumei_available", return_value=False), \
             patch(
                 "agent.strategies.generate_strategy.generate_code",
                 return_value=(generated, True),
             ):
            result = run_e2e(spec_path=spec_path, dry_run=False)

        assert result["errors"] == []

    def test_verified_with_mumei(self, mock_openai_client, mock_mumei_client):
        """Full pipeline with successful verification."""
        spec_path = str(Path(__file__).parent.parent / "examples" / "simple_add_spec.json")
        generated = (
            "atom safe_add(a: i64, b: i64)\n"
            "    requires: a >= 0 && b >= 0;\n"
            "    ensures: result == a + b;\n"
            "    body: a + b;\n"
        )
        mock_client = mock_openai_client(f"```mumei\n{generated}```")
        mock_mumei = mock_mumei_client(verify_success=True, check_success=True)
        mock_config = MagicMock()
        mock_config.create_client.return_value = mock_client
        mock_config.model = "test-model"
        mock_config.mumei_bin = "mumei"

        with patch("agent.config.AgentConfig", return_value=mock_config), \
             patch("agent.mumei_client.MumeiClient", return_value=mock_mumei), \
             patch("examples.run_e2e_demo._mumei_available", return_value=True), \
             patch(
                 "agent.strategies.generate_strategy.generate_code",
                 return_value=(generated, True),
             ):
            result = run_e2e(spec_path=spec_path, dry_run=False)

        assert result["errors"] == []
        assert result["verified"] is True
        assert result["code"] != ""
