"""Tests for per-file timeout supervision of dogfood corpus audits."""
from __future__ import annotations

import json
from pathlib import Path

from agent.audit_models import AuditDirectoryResult, AuditResult
from agent import dogfood_timeout
from agent.dogfood_timeout import (
    FileAuditTiming,
    audit_file_with_timeout,
    format_timing_markdown,
    source_risk_markers,
)
from agent.dogfood_triage import triage_directory_result


def _directory_result(file_results: list[AuditResult]) -> AuditDirectoryResult:
    return AuditDirectoryResult(
        success=all(result.success for result in file_results),
        source_dir="/corpus",
        language="mixed",
        file_results=file_results,
        total_files=len(file_results),
        files_with_issues=sum(0 if r.success else 1 for r in file_results),
    )


def test_large_function_is_detected(tmp_path: Path) -> None:
    body = "\n".join(f"    x{i} = {i}" for i in range(200))
    path = tmp_path / "big.py"
    path.write_text(f"def wide(x):\n{body}\n", encoding="utf-8")
    assert source_risk_markers(path) == ["large_function"]


def test_inline_assembly_is_detected(tmp_path: Path) -> None:
    path = tmp_path / "asm.sol"
    path.write_text(
        "contract A {\n"
        "  function f() internal pure {\n"
        "    assembly {\n      mstore(0, 1)\n    }\n"
        "  }\n}\n",
        encoding="utf-8",
    )
    assert source_risk_markers(path) == ["inline_assembly"]


def test_nested_generics_are_detected(tmp_path: Path) -> None:
    path = tmp_path / "generic.rs"
    path.write_text(
        "pub fn f<T>(v: Vec<Option<T>>) -> usize { v.len() }\n", encoding="utf-8"
    )
    assert source_risk_markers(path) == ["complex_generics"]


def test_repeated_declaration_site_generics_are_detected(tmp_path: Path) -> None:
    path = tmp_path / "impls.rs"
    path.write_text(
        "impl<T> Pointer for *const T {\n    fn as_usize(self) -> usize { 0 }\n}\n"
        "impl<T> Pointer for *mut T {\n    fn as_usize(self) -> usize { 0 }\n}\n",
        encoding="utf-8",
    )
    assert source_risk_markers(path) == ["complex_generics"]


def test_go_square_bracket_generics_are_detected(tmp_path: Path) -> None:
    """Go writes type parameters as `[T Ordered]`, not `<T>`."""
    path = tmp_path / "cmp.go"
    path.write_text(
        "func Less[T Ordered](x, y T) bool { return x < y }\n"
        "func Compare[T Ordered](x, y T) int { return 0 }\n",
        encoding="utf-8",
    )
    assert source_risk_markers(path) == ["complex_generics"]


def test_array_indexing_is_not_mistaken_for_go_generics(tmp_path: Path) -> None:
    path = tmp_path / "index.go"
    path.write_text(
        "func first(xs []int) int { return xs[0] }\n"
        "func second(xs []int) int { return xs[1] }\n",
        encoding="utf-8",
    )
    assert source_risk_markers(path) == []


def test_plain_source_has_no_markers(tmp_path: Path) -> None:
    path = tmp_path / "plain.py"
    path.write_text("def f(x):\n    return x + 1\n", encoding="utf-8")
    assert source_risk_markers(path) == []


def test_missing_file_has_no_markers(tmp_path: Path) -> None:
    assert source_risk_markers(tmp_path / "nope.rs") == []


def test_pinned_corpus_risk_shapes_match_the_manifest() -> None:
    """Every declared `risk_shape` must be one the detector actually reports."""
    corpus = Path(__file__).parent / "corpora" / "oss"
    manifest = json.loads((corpus / "MANIFEST.json").read_text(encoding="utf-8"))
    declared = {
        entry["path"]: entry["risk_shape"]
        for entry in manifest["entries"]
        if "risk_shape" in entry
    }
    assert declared, "the corpus should pin at least one risk shape"
    for relative_path, shape in declared.items():
        markers = source_risk_markers(corpus / relative_path)
        assert shape in markers, f"{relative_path} declares {shape} but reports {markers}"
    assert {"inline_assembly", "complex_generics"} <= set(declared.values())


def test_timeout_stays_inside_the_existing_verdict_vocabulary(tmp_path: Path) -> None:
    """An abandoned file is `unverifiable` with the existing `timeout` cause."""
    path = tmp_path / "slow.sol"
    path.write_text(
        "contract A {\n  function f() internal pure {\n"
        "    assembly {\n      mstore(0, 1)\n    }\n  }\n}\n",
        encoding="utf-8",
    )
    # A microscopic budget cannot outlive process spawn, so this exercises the
    # real supervision + kill path rather than a stubbed one.
    result, timing = audit_file_with_timeout(path, "solidity", 0.001)

    assert timing.timed_out is True
    assert timing.risk_markers == ["inline_assembly"]
    assert result.verification_status == "unverifiable"
    assert "timed out" in result.errors[0]
    assert "inline_assembly" in result.errors[0]

    report = triage_directory_result(_directory_result([result]))
    assert report.unverifiable_counts["timeout"] == 1
    assert report.human_review_count == 0
    assert report.verified_count == 0

    markdown = format_timing_markdown([timing], slow_threshold_s=0.0)
    assert "per-file audit cost" in markdown
    assert "`slow.sol`" in markdown
    assert "inline_assembly" in markdown


def test_unsupervised_audit_reports_elapsed_time(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "ok.py"
    path.write_text("def f(x):\n    return x\n", encoding="utf-8")
    expected = AuditResult(
        success=True,
        source_file=str(path),
        language="python",
        spec_extracted=True,
        verification_status="verified",
    )

    class _Pipeline:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def audit_file(self, *_args: object, **_kwargs: object) -> AuditResult:
            return expected

    monkeypatch.setattr(dogfood_timeout, "AuditPipeline", _Pipeline)
    result, timing = audit_file_with_timeout(path, "python", 0.0)
    assert result is expected
    assert timing.timed_out is False
    assert timing.elapsed_s >= 0.0


def test_timing_markdown_is_empty_when_nothing_is_slow(tmp_path: Path) -> None:
    timings = [FileAuditTiming(source_file=str(tmp_path / "a.py"), elapsed_s=0.2)]
    assert format_timing_markdown(timings, slow_threshold_s=10.0) == ""
