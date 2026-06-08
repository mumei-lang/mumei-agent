from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from agent import proliferate


class ConvergedSelfCorrection:
    converged = True

    def to_dict(self) -> dict[str, object]:
        return {
            "converged": True,
            "repair_attempts": 1,
            "self_correction_metadata": {"converged": True},
        }


def test_forge_failure_runs_structured_feedback_self_correction(tmp_path: Path) -> None:
    cache_path = tmp_path / "forge-cache.json"
    spec = {"target_file": "std/vault.mm"}
    broken_code = "atom vault(x: i64) ensures: result > 0; body: 0;\n"
    fixed_code = "atom vault(x: i64) ensures: result > 0; body: 1;\n"
    config = SimpleNamespace(
        enable_self_correction=True,
        max_retries=1,
        model="model",
        create_client=lambda: MagicMock(),
    )
    mumei_client = MagicMock()
    mumei_client.verify.side_effect = [
        {
            "success": False,
            "report": {
                "structured_feedback": {
                    "status": "verification_failed",
                    "reconstruction_loss": {"is_zero_loss": False},
                }
            },
            "stdout": "",
            "stderr": "verification failed",
        },
        {"success": True, "report": {"status": "ok"}, "stdout": "", "stderr": ""},
    ]

    def fake_self_correction(source_path: str, **_kwargs: object) -> ConvergedSelfCorrection:
        Path(source_path).write_text(fixed_code, encoding="utf-8")
        return ConvergedSelfCorrection()

    with patch("agent.proliferate.generate_code", return_value=(broken_code, False)), patch(
        "agent.self_correction.run_self_correction_loop",
        side_effect=fake_self_correction,
    ) as sc_mock:
        _idx, result, _metrics = proliferate._run_forge_generation(
            index=1,
            spec=spec,
            config=config,  # type: ignore[arg-type]
            mumei_client=mumei_client,
            cache_path=cache_path,
            mumei_repo_dir=tmp_path,
        )

    assert result["verified"] is True
    assert result["code"] == fixed_code
    assert result["self_correction"]["converged"] is True
    assert result["self_correction_reverify"]["success"] is True
    assert mumei_client.verify.call_count == 2
    sc_mock.assert_called_once()
