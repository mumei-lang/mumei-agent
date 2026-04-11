"""E2E integration tests for the publish pipeline (SI-3 verification).

These tests exercise the full publish() pipeline end-to-end using:
- Existing spec files from examples/
- The mock mumei binary (tests/fixtures/mock_mumei.py)
- dry_run=True to avoid git/PR operations

Run with: pytest tests/test_publish_e2e.py -m integration
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent.publish import publish

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"
FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _mock_config(mumei_bin: str = "mumei"):
    """Create a mock AgentConfig."""
    cfg = MagicMock()
    cfg.mumei_bin = mumei_bin
    cfg.model = "test-model"
    cfg.max_retries = 2
    cfg.create_client.return_value = MagicMock()
    return cfg


def _mock_generate_code(code: str, verified: bool = True):
    """Return a side_effect-compatible function for generate_code."""
    def _generate(*args, **kwargs):
        return code, verified
    return _generate


# Sample generated code for each spec type
_SINGLE_ATOM_CODE = """\
atom safe_add(a: i64, b: i64) -> i64
    requires: a >= 0 && b >= 0;
    ensures: result == a + b;
    body: a + b;
"""

_SAFE_DIV_CODE = """\
atom safe_div(a: i64, b: i64) -> i64
    requires: b != 0;
    ensures: result == a / b;
    body: a / b;
"""

_PAYMENT_CODE = """\
atom calc_subtotal(quantity: i64, price: i64) -> i64
    requires: quantity > 0 && price > 0;
    ensures: result > 0;
    body: quantity * price;

atom calc_tax(amount: i64, rate: i64) -> i64
    requires: amount > 0 && rate >= 0 && rate <= 100;
    ensures: result >= 0;
    body: amount * rate / 100;

atom calc_total(subtotal: i64, tax: i64) -> i64
    requires: subtotal > 0 && tax >= 0;
    ensures: result >= subtotal;
    body: subtotal + tax;
"""


def _ok_client(mc_class):
    """Configure a MumeiClient mock to return success for verify and build_with_emit."""
    inst = mc_class.return_value
    inst.verify.return_value = {
        "success": True, "report": {"status": "ok"}, "stdout": "", "stderr": "",
    }
    inst.build_with_emit.return_value = {
        "success": True, "stdout": "ok", "stderr": "",
    }
    return inst


# ---------------------------------------------------------------------------
# E2E tests with existing specs (dry_run=True)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestPublishE2EWithSpecs:
    """E2E tests using existing spec files from examples/."""

    def test_simple_add_spec(self, tmp_path):
        """Publish pipeline with simple_add_spec.json (single-atom)."""
        spec_path = str(EXAMPLES_DIR / "simple_add_spec.json")
        with patch("agent.publish.AgentConfig", return_value=_mock_config()), \
             patch("agent.publish.generate_code", side_effect=_mock_generate_code(_SINGLE_ATOM_CODE)), \
             patch("agent.publish.MumeiClient") as MC:
            _ok_client(MC)
            result = publish(
                spec_path=spec_path,
                repo_dir=str(tmp_path),
                dry_run=True,
            )

        assert result["success"] is True
        assert result["generated_file"] == "safe_add.mm"
        assert len(result["artifacts"]) == 3
        assert all(a["success"] for a in result["artifacts"])

        # Verify the generated .mm file was written
        mm_file = tmp_path / "safe_add.mm"
        assert mm_file.exists()
        content = mm_file.read_text()
        assert "atom safe_add" in content
        assert "requires:" in content
        assert "ensures:" in content

    def test_simple_e2e_spec(self, tmp_path):
        """Publish pipeline with simple_e2e_spec.json (safe_div)."""
        spec_path = str(EXAMPLES_DIR / "simple_e2e_spec.json")
        with patch("agent.publish.AgentConfig", return_value=_mock_config()), \
             patch("agent.publish.generate_code", side_effect=_mock_generate_code(_SAFE_DIV_CODE)), \
             patch("agent.publish.MumeiClient") as MC:
            _ok_client(MC)
            result = publish(
                spec_path=spec_path,
                repo_dir=str(tmp_path),
                dry_run=True,
            )

        assert result["success"] is True
        assert result["generated_file"] == "safe_div.mm"
        mm_file = tmp_path / "safe_div.mm"
        assert mm_file.exists()
        content = mm_file.read_text()
        assert "b != 0" in content

    def test_payment_multi_atom_spec(self, tmp_path):
        """Publish pipeline with payment_spec.json (multi-atom module)."""
        spec_path = str(EXAMPLES_DIR / "publish_demo" / "payment_spec.json")
        with patch("agent.publish.AgentConfig", return_value=_mock_config()), \
             patch("agent.publish.generate_code", side_effect=_mock_generate_code(_PAYMENT_CODE)), \
             patch("agent.publish.MumeiClient") as MC:
            _ok_client(MC)
            result = publish(
                spec_path=spec_path,
                repo_dir=str(tmp_path),
                dry_run=True,
            )

        assert result["success"] is True
        assert result["generated_file"] == "payment.mm"
        assert len(result["artifacts"]) == 3

        mm_file = tmp_path / "payment.mm"
        assert mm_file.exists()
        content = mm_file.read_text()
        # Verify all three atoms are present
        assert "calc_subtotal" in content
        assert "calc_tax" in content
        assert "calc_total" in content

    def test_emit_targets_are_called_correctly(self, tmp_path):
        """Verify build_with_emit is called with all 3 targets in order."""
        spec_path = str(EXAMPLES_DIR / "simple_add_spec.json")
        with patch("agent.publish.AgentConfig", return_value=_mock_config()), \
             patch("agent.publish.generate_code", side_effect=_mock_generate_code(_SINGLE_ATOM_CODE)), \
             patch("agent.publish.MumeiClient") as MC:
            inst = _ok_client(MC)
            publish(
                spec_path=spec_path,
                repo_dir=str(tmp_path),
                dry_run=True,
            )

        assert inst.build_with_emit.call_count == 3
        targets = [c[0][1] for c in inst.build_with_emit.call_args_list]
        assert targets == ["c-header", "rust-wrapper", "python-wrapper"]


# ---------------------------------------------------------------------------
# Full pipeline tests with mock mumei binary
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestPublishE2EMockBinary:
    """Full pipeline tests using the mock mumei binary.

    These tests use the mock_mumei.py script as the mumei binary and
    exercise the full generate -> verify -> emit path.
    """

    def test_pipeline_with_mock_binary(self, tmp_path):
        """Full pipeline: generate -> verify -> emit with mock binary."""
        spec_path = str(EXAMPLES_DIR / "simple_add_spec.json")
        mock_bin = f"{sys.executable} {FIXTURES_DIR / 'mock_mumei.py'}"

        with patch("agent.publish.AgentConfig", return_value=_mock_config(mock_bin)), \
             patch("agent.publish.generate_code", side_effect=_mock_generate_code(_SINGLE_ATOM_CODE)):
            result = publish(
                spec_path=spec_path,
                mumei_bin=mock_bin,
                repo_dir=str(tmp_path),
                dry_run=True,
            )

        assert result["success"] is True
        assert result["generated_file"] == "safe_add.mm"
        # Mock binary returns success for verify (valid code with no known violation)
        assert result.get("verify_error") is None

        # Check artifacts — mock binary doesn't actually emit files,
        # but the pipeline should still attempt all targets
        assert len(result["artifacts"]) == 3

    def test_pipeline_with_mock_binary_payment(self, tmp_path):
        """Full pipeline with multi-atom payment spec and mock binary."""
        spec_path = str(EXAMPLES_DIR / "publish_demo" / "payment_spec.json")
        mock_bin = f"{sys.executable} {FIXTURES_DIR / 'mock_mumei.py'}"

        with patch("agent.publish.AgentConfig", return_value=_mock_config(mock_bin)), \
             patch("agent.publish.generate_code", side_effect=_mock_generate_code(_PAYMENT_CODE)):
            result = publish(
                spec_path=spec_path,
                mumei_bin=mock_bin,
                repo_dir=str(tmp_path),
                dry_run=True,
            )

        assert result["success"] is True
        assert result["generated_file"] == "payment.mm"

        # Verify the .mm file was written with all atoms
        mm_file = tmp_path / "payment.mm"
        assert mm_file.exists()
        content = mm_file.read_text()
        assert "calc_subtotal" in content
        assert "calc_tax" in content
        assert "calc_total" in content

    def test_pipeline_result_structure(self, tmp_path):
        """Verify the result dict has all expected keys."""
        spec_path = str(EXAMPLES_DIR / "simple_add_spec.json")
        with patch("agent.publish.AgentConfig", return_value=_mock_config()), \
             patch("agent.publish.generate_code", side_effect=_mock_generate_code(_SINGLE_ATOM_CODE)), \
             patch("agent.publish.MumeiClient") as MC:
            _ok_client(MC)
            result = publish(
                spec_path=spec_path,
                repo_dir=str(tmp_path),
                dry_run=True,
            )

        # Required keys
        assert "success" in result
        assert "generated_file" in result
        assert "artifacts" in result
        assert "pr_url" in result

        # Dry-run specific
        assert result["pr_url"] is None
        assert result["verified_at_generation"] is True

    def test_pipeline_generation_failure_returns_error(self, tmp_path):
        """Pipeline returns meaningful error on generation failure."""
        spec_path = str(EXAMPLES_DIR / "simple_add_spec.json")
        with patch("agent.publish.AgentConfig", return_value=_mock_config()), \
             patch("agent.publish.generate_code", return_value=("", False)), \
             patch("agent.publish.MumeiClient"):
            result = publish(
                spec_path=spec_path,
                repo_dir=str(tmp_path),
                dry_run=True,
            )

        assert result["success"] is False
        assert result["generation_error"] == "empty code"
        assert result["generated_file"] is None

    def test_pipeline_verify_failure_returns_error(self, tmp_path):
        """Pipeline returns error when verification fails."""
        spec_path = str(EXAMPLES_DIR / "simple_add_spec.json")
        with patch("agent.publish.AgentConfig", return_value=_mock_config()), \
             patch("agent.publish.generate_code", side_effect=_mock_generate_code(_SINGLE_ATOM_CODE, verified=False)), \
             patch("agent.publish.MumeiClient") as MC:
            MC.return_value.verify.return_value = {
                "success": False,
                "report": {"status": "failed", "failure_type": "postcondition_violated"},
                "stdout": "",
                "stderr": "Verification failed: postcondition violated",
            }
            result = publish(
                spec_path=spec_path,
                repo_dir=str(tmp_path),
                dry_run=True,
            )

        assert result["success"] is False
        assert "verify_error" in result


# ---------------------------------------------------------------------------
# Generated file content validation
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestPublishE2EFileValidation:
    """Validate the content of generated files."""

    def test_generated_mm_has_atom_declaration(self, tmp_path):
        """Generated .mm file contains valid atom declaration."""
        spec_path = str(EXAMPLES_DIR / "simple_add_spec.json")
        with patch("agent.publish.AgentConfig", return_value=_mock_config()), \
             patch("agent.publish.generate_code", side_effect=_mock_generate_code(_SINGLE_ATOM_CODE)), \
             patch("agent.publish.MumeiClient") as MC:
            _ok_client(MC)
            publish(spec_path=spec_path, repo_dir=str(tmp_path), dry_run=True)

        mm_file = tmp_path / "safe_add.mm"
        content = mm_file.read_text()
        # Basic structure checks
        assert content.startswith("atom ")
        assert "requires:" in content
        assert "ensures:" in content
        assert "body:" in content

    def test_generated_mm_multi_atom_structure(self, tmp_path):
        """Multi-atom .mm file contains all atom declarations."""
        spec_path = str(EXAMPLES_DIR / "publish_demo" / "payment_spec.json")
        with patch("agent.publish.AgentConfig", return_value=_mock_config()), \
             patch("agent.publish.generate_code", side_effect=_mock_generate_code(_PAYMENT_CODE)), \
             patch("agent.publish.MumeiClient") as MC:
            _ok_client(MC)
            publish(spec_path=spec_path, repo_dir=str(tmp_path), dry_run=True)

        mm_file = tmp_path / "payment.mm"
        content = mm_file.read_text()

        # Count atom declarations
        atom_count = content.count("atom ")
        assert atom_count == 3

        # Verify contracts are present
        assert content.count("requires:") == 3
        assert content.count("ensures:") == 3

    def test_output_dir_passed_to_build_with_emit(self, tmp_path):
        """Verify output directory is correctly passed to build_with_emit."""
        spec_path = str(EXAMPLES_DIR / "simple_add_spec.json")
        with patch("agent.publish.AgentConfig", return_value=_mock_config()), \
             patch("agent.publish.generate_code", side_effect=_mock_generate_code(_SINGLE_ATOM_CODE)), \
             patch("agent.publish.MumeiClient") as MC:
            inst = _ok_client(MC)
            publish(
                spec_path=spec_path,
                repo_dir=str(tmp_path),
                output_dir="katana",
                dry_run=True,
            )

        # All build_with_emit calls should use the correct output dir
        for call_args in inst.build_with_emit.call_args_list:
            output_arg = call_args[0][2]
            assert output_arg.endswith("katana")
