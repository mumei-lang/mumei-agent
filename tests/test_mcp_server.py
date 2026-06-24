"""Unit tests for ``agent.mcp_server`` (P10).

Each MCP tool is exercised directly as a Python function — the FastMCP
transport is not booted.  External dependencies (``MumeiClient``,
``AgentConfig``, ``MumeiForge``) are patched so the suite stays
hermetic: no LLM calls, no mumei binary required.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from agent import mcp_server


def _payload(raw: str) -> dict:
    """Parse the JSON-encoded tool result."""
    assert isinstance(raw, str)
    return json.loads(raw)


# ---------------------------------------------------------------------------
# get_agent_status
# ---------------------------------------------------------------------------


class TestGetAgentStatus:
    def test_returns_expected_fields(self) -> None:
        result = _payload(mcp_server.get_agent_status())
        assert result["status"] == "ok"
        assert "model" in result
        assert "mumei_bin" in result
        assert "mcp-server" in result["subcommands"]
        assert set(result["mcp_tools"]) >= {
            "forge_task",
            "heal_file",
            "measure_std_health",
            "propose_forge_tasks",
            "list_forge_log",
            "get_agent_status",
            "get_spec_guide_summary",
            "get_spec_guidelines",
            "extract_spec_from_code",
            "validate_code",
            "verify_foreign_code",
            "validate_nl_spec",
            "validate_foreign_code",
            "validate_spec_to_code",
            "validate_code_to_spec",
            "scan_and_fix",
            "send_latent_message",
            "send_latent_message_batch",
            "async_send_latent_message",
            "run_nlae_pipeline",
        }
        assert "PREFER_MCP_GAPS" in result["feature_flags"]
        assert "ENABLE_LATENT_PROTOCOL" in result["feature_flags"]
        assert "ENABLE_CODE_TO_SPEC" in result["feature_flags"]

    def test_status_tools_match_registered_tools(self) -> None:
        result = _payload(mcp_server.get_agent_status())
        registered = set(mcp_server.mcp._tool_manager._tools)
        assert set(result["mcp_tools"]) == registered
        assert "extract_spec_from_code" in registered
        assert "get_spec_guide_summary" in registered
        assert "get_spec_guidelines" in registered
        assert "send_latent_message" in registered


# ---------------------------------------------------------------------------
# cross_validation MCP tools
# ---------------------------------------------------------------------------


class TestCrossValidationTools:
    def test_validate_nl_spec_returns_dataclass_payload(self) -> None:
        result = _payload(
            mcp_server.validate_nl_spec(
                "requires: x >= 0; ensures: result >= x",
                use_llm=False,
                run_mumei=False,
            )
        )

        assert result["status"] == "ok"
        assert result["success"] is True
        assert result["inferred_atoms"][0]["requires"] == "x >= 0"
        assert result["verification"] is None

    def test_validate_nl_spec_returns_fix_suggestions(self) -> None:
        result = _payload(
            mcp_server.validate_nl_spec(
                "requires: x > 0 && x < 0; ensures: result == x",
                use_llm=False,
                run_mumei=False,
            )
        )

        assert result["status"] == "ok"
        assert result["success"] is False
        assert result["fix_suggestions"]
        assert result["overconstraints"][0]["fix_suggestion"]

    def test_validate_nl_spec_multi_returns_cross_spec_conflicts(self) -> None:
        result = _payload(
            mcp_server.validate_nl_spec_multi(
                json.dumps(
                    [
                        "requires: true; ensures: result > 0",
                        "requires: true; ensures: result < 0",
                    ]
                ),
                use_llm=False,
            )
        )

        assert result["status"] == "ok"
        assert result["success"] is False
        assert result["cross_spec_conflicts"]

    def test_validate_foreign_code_returns_inferred_contracts(self) -> None:
        result = _payload(
            mcp_server.validate_foreign_code(
                "def add(a: int, b: int) -> int:\n    return a + b\n",
                "python",
                use_llm=False,
                run_mumei=False,
            )
        )

        assert result["status"] == "ok"
        assert result["success"] is True
        assert result["language"] == "python"
        assert result["inferred_atoms"][0]["name"] == "add"
        assert "trusted atom add" in result["mumei_source"]
        assert result["verification"] is None

    def test_validate_spec_to_code_returns_alignment_result(
        self, tmp_path: Path
    ) -> None:
        code_path = tmp_path / "calc.py"
        code_path.write_text(
            "def add(a: int, b: int) -> int:\n    return a + b\n",
            encoding="utf-8",
        )

        result = _payload(
            mcp_server.validate_spec_to_code(
                "requires: a >= 0; ensures: result >= a",
                str(code_path),
                language="python",
                use_llm=False,
                run_mumei=False,
            )
        )

        assert result["status"] == "ok"
        assert result["code_path"] == str(code_path)
        assert result["language"] == "python"
        assert result["spec_atoms"][0]["name"] == "nl_spec_contract"
        assert result["code_atoms"][0]["name"] == "add"
        assert "constraint_violations" in result
        assert "extra_behaviors" in result

    def test_validate_code_to_spec_returns_drift_result(self, tmp_path: Path) -> None:
        code_path = tmp_path / "calc.py"
        spec_path = tmp_path / "spec.txt"
        code_path.write_text(
            "def add(a: int, b: int) -> int:\n    return a + b\n",
            encoding="utf-8",
        )
        spec_path.write_text(
            "requires: a >= 0; ensures: result >= a",
            encoding="utf-8",
        )

        result = _payload(
            mcp_server.validate_code_to_spec(
                str(code_path),
                str(spec_path),
                language="python",
                use_llm=False,
                run_mumei=False,
            )
        )

        assert result["status"] == "ok"
        assert result["code_path"] == str(code_path)
        assert result["spec_path"] == str(spec_path)
        assert result["language"] == "python"
        assert result["spec_atoms"][0]["name"] == "nl_spec_contract"
        assert result["code_atoms"][0]["name"] == "add"


# ---------------------------------------------------------------------------
# get_spec_guidelines
# ---------------------------------------------------------------------------


class TestGetSpecGuidelines:
    def test_returns_agent_facing_spec_guide_summary(self) -> None:
        result = _payload(mcp_server.get_spec_guide_summary())
        assert result["status"] == "ok"
        assert "outside_decidable_fragment" in result["summary"]
        assert "Z3-stable specification fragment" in result["summary"]

    def test_returns_decidable_fragment_guidance(self) -> None:
        result = _payload(mcp_server.get_spec_guidelines())
        assert result["status"] == "ok"
        guidelines = result["guidelines"]
        assert guidelines["warning"]["code"] == "outside_decidable_fragment"
        assert any(
            item["name"] == "array_and_sequence_access"
            for item in guidelines["fragment_catalog"]
        )
        assert "P8-C metrics" in guidelines["metric_refresh"]["source"]


# ---------------------------------------------------------------------------
# forge_task
# ---------------------------------------------------------------------------


class TestForgeTask:
    def test_invalid_json_returns_error(self, tmp_path: Path) -> None:
        result = _payload(
            mcp_server.forge_task("{not json", str(tmp_path), dry_run=True)
        )
        assert result["status"] == "error"
        assert "valid JSON" in result["error"]

    def test_missing_repo_returns_error(self) -> None:
        result = _payload(
            mcp_server.forge_task('{"task_id":"x"}', "/no/such/path/exists")
        )
        assert result["status"] == "error"
        assert "does not exist" in result["error"]

    def test_dry_run_short_circuits(self, tmp_path: Path) -> None:
        result = _payload(
            mcp_server.forge_task(
                json.dumps(
                    {
                        "task_id": "demo",
                        "target_file": "std/demo.mm",
                        "atoms": [{"name": "demo"}],
                    }
                ),
                str(tmp_path),
                dry_run=True,
            )
        )
        assert result["task_id"] == "demo"
        assert result["status"] == "skipped"
        assert result["error"] == "dry-run"
        assert result["code_length"] == 0
        assert result["dry_run"] is True

    def test_real_run_calls_forge_one(self, tmp_path: Path) -> None:
        # Pretend the LLM is available and a fake MumeiForge produces a
        # successful ForgeResult.
        from agent.forge import ForgeResult

        target = tmp_path / "std" / "demo.mm"
        target.parent.mkdir(parents=True)
        target.write_text("// generated\n", encoding="utf-8")

        fake_result = ForgeResult(
            task_id="demo",
            status="success",
            attempts=1,
            target_file="std/demo.mm",
            atoms_added=["demo"],
        )

        fake_config = MagicMock()
        fake_config.mumei_bin = "mumei"
        fake_config.create_client.return_value = MagicMock()

        fake_forge = MagicMock()
        fake_forge.forge_one.return_value = fake_result

        with (
            patch("agent.config.AgentConfig", return_value=fake_config),
            patch("agent.forge.MumeiForge", return_value=fake_forge),
            patch("agent.mumei_client.MumeiClient"),
        ):
            result = _payload(
                mcp_server.forge_task(
                    json.dumps(
                        {
                            "task_id": "demo",
                            "target_file": "std/demo.mm",
                            "atoms": [{"name": "demo"}],
                        }
                    ),
                    str(tmp_path),
                    dry_run=False,
                )
            )

        assert result["status"] == "success"
        assert result["task_id"] == "demo"
        assert result["target_file"] == "std/demo.mm"
        assert result["code_length"] == len("// generated\n")
        fake_forge.forge_one.assert_called_once()


# ---------------------------------------------------------------------------
# heal_file
# ---------------------------------------------------------------------------


class TestHealFile:
    def test_empty_source_returns_error(self) -> None:
        result = _payload(mcp_server.heal_file("   "))
        assert result["status"] == "error"

    def test_calls_get_fix(self) -> None:
        fake_config = MagicMock()
        fake_config.mumei_bin = "mumei"
        fake_config.model = "gpt-4o"
        fake_config.strategy = "single"
        fake_config.create_client.return_value = MagicMock()

        fake_mumei = MagicMock()

        with (
            patch("agent.config.AgentConfig", return_value=fake_config),
            patch(
                "agent.mumei_client.create_mumei_client",
                return_value=fake_mumei,
            ) as mock_create_mumei,
            patch(
                "agent.strategies.fix_strategy.get_fix",
                return_value="atom fixed() ensures: true; body: 0;",
            ) as mock_fix,
        ):
            result = _payload(
                mcp_server.heal_file(
                    "atom broken() ensures: false; body: 0;",
                    error_report=json.dumps({"failure_type": "postcondition"}),
                )
            )

        mock_fix.assert_called_once()
        mock_create_mumei.assert_called_once_with("mumei")
        assert mock_fix.call_args.kwargs["mumei_client"] is fake_mumei
        assert result["status"] == "ok"
        assert result["success"] is True
        assert "atom fixed" in result["healed_code"]


# ---------------------------------------------------------------------------
# measure_std_health
# ---------------------------------------------------------------------------


class TestMeasureStdHealth:
    def test_missing_std_returns_error(self, tmp_path: Path) -> None:
        result = _payload(mcp_server.measure_std_health(str(tmp_path)))
        assert result["status"] == "error"
        assert "std directory not found" in result["error"]

    def test_calls_measure_health(self, tmp_path: Path) -> None:
        std = tmp_path / "std"
        std.mkdir()
        sentinel = {
            "total_files": 0,
            "verified_files": 0,
            "failed_files": 0,
            "total_atoms": 0,
            "verified_atoms": 0,
            "trusted_atoms": 0,
            "health_score": 0.0,
            "todo_count": 0,
            "details": [],
        }
        with patch(
            "agent.std_health.measure_health", return_value=sentinel
        ) as mock_measure:
            result = _payload(mcp_server.measure_std_health(str(tmp_path)))
        mock_measure.assert_called_once()
        assert result["status"] == "ok"
        assert result["health_score"] == 0.0


# ---------------------------------------------------------------------------
# propose_forge_tasks
# ---------------------------------------------------------------------------


class TestProposeForgeTasks:
    def test_invalid_max_returns_error(self, tmp_path: Path) -> None:
        std = tmp_path / "std"
        std.mkdir()
        result = _payload(
            mcp_server.propose_forge_tasks(str(tmp_path), max_proposals=0)
        )
        assert result["status"] == "error"

    def test_missing_std_returns_error(self, tmp_path: Path) -> None:
        result = _payload(mcp_server.propose_forge_tasks(str(tmp_path)))
        assert result["status"] == "error"

    def test_returns_proposals_and_specs(self, tmp_path: Path) -> None:
        std = tmp_path / "std"
        std.mkdir()
        result = _payload(
            mcp_server.propose_forge_tasks(str(tmp_path), max_proposals=2)
        )
        assert result["status"] == "ok"
        assert isinstance(result["proposals"], list)
        assert isinstance(result["specs"], list)
        # Empty std/ triggers at least the std/core.mm rule.
        assert any(p["name"] == "std/core.mm" for p in result["proposals"])


# ---------------------------------------------------------------------------
# list_forge_log
# ---------------------------------------------------------------------------


class TestListForgeLog:
    def test_missing_log_is_ok(self, tmp_path: Path) -> None:
        result = _payload(mcp_server.list_forge_log(str(tmp_path / "nope.json")))
        assert result["status"] == "ok"
        assert result["count"] == 0
        assert result["entries"] == []

    def test_reads_list_log(self, tmp_path: Path) -> None:
        log = tmp_path / "forge_log.json"
        entries = [
            {"task_id": "a", "status": "success"},
            {"task_id": "b", "status": "failed"},
        ]
        log.write_text(json.dumps(entries), encoding="utf-8")
        result = _payload(mcp_server.list_forge_log(str(log)))
        assert result["count"] == 2
        assert result["entries"][0]["task_id"] == "a"

    def test_reads_dict_log(self, tmp_path: Path) -> None:
        log = tmp_path / "forge_log.json"
        log.write_text(
            json.dumps({"entries": [{"task_id": "x", "status": "success"}]}),
            encoding="utf-8",
        )
        result = _payload(mcp_server.list_forge_log(str(log)))
        assert result["count"] == 1
        assert result["entries"][0]["task_id"] == "x"

    def test_invalid_json_returns_error(self, tmp_path: Path) -> None:
        log = tmp_path / "forge_log.json"
        log.write_text("not json", encoding="utf-8")
        result = _payload(mcp_server.list_forge_log(str(log)))
        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# scan_and_fix
# ---------------------------------------------------------------------------


class TestScanAndFix:
    def test_audits_with_auto_migrate_enabled(self, tmp_path: Path) -> None:
        from agent.audit import AuditResult

        source = tmp_path / "impl.py"
        source.write_text("def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")
        audit_result = AuditResult(
            success=True,
            source_file=str(source),
            language="python",
            spec_extracted=True,
            migration_hints=[],
            report="Audit passed",
        )

        with patch("agent.audit.AuditPipeline") as pipeline_cls:
            pipeline_cls.return_value.audit_file.return_value = audit_result
            result = mcp_server.scan_and_fix(
                str(source),
                "python",
                auto_heal=True,
                heal_output_dir=str(tmp_path / "healed"),
                domain_hint="finance",
            )

        assert result["audit"]["success"] is True
        assert result["spec_alignment"] is None
        assert result["conformance_verification"] is None
        assert result["audit_schema"] == [
            "spec_health_issues",
            "verification_violations",
            "cross_validation_gaps",
            "next_steps",
            "migration_hints",
            "healed_files",
            "heal_errors",
        ]
        assert result["contract_terms"]["verification_violations"].startswith(
            "existing-code bugs or unsafe paths"
        )
        assert result["contract_terms"] == {
            "spec_health_issues": "spec-only contradictions, overconstraints, vacuity, or ambiguity",
            "verification_violations": "existing-code bugs or unsafe paths found before .mm migration",
            "cross_validation_gaps": "spec/code mismatches or cross-spec drift discovered during audit",
            "next_steps": "human-review entrypoint for audit -> migrate-suggest -> heal",
            "migration_hints": "generated .mm skeleton advice from migrate-suggest or audit --auto-migrate",
            "healed_files": "generated .mm skeletons accepted or rewritten by the self-healing loop",
            "heal_errors": "per-skeleton self-healing failures and diagnostics",
            "contradiction_type": "stable spec contradiction classifier",
        }
        for key in result["audit_schema"]:
            assert key in result
            assert key in result["audit"]
        assert "human-review entrypoint" in result["contract_terms"]["next_steps"]
        pipeline_cls.assert_called_once_with(heal_output_dir=str(tmp_path / "healed"))
        pipeline_cls.return_value.audit_file.assert_called_once_with(
            str(source),
            "python",
            domain_hint="finance",
            auto_migrate=True,
            auto_heal=True,
        )

    def test_exposes_fixed_audit_keys_without_aliases(self, tmp_path: Path) -> None:
        from agent.audit import AuditResult

        source = tmp_path / "impl.py"
        source.write_text("def sub(a: int, b: int) -> int:\n    return a - b\n", encoding="utf-8")
        audit_result = AuditResult(
            success=False,
            source_file=str(source),
            language="python",
            spec_extracted=True,
            verification_violations=["balance can go negative"],
            next_steps=[
                {
                    "priority": "high",
                    "action": "migrate-suggest で.mm skeleton 生",
                    "command": "mumei-agent migrate-suggest --code-file <file>",
                }
            ],
            migration_hints=[{"function_name": "sub"}],
            healed_files=[str(tmp_path / "sub.mm")],
            heal_errors=[],
        )

        with patch("agent.audit.AuditPipeline") as pipeline_cls:
            pipeline_cls.return_value.audit_file.return_value = audit_result
            result = mcp_server.scan_and_fix(str(source), "python", auto_heal=True)

        assert result["verification_violations"] == ["balance can go negative"]
        assert result["migration_hints"] == [{"function_name": "sub"}]
        assert result["healed_files"] == [str(tmp_path / "sub.mm")]
        assert result["heal_errors"] == []
        assert result["next_steps"] == audit_result.next_steps
        assert "recommendations" not in result
        assert "actions" not in result
        assert "review_actions" not in result
        assert "human_review" not in result
        assert "repair_hints" not in result

    def test_runs_spec_alignment_when_spec_is_provided(self, tmp_path: Path) -> None:
        from agent.audit import AuditResult
        from agent.cross_validation import SpecCodeAlignmentResult

        source = tmp_path / "impl.py"
        source.write_text("def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")
        spec = tmp_path / "spec.txt"
        spec.write_text("requires: true; ensures: result == a + b", encoding="utf-8")
        audit_result = AuditResult(
            success=True,
            source_file=str(source),
            language="python",
            spec_extracted=True,
            report="Audit passed",
        )
        alignment_result = SpecCodeAlignmentResult(
            success=True,
            code_path=str(source),
            language="python",
            spec_atoms=[],
            code_atoms=[],
            missing_constraints=[],
            divergences=[],
            satisfiable=True,
            report="Aligned",
        )

        with (
            patch("agent.audit.AuditPipeline") as pipeline_cls,
            patch(
                "agent.cross_validation.validate_spec_to_code",
                return_value=alignment_result,
            ) as validate,
        ):
            pipeline_cls.return_value.audit_file.return_value = audit_result
            result = mcp_server.scan_and_fix(
                str(source),
                "python",
                spec=str(spec),
                output_format="human",
            )

        assert result["audit"]["source_file"] == str(source)
        assert result["spec_alignment"]["success"] is True
        assert result["spec_alignment"]["satisfiable"] is True
        assert result["conformance_verification"]["success"] is True
        assert result["conformance_verification"]["next_steps"] == []
        assert "### next_steps (V1-E-1)" in result["conformance_verification"]["report"]
        assert "scan_and_fix role split" in result["formatted_report"]
        assert "`audit`" in result["formatted_report"]
        assert "`spec_alignment`" in result["formatted_report"]
        assert "`conformance_verification`" in result["formatted_report"]
        assert result["formatted_report"].index("### next_steps (V1-E-1)") < result[
            "formatted_report"
        ].index("### Human review entrypoints")
        assert "recommendations" not in result["formatted_report"]
        assert "review_actions" not in result["formatted_report"]
        assert "human_review" not in result["formatted_report"]
        assert "recommendations" not in result["conformance_verification"]
        assert "review_actions" not in result["conformance_verification"]
        assert "human_review" not in result["conformance_verification"]
        validate.assert_called_once_with(
            "requires: true; ensures: result == a + b",
            str(source),
            language="python",
        )

    def test_verify_conformance_exposes_next_steps_without_aliases(self, tmp_path: Path) -> None:
        source = tmp_path / "impl.py"
        source.write_text("def identity(x: int) -> int:\n    return x\n", encoding="utf-8")

        result = mcp_server.verify_conformance(
            "requires: true;\nensures: result == x + 1;",
            str(source),
            language="python",
            use_llm=False,
            run_mumei=False,
        )

        assert result["status"] == "needs_review"
        assert result["unimplemented_conditions"]
        assert result["verification_violations"]
        assert result["cross_validation_gaps"]
        assert result["next_steps"]
        assert "human_review" not in result
        assert "recommendations" not in result
        assert "review_actions" not in result


# ---------------------------------------------------------------------------
# extract_spec_from_code
# ---------------------------------------------------------------------------


class TestExtractSpecFromCode:
    def test_missing_file_returns_error(self) -> None:
        result = _payload(mcp_server.extract_spec_from_code("/no/such/file.rs"))

        assert result["status"] == "error"
        assert "does not exist" in result["error"]

    def test_extracts_spec_with_mock_extractor(self, tmp_path: Path) -> None:
        source = tmp_path / "simple_add.rs"
        source.write_text(
            "pub fn simple_add(a: i64, b: i64) -> i64 { a + b }\n", encoding="utf-8"
        )

        fake_result = MagicMock()
        fake_result.success = True
        fake_result.natural_language_spec = (
            "simple_add returns a + b without side effects"
        )
        fake_result.forge_task_spec = {"task_id": "code-simple-add", "atoms": []}
        fake_result.detected_language = "rust"
        fake_result.warnings = []

        fake_config = MagicMock()
        fake_config.mumei_bin = "mumei"

        fake_extractor = MagicMock()
        fake_extractor.extract_from_file.return_value = fake_result

        with (
            patch("agent.config.AgentConfig", return_value=fake_config),
            patch(
                "agent.code_to_spec.CodeToSpecExtractor", return_value=fake_extractor
            ),
            patch("agent.mumei_client.create_mumei_client", return_value=MagicMock()),
        ):
            result = _payload(mcp_server.extract_spec_from_code(str(source)))

        assert result["status"] == "ok"
        assert result["detected_language"] == "rust"
        assert result["spec"]["task_id"] == "code-simple-add"

    def test_extracts_directory_with_merged_spec(self, tmp_path: Path) -> None:
        source_dir = tmp_path / "code"
        source_dir.mkdir()
        (source_dir / "simple_add.rs").write_text(
            "pub fn simple_add(a: i64, b: i64) -> i64 { a + b }\n",
            encoding="utf-8",
        )
        directory_payload = {
            "files": [
                {
                    "path": str(source_dir / "simple_add.rs"),
                    "relative_path": "simple_add.rs",
                    "natural_language_spec": "simple_add returns a + b",
                    "detected_language": "rust",
                    "spec": {"task_id": "code-simple-add", "atoms": []},
                    "warnings": [],
                }
            ],
            "merged_spec": {"task_id": "merged-code-spec", "atoms": []},
        }

        fake_config = MagicMock()
        fake_config.mumei_bin = "mumei"
        fake_config.max_retries = 2

        with (
            patch("agent.config.AgentConfig", return_value=fake_config),
            patch("agent.mumei_client.create_mumei_client", return_value=MagicMock()),
            patch(
                "agent.extract_spec.extract_spec_from_code_directory",
                return_value=directory_payload,
            ) as mock_extract_directory,
        ):
            result = _payload(mcp_server.extract_spec_from_code(str(source_dir)))

        assert result["status"] == "ok"
        assert result["files"][0]["relative_path"] == "simple_add.rs"
        assert result["merged_spec"]["task_id"] == "merged-code-spec"
        mock_extract_directory.assert_called_once()


# ---------------------------------------------------------------------------
# send_latent_message
# ---------------------------------------------------------------------------


class TestSendLatentMessage:
    def test_requires_feature_flag(self) -> None:
        result = _payload(mcp_server.send_latent_message('{"action":"generate"}'))
        assert result["status"] == "error"
        assert "ENABLE_LATENT_PROTOCOL" in result["error"]

    def test_invalid_json_returns_error(self, monkeypatch) -> None:
        monkeypatch.setenv("ENABLE_LATENT_PROTOCOL", "true")
        result = _payload(mcp_server.send_latent_message("{not json", verify=False))
        assert result["status"] == "error"
        assert "valid JSON" in result["error"]

    def test_encodes_when_enabled_without_verification(self, monkeypatch) -> None:
        monkeypatch.setenv("ENABLE_LATENT_PROTOCOL", "true")
        result = _payload(
            mcp_server.send_latent_message(
                json.dumps({"action": "generate"}),
                context=json.dumps({"domain": "arithmetic"}),
                verify=False,
            )
        )
        assert result["status"] == "ok"
        assert len(result["latent_vector"]) == 16
        assert result["decoded"]["decoded"] is True
        assert result["verification_result"] is None
        assert result["authentication_verified"] is True

    def test_batch_sends_messages_and_reports_item_errors(self, monkeypatch) -> None:
        monkeypatch.setenv("ENABLE_LATENT_PROTOCOL", "true")
        body = "\n".join(
            f"atom_{index}: requires x >= {index}; ensures result >= {index};"
            for index in range(120)
        )
        batch = [
            {
                "message": {
                    "action": "generate",
                    "target": "proof_block",
                    "body": body,
                },
                "context": {"domain": "stdlib"},
            },
            {
                "message": {
                    "action": "generate",
                    "target": "proof_block",
                    "body": body.replace(
                        "ensures result >= 119",
                        "ensures result >= 120",
                    ),
                },
                "context": {"domain": "stdlib"},
            },
            "bad item",
        ]

        result = _payload(
            mcp_server.send_latent_message_batch(json.dumps(batch), verify=False)
        )

        assert result["status"] == "ok"
        assert result["sent"] == 2
        assert result["failed"] == 1
        assert result["results"][1]["decoded"]["compression_mode"] == "zlib-delta"
        assert result["average_transfer_reduction_ratio"] >= 0.5

    def test_async_send_latent_message(self, monkeypatch) -> None:
        monkeypatch.setenv("ENABLE_LATENT_PROTOCOL", "true")

        result = _payload(
            asyncio.run(
                mcp_server.async_send_latent_message(
                    json.dumps({"action": "generate"}),
                    context=json.dumps({"domain": "arithmetic"}),
                    verify=False,
                )
            )
        )

        assert result["status"] == "ok"
        assert len(result["latent_vector"]) == 16
