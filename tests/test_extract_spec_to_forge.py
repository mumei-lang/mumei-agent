"""Tests for extract-spec → forge pipeline wiring."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from agent.extract_spec import build_parser, main


def _make_response(text: str) -> MagicMock:
    message = MagicMock()
    message.content = text
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def _mock_client(response_text: str) -> MagicMock:
    client = MagicMock()
    client.chat.completions.create.return_value = _make_response(response_text)
    return client


def test_extract_spec_forge_option_parses() -> None:
    args = build_parser().parse_args(
        [
            "--text",
            "絶対値関数。結果は常に非負。",
            "--domain",
            "math",
            "--output",
            "spec.json",
            "--forge",
            "--forge-dry-run",
        ]
    )

    assert args.forge is True
    assert args.forge_dry_run is True
    assert args.domain == "math"


def test_extract_spec_code_file_option_parses() -> None:
    args = build_parser().parse_args(
        [
            "--code-file",
            "tests/fixtures/code_samples/simple_add.rs",
            "--code-language",
            "rust",
            "--domain",
            "math",
            "--output",
            "spec.json",
        ]
    )

    assert args.code_file == "tests/fixtures/code_samples/simple_add.rs"
    assert args.code_language == "rust"
    assert args.domain == "math"


def test_extract_spec_code_directory_merges_file_specs(tmp_path: Path) -> None:
    source_dir = tmp_path / "code"
    (source_dir / "src").mkdir(parents=True)
    (source_dir / "src" / "simple_add.rs").write_text(
        "pub fn simple_add(a: i64, b: i64) -> i64 { a + b }\n",
        encoding="utf-8",
    )
    (source_dir / "lib.py").write_text(
        "def negate(x: int) -> int:\n    return -x\n",
        encoding="utf-8",
    )
    (source_dir / "README.md").write_text("not source code\n", encoding="utf-8")

    merged_spec = {
        "task_id": "merged-code-spec",
        "target_file": "std/math/merged.mm",
        "mode": "create",
        "atoms": [],
    }
    output_path = tmp_path / "merged.json"

    fake_config = MagicMock()
    fake_config.model = "test-model"
    fake_config.max_retries = 2
    fake_config.mumei_bin = "mumei"
    fake_config.create_client.return_value = _mock_client(json.dumps(merged_spec))

    fake_extractor = MagicMock()
    py_result = MagicMock()
    py_result.success = True
    py_result.natural_language_spec = "negate returns the additive inverse of x."
    py_result.forge_task_spec = {"task_id": "code-negate", "atoms": []}
    py_result.detected_language = "python"
    py_result.warnings = []
    py_result.errors = []
    rs_result = MagicMock()
    rs_result.success = True
    rs_result.natural_language_spec = "simple_add returns a + b."
    rs_result.forge_task_spec = {"task_id": "code-simple-add", "atoms": []}
    rs_result.detected_language = "rust"
    rs_result.warnings = []
    rs_result.errors = []
    fake_extractor.extract_from_file.side_effect = [py_result, rs_result]

    args = build_parser().parse_args(
        [
            "--code-file",
            str(source_dir),
            "--domain",
            "math",
            "--output",
            str(output_path),
        ]
    )

    with (
        patch("agent.extract_spec.AgentConfig", return_value=fake_config),
        patch("agent.extract_spec.create_mumei_client", return_value=MagicMock()),
        patch("agent.code_to_spec.CodeToSpecExtractor") as mock_extractor_class,
        patch("agent.extract_spec.extract_spec", return_value=merged_spec) as mock_merge,
    ):
        mock_extractor_class.EXTENSION_MAP = {".rs": "rust", ".py": "python"}
        mock_extractor_class.return_value = fake_extractor
        main(args)

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert [file["relative_path"] for file in payload["files"]] == [
        "lib.py",
        "src/simple_add.rs",
    ]
    assert payload["merged_spec"] == merged_spec
    assert fake_extractor.extract_from_file.call_count == 2
    merged_prompt = mock_merge.call_args.args[2]
    assert "lib.py" in merged_prompt
    assert "src/simple_add.rs" in merged_prompt
    assert "simple_add returns a + b" in merged_prompt


def test_extract_spec_to_forge_to_verify_with_mocks(tmp_path: Path) -> None:
    spec = {
        "task_id": "nl-abs-i64",
        "target_file": "std/math/abs_i64.mm",
        "mode": "create",
        "atoms": [
            {
                "name": "abs_i64",
                "description": "Absolute value for i64",
                "inputs": [{"name": "x", "type": "i64"}],
                "return_type": "i64",
                "requires": "x > i64::MIN",
                "ensures": "result >= 0",
                "effects": [],
            }
        ],
        "max_retries": 2,
        "auto_commit": False,
    }
    generated_code = "atom abs_i64(x: i64)\n    requires: x > i64::MIN;\n    ensures: result >= 0;\n    body: if x < 0 { -x } else { x };\n"
    output_path = tmp_path / "extracted.json"
    tasks_dir = tmp_path / "forge_tasks"
    mumei_repo = tmp_path / "mumei"
    (mumei_repo / "std" / "math").mkdir(parents=True)
    log_path = tmp_path / "forge_log.json"

    fake_config = MagicMock()
    fake_config.model = "test-model"
    fake_config.max_retries = 2
    fake_config.mumei_bin = "mumei"
    fake_config.create_client.return_value = _mock_client(json.dumps(spec))

    mumei_client = MagicMock()
    mumei_client.verify.return_value = {"success": True, "report": {}, "stdout": "", "stderr": ""}

    args = build_parser().parse_args(
        [
            "--text",
            "絶対値関数。負の入力は正に変換し、結果は常に非負。",
            "--domain",
            "math",
            "--output",
            str(output_path),
            "--forge",
            "--forge-tasks-dir",
            str(tasks_dir),
            "--mumei-repo",
            str(mumei_repo),
            "--forge-log-path",
            str(log_path),
        ]
    )

    with patch("agent.extract_spec.AgentConfig", return_value=fake_config), patch(
        "agent.extract_spec.create_mumei_client", return_value=mumei_client
    ), patch("agent.forge.generate_code", return_value=(generated_code, True)) as mock_generate:
        main(args)

    assert json.loads(output_path.read_text(encoding="utf-8")) == spec
    forge_spec_path = tasks_dir / "nl-abs-i64.json"
    assert json.loads(forge_spec_path.read_text(encoding="utf-8")) == spec

    target_path = mumei_repo / "std" / "math" / "abs_i64.mm"
    assert target_path.read_text(encoding="utf-8") == generated_code
    mumei_client.verify.assert_called_once_with(
        str(target_path),
        collect_decidable_metrics=True,
    )
    mock_generate.assert_called_once()
    assert mock_generate.call_args.kwargs["mumei_client"] is mumei_client

    forge_log = json.loads(log_path.read_text(encoding="utf-8"))
    assert forge_log["runs"][0]["task_id"] == "nl-abs-i64"
    assert forge_log["runs"][0]["status"] == "success"


def test_extract_spec_generate_and_forge_uses_raw_forge_spec(tmp_path: Path) -> None:
    spec = {
        "task_id": "nl-abs-i64",
        "target_file": "std/math/abs_i64.mm",
        "mode": "create",
        "atoms": [
            {
                "name": "abs_i64",
                "description": "Absolute value for i64",
                "inputs": [{"name": "x", "type": "i64"}],
                "return_type": "i64",
                "requires": "x > i64::MIN",
                "ensures": "result >= 0",
                "effects": [],
            }
        ],
    }
    normalized_spec = {
        "name": "abs_i64",
        "description": "Absolute value for i64",
        "params": [{"name": "x", "type": "i64"}],
        "return_type": "i64",
        "requires": "x > i64::MIN",
        "ensures": "result >= 0",
    }
    generated_code = "atom abs_i64(x: i64) -> i64 { if x < 0 { -x } else { x } }\n"
    forge_code = "atom abs_i64(x: i64)\n    ensures: result >= 0;\n    body: if x < 0 { -x } else { x };\n"
    output_path = tmp_path / "generated_spec.json"
    generate_output_path = tmp_path / "generated.mm"
    tasks_dir = tmp_path / "forge_tasks"
    mumei_repo = tmp_path / "mumei"
    (mumei_repo / "std" / "math").mkdir(parents=True)
    log_path = tmp_path / "forge_log.json"

    fake_config = MagicMock()
    fake_config.model = "test-model"
    fake_config.max_retries = 2
    fake_config.mumei_bin = "mumei"
    fake_config.create_client.return_value = _mock_client(json.dumps(spec))

    mumei_client = MagicMock()
    mumei_client.verify.return_value = {"success": True, "report": {}, "stdout": "", "stderr": ""}

    args = build_parser().parse_args(
        [
            "--text",
            "絶対値関数。負の入力は正に変換し、結果は常に非負。",
            "--domain",
            "math",
            "--output",
            str(output_path),
            "--generate",
            "--generate-output",
            str(generate_output_path),
            "--forge",
            "--forge-tasks-dir",
            str(tasks_dir),
            "--mumei-repo",
            str(mumei_repo),
            "--forge-log-path",
            str(log_path),
        ]
    )

    with patch("agent.extract_spec.AgentConfig", return_value=fake_config), patch(
        "agent.extract_spec.create_mumei_client", return_value=mumei_client
    ), patch(
        "agent.strategies.spec_refinement.run_refinement_loop",
        return_value=(generated_code, True, normalized_spec),
    ), patch("agent.forge.generate_code", return_value=(forge_code, True)):
        main(args)

    assert json.loads(output_path.read_text(encoding="utf-8")) == normalized_spec
    assert generate_output_path.read_text(encoding="utf-8") == generated_code
    forge_spec_path = tasks_dir / "nl-abs-i64.json"
    assert json.loads(forge_spec_path.read_text(encoding="utf-8")) == spec
    assert (mumei_repo / "std" / "math" / "abs_i64.mm").read_text(encoding="utf-8") == forge_code
    forge_log = json.loads(log_path.read_text(encoding="utf-8"))
    assert forge_log["runs"][0]["status"] == "success"
