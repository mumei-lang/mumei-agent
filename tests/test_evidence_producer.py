"""Tests for the C02 evidence-producer-check route."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest

from agent.evidence_producer import main_producer


def _evidence(provenance: dict | None = None, **overrides) -> str:
    record = {
        "schema_version": "mumei.verification-evidence/v1",
        "subject": {"id": "mumei_source", "kind": "mumei_source",
                    "sha256": "0" * 64},
        "specification": {"id": "source.postcondition",
                          "sha256": "0" * 64},
        "obligation_id": "source_postcondition:" + "0" * 64,
        "provenance": provenance
        if provenance is not None
        else {
            "adapter": {
                "id": "mumei-agent",
                "version": "0.1.0",
                "protocol_version": "1",
            },
            "tool": {"name": "mumei", "version": "0.9.2"},
            "configuration_fingerprint": "a" * 64,
        },
    }
    record.update(overrides)
    return json.dumps(record)


def _write(tmp_path: Path, name: str, content: str | bytes) -> str:
    path = tmp_path / name
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return str(path)


def _args(
    evidence: str,
    tool: str = "mumei",
    adapter: str = "mumei-agent",
    tool_version: str | None = None,
    adapter_version: str | None = None,
    output: str | None = None,
) -> Namespace:
    return Namespace(
        evidence=evidence,
        tool=tool,
        adapter=adapter,
        tool_version=tool_version,
        adapter_version=adapter_version,
        output=output,
    )


def test_identity_match(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    evidence = _write(tmp_path, "e.json", _evidence())
    assert main_producer(_args(evidence)) == 0
    descriptor = json.loads(capsys.readouterr().out)
    assert (
        descriptor["schema_version"]
        == "mumei.evidence-producer-identity/v1"
    )
    assert descriptor["identity"] == "match"
    assert descriptor["mismatched"] == []
    assert descriptor["tool_name"] == "mumei"
    assert descriptor["tool_version"] == "0.9.2"
    assert descriptor["adapter_id"] == "mumei-agent"
    assert descriptor["adapter_version"] == "0.1.0"
    assert "producer_authenticity" not in descriptor["checks_not_performed"]
    assert "claim_truth" in descriptor["checks_not_performed"]
    assert "file_identity" in descriptor["checks_not_performed"]


def test_utf16_document_is_static_error(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """A document that decodes under an encoding sniff is still a
    static error — the route binds UTF-8 bytes like the sibling
    evidence routes."""
    evidence = _write(
        tmp_path, "e.json", _evidence().encode("utf-16")
    )
    assert main_producer(_args(evidence)) == 1


def test_identity_match_with_version_pins(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    evidence = _write(tmp_path, "e.json", _evidence())
    assert (
        main_producer(
            _args(evidence, tool_version="0.9.2", adapter_version="0.1.0")
        )
        == 0
    )
    descriptor = json.loads(capsys.readouterr().out)
    assert descriptor["identity"] == "match"
    assert descriptor["mismatched"] == []


def test_identity_mismatch_names_fields(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    evidence = _write(tmp_path, "e.json", _evidence())
    assert (
        main_producer(_args(evidence, adapter="foreign-adapter")) == 0
    )
    descriptor = json.loads(capsys.readouterr().out)
    assert descriptor["identity"] == "mismatch"
    assert descriptor["mismatched"] == ["adapter.id"]


def test_identity_mismatch_version_pin(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """A version the expectation pins is compared, not skipped."""
    evidence = _write(tmp_path, "e.json", _evidence())
    assert (
        main_producer(_args(evidence, tool_version="9.9.9")) == 0
    )
    descriptor = json.loads(capsys.readouterr().out)
    assert descriptor["identity"] == "mismatch"
    assert descriptor["mismatched"] == ["tool.version"]


def test_missing_provenance_is_static_error(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    body = json.loads(_evidence())
    del body["provenance"]
    evidence = _write(tmp_path, "e.json", json.dumps(body))
    assert main_producer(_args(evidence)) == 1
    err = capsys.readouterr().err
    assert "provenance" in err


def test_malformed_provenance_is_static_error(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    evidence = _write(
        tmp_path,
        "e.json",
        _evidence(provenance={"tool": {"name": "mumei"}}),
    )
    assert main_producer(_args(evidence)) == 1


def test_foreign_schema_is_static_error(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    evidence = _write(
        tmp_path, "e.json", _evidence(schema_version="other/v9")
    )
    assert main_producer(_args(evidence)) == 1


def test_oversized_input_is_static_error(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    evidence = _write(
        tmp_path,
        "e.json",
        '{"schema_version": "mumei.verification-evidence/v1", "pad": '
        + "1" * 70_000
        + "}",
    )
    assert main_producer(_args(evidence)) == 1


def test_output_may_not_overwrite_declared_input(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    evidence = _write(tmp_path, "e.json", _evidence())
    assert main_producer(_args(evidence, output=evidence)) == 1
    # The declared input survives untouched.
    assert json.loads(Path(evidence).read_text())["schema_version"] == (
        "mumei.verification-evidence/v1"
    )


def test_mcp_tool_emits_descriptor(tmp_path: Path) -> None:
    import json as _json
    from agent import mcp_server

    evidence = _write(tmp_path, "e.json", _evidence())
    out = _json.loads(
        mcp_server.evidence_producer_check(
            evidence, "mumei", "mumei-agent"
        )
    )
    assert "identity" in out
    assert out["identity"]["identity"] == "match"


def test_mcp_tool_mismatch(tmp_path: Path) -> None:
    import json as _json
    from agent import mcp_server

    evidence = _write(tmp_path, "e.json", _evidence())
    out = _json.loads(
        mcp_server.evidence_producer_check(
            evidence, "mumei", "mumei-agent", tool_version="9.9.9"
        )
    )
    assert out["identity"]["identity"] == "mismatch"
    assert out["identity"]["mismatched"] == ["tool.version"]


def test_mcp_tool_validates_declared_args(tmp_path: Path) -> None:
    import json as _json
    from agent import mcp_server

    evidence = _write(tmp_path, "e.json", _evidence())
    fn = mcp_server.evidence_producer_check
    assert "error" in _json.loads(fn("", "mumei", "mumei-agent"))
    assert "error" in _json.loads(fn("a\nb", "mumei", "mumei-agent"))
    assert "error" in _json.loads(fn(evidence, "", "mumei-agent"))
    assert "error" in _json.loads(fn(evidence, "mumei", ""))
    assert "error" in _json.loads(fn(evidence, "mumei", "a\nb"))
    assert "error" in _json.loads(
        fn(evidence, "mumei", "mumei-agent", tool_version="a\nb")
    )


def test_mcp_tool_error_redacts_declared_path(tmp_path: Path) -> None:
    import json as _json
    from agent import mcp_server

    missing = tmp_path / "no-such-evidence.json"
    out = _json.loads(
        mcp_server.evidence_producer_check(
            str(missing), "mumei", "mumei-agent"
        )
    )
    assert "error" in out
    assert str(missing) not in out["error"]
    assert str(tmp_path) not in out["error"]
