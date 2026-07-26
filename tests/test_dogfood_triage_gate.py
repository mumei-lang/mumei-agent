"""Tests for the dogfood verdict aggregation / gate layer."""
from __future__ import annotations

import json
from pathlib import Path
import sys

from agent.audit import AUDIT_SCHEMA_KEYS
from agent.audit_models import AuditDirectoryResult, AuditResult
from agent.dogfood_triage import format_triage_markdown, triage_directory_result

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import dogfood_triage_gate  # noqa: E402


def _file_result(
    source_file: str,
    verdict: str,
    *,
    violations: list[str] | None = None,
    errors: list[str] | None = None,
    spec_health_issues: list[str] | None = None,
    spec_extracted: bool = True,
) -> AuditResult:
    return AuditResult(
        success=verdict == "verified",
        source_file=source_file,
        language="python",
        spec_extracted=spec_extracted,
        verification_status=verdict,
        verification_violations=violations or [],
        errors=errors or [],
        spec_health_issues=spec_health_issues or [],
        next_steps=[
            {
                "priority": "high",
                "action": "migrate-suggest で .mm スケルトンを生成",
                "command": "mumei-agent migrate-suggest --code-file <file>",
            }
        ]
        if verdict == "refuted"
        else [],
    )


def _directory_result(file_results: list[AuditResult]) -> AuditDirectoryResult:
    return AuditDirectoryResult(
        success=all(r.success for r in file_results),
        source_dir="/corpus",
        language="python",
        file_results=file_results,
        total_files=len(file_results),
        files_with_issues=sum(0 if r.success else 1 for r in file_results),
    )


def test_markdown_surfaces_only_refuted_files_through_next_steps() -> None:
    result = _directory_result(
        [
            _file_result(
                "/corpus/bug.py",
                "refuted",
                violations=["overflow on a + b"],
            ),
            _file_result("/corpus/ok.py", "verified"),
            _file_result(
                "/corpus/slow.py",
                "unverifiable",
                errors=["z3 timed out"],
            ),
        ]
    )
    report = triage_directory_result(result)
    markdown = format_triage_markdown(result, report)

    assert "| refuted (human review) | 1 |" in markdown
    assert "| verified | 1 |" in markdown
    assert "| unverifiable | 1 |" in markdown
    assert "| timeout | 1 |" in markdown
    assert "`/corpus/bug.py`" in markdown
    assert "violation: overflow on a + b" in markdown
    assert "next_step [high]" in markdown
    # unverifiable files stay folded into cause counts, out of human attention
    assert "/corpus/slow.py" not in markdown
    assert "/corpus/ok.py" not in markdown


def test_markdown_reports_clean_corpus() -> None:
    result = _directory_result([_file_result("/corpus/ok.py", "verified")])
    markdown = format_triage_markdown(result, triage_directory_result(result))
    assert "No `refuted` files" in markdown
    assert "unverifiable causes" not in markdown


def test_fixed_key_contract_is_echoed_without_additions() -> None:
    result = _directory_result([_file_result("/corpus/ok.py", "verified")])
    result.verification_status = "verified"
    payload = dogfood_triage_gate._fixed_keys(result)
    assert list(payload) == AUDIT_SCHEMA_KEYS
    assert payload["verification_status"] == "verified"


def test_gate_reports_and_fails_on_refuted(tmp_path, monkeypatch, capsys) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "bug.py").write_text("def f(x):\n    return x\n", encoding="utf-8")

    result = _directory_result(
        [
            _file_result(
                str(corpus / "bug.py"),
                "refuted",
                violations=["overflow on a + b"],
            )
        ]
    )
    monkeypatch.setattr(dogfood_triage_gate, "AuditPipeline", lambda **_: object())
    monkeypatch.setattr(dogfood_triage_gate, "_audit", lambda *_args, **_kwargs: result)

    json_output = tmp_path / "triage.json"
    markdown_output = tmp_path / "triage.md"
    summary = tmp_path / "step_summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

    exit_code = dogfood_triage_gate.main(
        [
            str(corpus),
            "--json-output",
            str(json_output),
            "--markdown-output",
            str(markdown_output),
            "--fail-on-refuted",
        ]
    )
    assert exit_code == 1

    payload = json.loads(json_output.read_text(encoding="utf-8"))
    assert payload["totals"]["human_review_count"] == 1
    assert payload["totals"]["verified_count"] == 0
    assert list(payload["directories"][0]["audit_contract"]) == AUDIT_SCHEMA_KEYS
    assert "refuted (human review)" in markdown_output.read_text(encoding="utf-8")
    assert "Dogfood triage" in summary.read_text(encoding="utf-8")
    assert "::warning::" in capsys.readouterr().out


def test_gate_passes_when_only_unverifiable(tmp_path, monkeypatch) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    result = _directory_result(
        [
            _file_result(
                str(corpus / "opaque.py"),
                "unverifiable",
                spec_extracted=False,
            )
        ]
    )
    monkeypatch.setattr(dogfood_triage_gate, "AuditPipeline", lambda **_: object())
    monkeypatch.setattr(dogfood_triage_gate, "_audit", lambda *_args, **_kwargs: result)

    json_output = tmp_path / "triage.json"
    assert (
        dogfood_triage_gate.main(
            [str(corpus), "--json-output", str(json_output), "--fail-on-refuted"]
        )
        == 0
    )
    payload = json.loads(json_output.read_text(encoding="utf-8"))
    assert payload["totals"]["unverifiable_counts"]["no_function_declarations"] == 1


def test_gate_skips_missing_paths(tmp_path) -> None:
    assert dogfood_triage_gate.main([str(tmp_path / "nope")]) == 0
