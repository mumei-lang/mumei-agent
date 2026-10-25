from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent.context_files import load_context_files
from agent.harness_metrics import HarnessMetrics
from agent.metrics import Metrics
from agent.mumei_client import MumeiClient
from agent.proliferate_cache import _spec_cache_key
from agent import lean_bridge, proliferate
from agent.strategies import generate_strategy


def test_real_mumei_resolves_sibling_from_verify_dir(
    tmp_path: Path,
    mumei_bin: str,
) -> None:
    staging_root = tmp_path / "staged"
    dependency_path = staging_root / "std" / "math" / "sibling_lemma_probe.mm"
    dependency_path.parent.mkdir(parents=True)
    dependency_path.write_text(
        "atom identity(x: i64) -> i64\n"
        "    requires: true;\n"
        "    ensures: result == x;\n"
        "    body: x;\n",
        encoding="utf-8",
    )
    dependent_code = (
        'import "std/math/sibling_lemma_probe" as sibling;\n'
        "atom use_sibling(x: i64) -> i64\n"
        "    requires: true;\n"
        "    ensures: result == x;\n"
        "    body: sibling::identity(x);\n"
    )
    staged_source = staging_root / "dependent.mm"
    staged_source.write_text(dependent_code, encoding="utf-8")

    client = MumeiClient(mumei_bin)
    staged_result = client.verify(str(staged_source))
    assert staged_result["success"] is True, staged_result

    unstaged_root = tmp_path / "unstaged"
    unstaged_root.mkdir()
    unstaged_source = unstaged_root / "dependent.mm"
    unstaged_source.write_text(dependent_code, encoding="utf-8")
    unstaged_result = client.verify(str(unstaged_source))
    assert unstaged_result["success"] is False


def test_real_mumei_claims_exposes_g4_grade(
    tmp_path: Path,
    mumei_bin: str,
) -> None:
    source = tmp_path / "verified.mm"
    source.write_text(
        "atom identity(x: i64) -> i64\n"
        "    requires: true;\n"
        "    ensures: result == x;\n"
        "    body: x;\n",
        encoding="utf-8",
    )
    certificate = tmp_path / "verified.proof.json"
    client = MumeiClient(mumei_bin)
    verified = client.verify(
        str(source),
        extra_args=["--proof-cert", "--output", str(certificate)],
    )
    assert verified["success"] is True, verified
    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    claims = client.claims(str(source), str(certificate), claims_dir)
    assert claims["returncode"] == 0, claims
    claim_rows = claims["report"]["claims"]
    identity = next(row for row in claim_rows if row.get("atom") == "identity")
    assert identity["effective_grade"] == "G4"


def _spec(target: str, depends_on: list[str] | None = None) -> dict:
    return {
        "target_file": target,
        "module_name": target.rsplit("/", 1)[-1].removesuffix(".mm"),
        "depends_on": depends_on or [],
    }


def _forge_result(spec: dict, *, verified: bool = True) -> dict:
    return {
        "spec": spec,
        "verified": verified,
        "success": verified,
        "code": f"code for {spec['target_file']}",
    }


def _run_forge_batch(
    specs: list[dict],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_run,
    *,
    workers: int = 4,
) -> list[dict]:
    monkeypatch.setattr(proliferate, "_run_forge_generation", fake_run)
    monkeypatch.setattr(proliferate, "_collect_g4_lemmas", lambda *args: [])
    return proliferate._parallel_forge(
        specs,
        config=MagicMock(),
        mumei_client=MagicMock(),
        harness_metrics=MagicMock(),
        cache_path=tmp_path / "forge-cache.json",
        mumei_repo_dir=None,
        max_workers=workers,
    )


def test_scheduler_runs_independent_spec_while_dependency_is_running(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    specs = [
        _spec("std/a.mm"),
        _spec("std/b.mm", ["std/a.mm"]),
        _spec("std/c.mm"),
    ]
    a_started = threading.Event()
    c_started = threading.Event()
    a_finished = threading.Event()
    call_order: list[str] = []

    def fake_run(*, index: int, spec: dict, **kwargs):
        target = spec["target_file"]
        call_order.append(target)
        if target == "std/a.mm":
            a_started.set()
            assert c_started.wait(3)
            a_finished.set()
        elif target == "std/c.mm":
            assert a_started.wait(3)
            c_started.set()
        elif target == "std/b.mm":
            assert a_finished.is_set()
        return index, _forge_result(spec), Metrics()

    results = _run_forge_batch(specs, tmp_path, monkeypatch, fake_run, workers=2)
    assert call_order.index("std/c.mm") < call_order.index("std/b.mm")
    assert [result["spec"]["target_file"] for result in results] == [
        "std/a.mm",
        "std/b.mm",
        "std/c.mm",
    ]


def test_single_worker_uses_stable_topological_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    specs = [
        _spec("std/child.mm", ["std/root.mm"]),
        _spec("std/root.mm"),
        _spec("std/other.mm"),
    ]
    call_order: list[str] = []

    def fake_run(*, index: int, spec: dict, **kwargs):
        call_order.append(spec["target_file"])
        return index, _forge_result(spec), Metrics()

    _run_forge_batch(specs, tmp_path, monkeypatch, fake_run, workers=1)
    assert call_order == ["std/root.mm", "std/child.mm", "std/other.mm"]


def test_scheduler_orders_dependency_chain_and_diamond(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    specs = [
        _spec("std/a.mm"),
        _spec("std/b.mm", ["std/a.mm"]),
        _spec("std/c.mm", ["std/a.mm"]),
        _spec("std/d.mm", ["std/b.mm", "std/c.mm"]),
        _spec("std/e.mm", ["std/d.mm"]),
    ]
    completed: set[str] = set()
    call_order: list[str] = []

    def fake_run(*, index: int, spec: dict, **kwargs):
        target = spec["target_file"]
        for dependency in spec["depends_on"]:
            assert dependency in completed
        call_order.append(target)
        completed.add(target)
        return index, _forge_result(spec), Metrics()

    results = _run_forge_batch(specs, tmp_path, monkeypatch, fake_run, workers=1)
    assert call_order == [
        "std/a.mm",
        "std/b.mm",
        "std/c.mm",
        "std/d.mm",
        "std/e.mm",
    ]
    assert len(results) == len(specs)


def test_self_dependency_is_ignored(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    specs = [_spec("std/self.mm", ["std/self.mm"])]
    called: list[str] = []

    def fake_run(*, index: int, spec: dict, **kwargs):
        called.append(spec["target_file"])
        return index, _forge_result(spec), Metrics()

    result = _run_forge_batch(specs, tmp_path, monkeypatch, fake_run)
    assert called == ["std/self.mm"]
    assert result[0]["verified"] is True


@pytest.mark.parametrize(
    "specs",
    [
        [_spec("std/a.mm", ["std/b.mm"]), _spec("std/b.mm", ["std/a.mm"])],
        [
            _spec("std/a.mm", ["std/c.mm"]),
            _spec("std/b.mm", ["std/a.mm"]),
            _spec("std/c.mm", ["std/b.mm"]),
        ],
    ],
)
def test_cycles_fail_without_generation(
    specs: list[dict],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_run(**kwargs):
        pytest.fail("cyclic specs must not call the generator")

    results = _run_forge_batch(specs, tmp_path, monkeypatch, unexpected_run)
    assert all(result["reason"] == "dependency_cycle" for result in results)


def test_failed_dependency_skips_generation_and_records_retry_class(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    specs = [_spec("std/a.mm"), _spec("std/b.mm", ["std/a.mm"])]
    calls: list[str] = []
    metrics = MagicMock()

    def fake_run(*, index: int, spec: dict, **kwargs):
        calls.append(spec["target_file"])
        result = _forge_result(spec, verified=False)
        result["reason"] = "verification_failed"
        return index, result, Metrics()

    monkeypatch.setattr(proliferate, "_run_forge_generation", fake_run)
    monkeypatch.setattr(proliferate, "_collect_g4_lemmas", lambda *args: [])
    results = proliferate._parallel_forge(
        specs,
        config=MagicMock(),
        mumei_client=MagicMock(),
        harness_metrics=metrics,
        cache_path=tmp_path / "forge-cache.json",
        mumei_repo_dir=None,
        max_workers=1,
    )
    assert calls == ["std/a.mm"]
    assert results[1]["reason"] == "dependency_failed:std/a.mm"
    assert any(
        call.kwargs.get("retry_class") == "dependency_failed"
        for call in metrics.record_result.call_args_list
    )


def test_verified_dependencies_share_only_g4_claims(
    tmp_path: Path,
) -> None:
    verify_dir = tmp_path / "verify"
    verify_dir.mkdir()
    staged_file = verify_dir / "std" / "dependency.mm"
    staged_file.parent.mkdir()
    code = "atom good() ensures: true; body: {}"

    class ClaimsClient:
        def verify(self, path: str, extra_args: list[str]):
            Path(extra_args[-1]).write_text("{}", encoding="utf-8")
            return {"success": True}

        def claims(self, path: str, cert_path: str, out_dir: str):
            rows = [
                {"atom": "g4", "requires": "true", "ensures": "true", "effective_grade": "G4"},
                {"atom": "g5", "effective_grade": "G5"},
                {"atom": "g2", "effective_grade": "G2"},
                {"atom": "g0", "effective_grade": "G0"},
                {"atom": "trusted", "effective_grade": "trusted"},
            ]
            return {"returncode": 0, "report": {"claims": rows}}

    lemmas = proliferate._collect_g4_lemmas(
        ClaimsClient(), staged_file, "std/dependency.mm", code, verify_dir
    )
    assert lemmas == [
        {
            "atom": "g4",
            "requires": "true",
            "ensures": "true",
            "source": "std/dependency.mm",
        }
    ]


def test_claims_failure_shares_no_lemmas(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    verify_dir = tmp_path / "verify"
    verify_dir.mkdir()
    staged_file = verify_dir / "dependency.mm"

    class FailedClaimsClient:
        def verify(self, path: str, extra_args: list[str]):
            Path(extra_args[-1]).write_text("{}", encoding="utf-8")
            return {"success": True}

        def claims(self, path: str, cert_path: str, out_dir: str):
            return {"returncode": 1, "stderr": "claims failed"}

    with caplog.at_level(logging.WARNING):
        lemmas = proliferate._collect_g4_lemmas(
            FailedClaimsClient(),
            staged_file,
            "std/dependency.mm",
            "atom a() ensures: true; body: {}",
            verify_dir,
        )
    assert lemmas == []
    assert "claims failed" in caplog.text


def test_forge_prompt_contains_g4_lemma_section(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = _spec("std/dependent.mm", ["std/dependency.mm"])
    observed: dict = {}

    def fake_generate_code(**kwargs):
        observed.update(kwargs)
        return "module code", True

    monkeypatch.setattr(proliferate, "generate_code", fake_generate_code)
    monkeypatch.setattr(
        proliferate,
        "_cache_results",
        lambda *args, **kwargs: None,
    )
    config = MagicMock()
    config.create_client.return_value = MagicMock()
    client = MagicMock()
    proliferate._run_forge_generation(
        index=0,
        spec=spec,
        config=config,
        mumei_client=client,
        cache_path=tmp_path / "cache.json",
        mumei_repo_dir=tmp_path,
        verify_dir=tmp_path,
        dependency_lemmas=[
            {
                "atom": "identity",
                "requires": "true",
                "ensures": "result == x",
                "source": "std/dependency.mm",
            }
        ],
    )
    context = observed["spec"]["cross_file_context"]
    assert (
        "# Machine-verified (G4) atoms from `std/dependency.mm`, generated in "
        "this run. Import the module and call them; do NOT re-define."
    ) in context
    assert (
        "atom identity  requires: true  ensures: result == x" in context
    )


def test_forge_prompt_loads_dependency_and_import_preamble(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dependency_path = tmp_path / "std" / "core.mm"
    dependency_path.parent.mkdir()
    dependency_path.write_text(
        "atom core_sentinel() ensures: true; body: {}",
        encoding="utf-8",
    )
    spec = _spec("std/dependent.mm", ["std/core.mm"])
    spec["context_files"] = ["std/core.mm"]
    spec["import_preamble"] = 'import "std/core" as core;'
    captured: list[dict] = []
    monkeypatch.setattr(
        proliferate,
        "generate_code",
        lambda **kwargs: (captured.append(kwargs["spec"]) or "code", True),
    )
    proliferate._run_forge_generation(
        index=0,
        spec=spec,
        config=MagicMock(create_client=MagicMock(return_value=object())),
        mumei_client=MagicMock(),
        cache_path=tmp_path / "cache.json",
        mumei_repo_dir=tmp_path,
        verify_dir=tmp_path,
    )
    context = captured[0]["cross_file_context"]
    assert "core_sentinel" in context
    assert (
        "# Import these dependency modules with:\n"
        "```mumei\nimport \"std/core\" as core;\n```"
    ) in context
    assert "cross_file_context" not in spec


def test_claims_failure_does_not_prevent_dependent_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    specs = [_spec("std/root.mm"), _spec("std/child.mm", ["std/root.mm"])]
    calls: list[str] = []

    class FailedClaimsClient:
        def verify(self, path: str, extra_args: list[str]):
            Path(extra_args[-1]).write_text("{}", encoding="utf-8")
            return {"success": True}

        def claims(self, path: str, cert_path: str, out_dir: str):
            return {"returncode": 1, "stderr": "claims unavailable"}

    def fake_run(*, index: int, spec: dict, **kwargs):
        calls.append(spec["target_file"])
        result = _forge_result(spec)
        if spec["target_file"] == "std/root.mm":
            result["cache_hit"] = True
        return index, result, Metrics()

    monkeypatch.setattr(proliferate, "_run_forge_generation", fake_run)
    with caplog.at_level(logging.WARNING):
        results = proliferate._parallel_forge(
            specs,
            config=MagicMock(),
            mumei_client=FailedClaimsClient(),
            harness_metrics=MagicMock(),
            cache_path=tmp_path / "cache.json",
            mumei_repo_dir=None,
            max_workers=1,
        )
    assert calls == ["std/root.mm", "std/child.mm"]
    assert results[1]["verified"] is True
    assert "claims unavailable" in caplog.text


def test_no_context_keeps_original_spec_and_cache_entry_clean(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = _spec("std/alone.mm")
    captured: list[dict] = []

    def fake_generate_code(**kwargs):
        captured.append(kwargs["spec"])
        return "module code", True

    monkeypatch.setattr(proliferate, "generate_code", fake_generate_code)
    result_path = tmp_path / "cache.json"
    config = MagicMock()
    config.create_client.return_value = MagicMock()
    _index, result, _metrics = proliferate._run_forge_generation(
        index=0,
        spec=spec,
        config=config,
        mumei_client=MagicMock(),
        cache_path=result_path,
        mumei_repo_dir=tmp_path,
        verify_dir=tmp_path,
    )
    assert captured[0] is spec
    assert "cross_file_context" not in result["spec"]
    cached = json.loads(result_path.read_text(encoding="utf-8"))
    entry = next(iter(cached.values()))
    assert "cross_file_context" not in entry
    assert "cross_file_context" not in spec


def test_context_copy_does_not_leak_into_result_or_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "std").mkdir()
    (tmp_path / "std" / "core.mm").write_text(
        "atom context_atom() ensures: true; body: {}",
        encoding="utf-8",
    )
    spec = _spec("std/consumer.mm")
    spec["context_files"] = ["std/core.mm"]
    captured: list[dict] = []
    monkeypatch.setattr(
        proliferate,
        "generate_code",
        lambda **kwargs: (captured.append(kwargs["spec"]) or "code", True),
    )
    cache_path = tmp_path / "cache.json"
    config = MagicMock(create_client=MagicMock(return_value=object()))
    _index, result, _metrics = proliferate._run_forge_generation(
        index=0,
        spec=spec,
        config=config,
        mumei_client=MagicMock(),
        cache_path=cache_path,
        mumei_repo_dir=tmp_path,
        verify_dir=tmp_path,
    )
    assert "context_atom" in captured[0]["cross_file_context"]
    assert result["spec"] is spec
    assert "cross_file_context" not in result["spec"]
    entry = next(iter(json.loads(cache_path.read_text(encoding="utf-8")).values()))
    assert "cross_file_context" not in entry


def test_self_correction_verification_uses_staging_directory(
    tmp_path: Path,
) -> None:
    verify_dir = tmp_path / "verify"
    verify_dir.mkdir()
    verified_paths: list[Path] = []

    class VerifyingClient:
        def verify(self, source_path: str):
            verified_paths.append(Path(source_path))
            return {"success": True}

    proliferate._try_self_correction_for_forge_failure(
        spec_result={"spec": _spec("std/broken.mm")},
        code="candidate",
        config=MagicMock(),
        mumei_client=VerifyingClient(),
        cache_path=tmp_path / "cache.json",
        mumei_repo_dir=None,
        verify_dir=verify_dir,
    )
    assert len(verified_paths) == 1
    assert verified_paths[0].parent == verify_dir


def test_generator_verification_temps_use_verify_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verify_dir = tmp_path / "verify"
    verify_dir.mkdir()
    monkeypatch.setattr(
        generate_strategy,
        "complete_text",
        lambda *args: (
            "```mumei\natom identity(x: i64) -> i64\n"
            "    requires: true;\n    ensures: result == x;\n"
            "    body: x;\n```"
        ),
    )
    paths: list[Path] = []
    client = MagicMock()
    client.check.side_effect = lambda path: (
        paths.append(Path(path)) or {"success": True, "stderr": ""}
    )
    client.verify.side_effect = lambda path, **kwargs: (
        paths.append(Path(path)) or {"success": True, "report": {}, "stderr": ""}
    )
    generate_strategy.generate_code(
        object(),
        "model",
        _spec("std/temp.mm"),
        config_max_retries=0,
        mumei_client=client,
        verify_dir=verify_dir,
    )
    assert len(paths) == 1
    assert all(path.parent == verify_dir for path in paths)


def test_dependency_lemma_context_reaches_retry_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts: list[str] = []
    code = (
        "```mumei\natom identity(x: i64) -> i64\n"
        "    requires: true;\n    ensures: result == x;\n"
        "    body: x;\n```"
    )

    def fake_complete(_client, messages, _model, **kwargs):
        prompts.append(messages[-1]["content"])
        return code

    monkeypatch.setattr(generate_strategy, "complete_text", fake_complete)
    client = MagicMock()
    client.check.return_value = {
        "success": False,
        "stderr": "parse failure",
        "stdout": "",
    }
    context = (
        "# Machine-verified (G4) atoms from `std/core.mm`, generated in this run.\n"
        "atom identity  requires: true  ensures: result == x"
    )
    spec = _spec("std/temp.mm")
    spec["cross_file_context"] = context
    generate_strategy.generate_code(
        object(),
        "model",
        spec,
        config_max_retries=1,
        mumei_client=client,
        verify_dir=tmp_path,
    )
    assert len(prompts) == 2
    assert context in prompts[1]


def test_cache_hit_skips_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = _spec("std/cached.mm")
    cache_path = tmp_path / "cache.json"
    proliferate._cache_results(
        cache_path,
        spec,
        _forge_result(spec),
        mumei_repo_dir=None,
    )
    monkeypatch.setattr(
        proliferate,
        "generate_code",
        lambda **kwargs: pytest.fail("cache hit should skip generation"),
    )
    _index, result, _metrics = proliferate._run_forge_generation(
        index=0,
        spec=spec,
        config=MagicMock(),
        mumei_client=MagicMock(),
        cache_path=cache_path,
    )
    assert result["cache_hit"] is True
    assert result["code"] == _forge_result(spec)["code"]


def test_dependent_cache_key_tracks_dependency_code() -> None:
    spec = _spec("std/dependent.mm", ["std/dependency.mm"])
    first = _spec_cache_key(
        spec, None, in_batch_dependency_codes=[("std/dependency.mm", "one")]
    )
    second = _spec_cache_key(
        spec, None, in_batch_dependency_codes=[("std/dependency.mm", "two")]
    )
    assert first != second


def test_no_dependency_cache_key_is_byte_identical() -> None:
    spec = _spec("std/alone.mm")
    assert _spec_cache_key(spec, None) == _spec_cache_key(
        spec, None, in_batch_dependency_codes=[]
    )


def test_context_file_loading_skips_invalid_entries(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "first.mm").write_text("FIRST_DEPENDENCY", encoding="utf-8")
    (tmp_path / "second.mm").write_text("SECOND_DEPENDENCY", encoding="utf-8")
    outside = tmp_path.parent / "outside.mm"
    outside.write_text("OUTSIDE", encoding="utf-8")
    assert load_context_files([], tmp_path) == ""
    assert load_context_files("first.mm", tmp_path) == ""
    with caplog.at_level(logging.WARNING):
        loaded = load_context_files(
            ["first.mm", "missing.mm", "../outside.mm", "second.mm", 5],
            tmp_path,
        )
    assert "FIRST_DEPENDENCY" in loaded
    assert "SECOND_DEPENDENCY" in loaded
    assert loaded.index("FIRST_DEPENDENCY") < loaded.index("SECOND_DEPENDENCY")
    assert "OUTSIDE" not in loaded
    assert "missing" in caplog.text.lower()

    original_read_text = Path.read_text

    def unreadable(path: Path, *args, **kwargs):
        if path.name == "first.mm":
            raise PermissionError("denied")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", unreadable)
    with caplog.at_level(logging.WARNING):
        assert load_context_files(["first.mm"], tmp_path) == ""
    assert "denied" in caplog.text


def test_empty_cross_file_context_keeps_generator_prompt_identical(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts: list[list[dict[str, str]]] = []

    def fake_complete_text(_client, messages, _model):
        prompts.append(messages)
        return (
            "```mumei\n"
            "atom identity(x: i64) -> i64\n"
            "    requires: true;\n"
            "    ensures: result == x;\n"
            "    body: x;\n"
            "```"
        )

    monkeypatch.setattr(generate_strategy, "complete_text", fake_complete_text)
    spec = _spec("std/alone.mm")
    client = MagicMock()
    client.check.return_value = {"success": True, "stderr": ""}
    client.verify.return_value = {"success": True, "report": {}, "stderr": ""}
    generate_strategy.generate_code(
        object(),
        "model",
        spec,
        config_max_retries=0,
        mumei_client=client,
    )
    config = MagicMock()
    config.create_client.return_value = object()
    proliferate._run_forge_generation(
        index=0,
        spec=spec,
        config=config,
        mumei_client=client,
        cache_path=tmp_path / "cache.json",
        mumei_repo_dir=tmp_path,
        verify_dir=tmp_path,
    )
    assert len(prompts) == 2
    assert prompts[0] == prompts[1]


def test_group_builder_handles_roots_chains_merges_and_no_diff(
    tmp_path: Path,
) -> None:
    specs = [
        _spec("std/root_a.mm"),
        _spec("std/child.mm", ["std/root_a.mm"]),
        _spec("std/grandchild.mm", ["std/child.mm"]),
        _spec("std/root_b.mm"),
        _spec("std/join.mm", ["std/root_b.mm", "std/root_a.mm"]),
    ]
    results = [_forge_result(spec) for spec in specs]
    groups = proliferate._dependency_publish_groups(specs, results, tmp_path)
    assert groups == [[0, 1, 2, 3, 4]]

    no_diff_specs = [
        _spec("std/on_disk.mm"),
        _spec("std/dependent.mm", ["std/on_disk.mm"]),
    ]
    (tmp_path / "std").mkdir(exist_ok=True)
    (tmp_path / "std/on_disk.mm").write_text(
        "code for std/on_disk.mm", encoding="utf-8"
    )
    no_diff_results = [_forge_result(spec) for spec in no_diff_specs]
    assert proliferate._dependency_publish_groups(
        no_diff_specs, no_diff_results, tmp_path
    ) == []
    assert no_diff_results[0]["reason"] == "no_diff"


def _group_inputs(tmp_path: Path) -> tuple[list[dict], list[dict]]:
    specs = [
        _spec("std/root.mm"),
        _spec("std/child.mm", ["std/root.mm"]),
    ]
    return specs, [_forge_result(spec) for spec in specs]


def test_group_publish_writes_and_verifies_members_together(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    specs, results = _group_inputs(tmp_path)
    check_targets: list[str] = []

    def check(_client, _repo, path, code):
        check_targets.append(path.relative_to(tmp_path).as_posix())
        return {"all_passed": True, "broken_files": []}

    publish_mock = MagicMock(return_value={"success": True, "pr_url": "https://pr/1"})
    monkeypatch.setattr(proliferate, "check_blast_radius", check)
    monkeypatch.setattr(proliferate, "publish", publish_mock)
    grouped = proliferate._publish_dependency_group(
        [0, 1],
        specs=specs,
        forged_results=results,
        mumei_repo=tmp_path,
        proposals_by_target={},
        config=MagicMock(),
        effective_mumei_bin="mumei",
        mumei_client=MagicMock(),
        harness_metrics=HarnessMetrics(),
        health_before=None,
        dry_run=False,
        enable_lean_fallback=False,
    )
    assert check_targets == ["std/root.mm", "std/child.mm"]
    assert publish_mock.call_args.kwargs["extra_files"] == [
        ("std/child.mm", "code for std/child.mm")
    ]
    assert grouped[1]["published_with"] == "std/root.mm"
    assert grouped[0]["success"] is True
    assert grouped[1]["success"] is True


def test_group_rollback_marks_every_member_when_healing_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    specs, results = _group_inputs(tmp_path)
    original = tmp_path / "std" / "existing.mm"
    original.parent.mkdir(parents=True)
    original.write_text("original", encoding="utf-8")
    checks = iter(
        [
            {"all_passed": False, "broken_files": [{"file": str(original), "error": "broken"}]},
        ]
    )
    monkeypatch.setattr(
        proliferate,
        "check_blast_radius",
        lambda *args: next(checks),
    )
    monkeypatch.setattr(proliferate, "attempt_heal", lambda **kwargs: False)
    grouped = proliferate._publish_dependency_group(
        [0, 1],
        specs=specs,
        forged_results=results,
        mumei_repo=tmp_path,
        proposals_by_target={},
        config=MagicMock(),
        effective_mumei_bin="mumei",
        mumei_client=MagicMock(),
        harness_metrics=HarnessMetrics(),
        health_before=None,
        dry_run=False,
        enable_lean_fallback=False,
    )
    assert original.read_text(encoding="utf-8") == "original"
    assert not (tmp_path / "std" / "root.mm").exists()
    assert not (tmp_path / "std" / "child.mm").exists()
    assert all(
        result["reason"] == "blast_radius_heal_failed"
        for result in grouped.values()
    )


@pytest.mark.parametrize("publish_raises", [False, True])
def test_failed_root_publish_rolls_back_and_marks_dependents_not_published(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    publish_raises: bool,
) -> None:
    specs, results = _group_inputs(tmp_path)
    root = tmp_path / "std" / "root.mm"
    root.parent.mkdir(parents=True)
    root.write_text("original root", encoding="utf-8")

    monkeypatch.setattr(
        proliferate,
        "check_blast_radius",
        lambda *args: {"all_passed": True, "broken_files": []},
    )

    def fail_publish(**kwargs):
        if publish_raises:
            raise RuntimeError("publish failed")
        return {"success": False}

    monkeypatch.setattr(
        proliferate,
        "publish",
        fail_publish,
    )
    grouped = proliferate._publish_dependency_group(
        [0, 1],
        specs=specs,
        forged_results=results,
        mumei_repo=tmp_path,
        proposals_by_target={},
        config=MagicMock(),
        effective_mumei_bin="mumei",
        mumei_client=MagicMock(),
        harness_metrics=HarnessMetrics(),
        health_before=None,
        dry_run=False,
        enable_lean_fallback=False,
    )
    assert grouped[0]["success"] is False
    assert grouped[1]["reason"] == "dependency_not_published"
    assert root.read_text(encoding="utf-8") == "original root"
    assert not (tmp_path / "std" / "child.mm").exists()


def test_dry_run_group_reports_all_members_and_restores_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    specs, results = _group_inputs(tmp_path)
    monkeypatch.setattr(
        proliferate,
        "check_blast_radius",
        lambda *args: {"all_passed": True, "broken_files": []},
    )
    monkeypatch.setattr(
        proliferate,
        "publish",
        lambda **kwargs: pytest.fail("dry run must not publish"),
    )
    grouped = proliferate._publish_dependency_group(
        [0, 1],
        specs=specs,
        forged_results=results,
        mumei_repo=tmp_path,
        proposals_by_target={},
        config=MagicMock(),
        effective_mumei_bin="mumei",
        mumei_client=MagicMock(),
        harness_metrics=HarnessMetrics(),
        health_before=None,
        dry_run=True,
        enable_lean_fallback=False,
    )
    assert all(result["publish_group"] == ["std/root.mm", "std/child.mm"] for result in grouped.values())
    assert all(result["dry_run"] is True for result in grouped.values())
    assert not (tmp_path / "std" / "root.mm").exists()
    assert not (tmp_path / "std" / "child.mm").exists()


def _publish_fixture(tmp_path: Path):
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(
        json.dumps(
            {"name": "root", "module_name": "root", "target_file": "std/root.mm"}
        ),
        encoding="utf-8",
    )
    client = MagicMock()
    client.verify.return_value = {"success": True, "report": {}, "stderr": ""}
    client.build_with_emit.return_value = {
        "success": True,
        "stdout": "",
        "stderr": "",
    }
    config = SimpleNamespace(
        mumei_bin="mumei",
        model="test",
        max_retries=1,
        create_client=MagicMock(),
    )
    return spec_path, config, client


def test_publish_extra_files_are_written_verified_and_staged(
    tmp_path: Path,
) -> None:
    spec_path, config, client = _publish_fixture(tmp_path)
    git_calls: list[list[str]] = []
    from subprocess import CompletedProcess

    def git(args, cwd):
        git_calls.append(args)
        return CompletedProcess(args, 0, stdout="develop", stderr="")

    with patch("agent.publish.AgentConfig", return_value=config), \
         patch("agent.publish.create_mumei_client", return_value=client), \
         patch("agent.publish._git", side_effect=git):
        result = proliferate.publish(
            spec_path=str(spec_path),
            repo_dir=str(tmp_path),
            dry_run=False,
            pre_generated_code="root code",
            extra_files=[("std/child.mm", "child code")],
        )
    assert result["success"] is True
    assert (tmp_path / "std" / "child.mm").read_text(encoding="utf-8") == "child code"
    assert client.verify.call_count == 2
    assert ["add", "--", "std/root.mm", "std/child.mm"] in git_calls


def test_publish_extra_file_verification_failure_aborts(
    tmp_path: Path,
) -> None:
    spec_path, config, client = _publish_fixture(tmp_path)
    client.verify.side_effect = [
        {"success": True, "report": {}, "stderr": ""},
        {"success": False, "report": {}, "stderr": "extra failed"},
    ]
    with patch("agent.publish.AgentConfig", return_value=config), \
         patch("agent.publish.create_mumei_client", return_value=client), \
         patch("agent.publish._git") as git:
        result = proliferate.publish(
            spec_path=str(spec_path),
            repo_dir=str(tmp_path),
            dry_run=True,
            pre_generated_code="root code",
            extra_files=[("std/child.mm", "bad child")],
        )
    assert result["success"] is False
    assert result["failed_extra_file"] == "std/child.mm"
    client.build_with_emit.assert_not_called()
    git.assert_not_called()


def test_publish_none_extra_files_preserves_single_file_path(
    tmp_path: Path,
) -> None:
    spec_path, config, client = _publish_fixture(tmp_path)
    from subprocess import CompletedProcess

    git_calls: list[list[str]] = []

    def git(args, cwd):
        git_calls.append(args)
        return CompletedProcess(args, 0, stdout="develop", stderr="")

    with patch("agent.publish.AgentConfig", return_value=config), \
         patch("agent.publish.create_mumei_client", return_value=client), \
         patch("agent.publish._git", side_effect=git):
        result = proliferate.publish(
            spec_path=str(spec_path),
            repo_dir=str(tmp_path),
            dry_run=False,
            pre_generated_code="root code",
            extra_files=None,
        )
    assert result["success"] is True
    assert client.verify.call_count == 1
    assert "extra_file_verifications" not in result
    assert ["add", "--", "std/root.mm"] in git_calls


def test_root_blast_radius_sees_all_group_members_before_healing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    specs, results = _group_inputs(tmp_path)
    child = tmp_path / "std" / "child.mm"
    child.parent.mkdir(parents=True)
    child.write_text("old incompatible child", encoding="utf-8")
    healed: list[str] = []

    def check(_client, _repo, path, _code):
        if path.name == "root.mm" and child.read_text(encoding="utf-8") != (
            "code for std/child.mm"
        ):
            return {
                "all_passed": False,
                "broken_files": [{"file": str(child), "error": "incompatible"}],
            }
        return {"all_passed": True, "broken_files": []}

    monkeypatch.setattr(proliferate, "check_blast_radius", check)
    monkeypatch.setattr(
        proliferate,
        "attempt_heal",
        lambda **kwargs: healed.append(kwargs["broken_info"]["file"]) or False,
    )
    publish_mock = MagicMock(return_value={"success": True})
    monkeypatch.setattr(proliferate, "publish", publish_mock)

    grouped = proliferate._publish_dependency_group(
        [0, 1],
        specs=specs,
        forged_results=results,
        mumei_repo=tmp_path,
        proposals_by_target={},
        config=MagicMock(),
        effective_mumei_bin="mumei",
        mumei_client=MagicMock(),
        harness_metrics=HarnessMetrics(),
        health_before=None,
        dry_run=False,
        enable_lean_fallback=False,
    )

    assert healed == []
    publish_mock.assert_called_once()
    assert grouped[0]["success"] is True
    assert grouped[1]["success"] is True


def test_publish_groups_changed_nodes_through_unchanged_intermediate(
    tmp_path: Path,
) -> None:
    specs = [
        _spec("std/child.mm", ["std/intermediate.mm"]),
        _spec("std/intermediate.mm", ["std/root.mm"]),
        _spec("std/root.mm"),
    ]
    (tmp_path / "std").mkdir()
    (tmp_path / "std" / "intermediate.mm").write_text(
        "code for std/intermediate.mm",
        encoding="utf-8",
    )
    results = [_forge_result(spec) for spec in specs]

    assert proliferate._dependency_publish_groups(specs, results, tmp_path) == [
        [2, 0]
    ]
    assert results[1]["reason"] == "no_diff"


def test_changed_dependents_of_unchanged_root_remain_separate(
    tmp_path: Path,
) -> None:
    specs = [
        _spec("std/dependent_a.mm", ["std/root.mm"]),
        _spec("std/dependent_b.mm", ["std/root.mm"]),
        _spec("std/root.mm"),
    ]
    (tmp_path / "std").mkdir()
    (tmp_path / "std" / "root.mm").write_text(
        "code for std/root.mm",
        encoding="utf-8",
    )
    results = [_forge_result(spec) for spec in specs]

    assert proliferate._dependency_publish_groups(specs, results, tmp_path) == []


def test_parallel_forge_uses_cli_fallback_only_for_dependents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    specs = [
        _spec("std/root.mm"),
        _spec("std/child.mm", ["std/root.mm"]),
        _spec("std/independent.mm"),
    ]

    class RecordingClient:
        def __init__(self) -> None:
            self.verify_calls: list[str] = []

        def verify(self, path: str) -> None:
            self.verify_calls.append(path)

    mcp_client = RecordingClient()
    fallback_client = RecordingClient()
    mcp_client._fallback = fallback_client

    def fake_run(*, index: int, spec: dict, mumei_client, **kwargs):
        target = spec["target_file"]
        mumei_client.verify(f"generation:{target}")
        return index, _forge_result(spec), Metrics()

    monkeypatch.setattr(proliferate, "_run_forge_generation", fake_run)
    monkeypatch.setattr(proliferate, "_collect_g4_lemmas", lambda *args: [])

    proliferate._parallel_forge(
        specs,
        config=MagicMock(),
        mumei_client=mcp_client,
        harness_metrics=MagicMock(),
        cache_path=tmp_path / "cache.json",
        mumei_repo_dir=None,
        max_workers=3,
    )

    assert set(mcp_client.verify_calls) == {
        "generation:std/root.mm",
        "generation:std/independent.mm",
    }
    assert fallback_client.verify_calls == ["generation:std/child.mm"]


def test_transitive_dependency_code_changes_dependent_cache_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    specs = [
        _spec("std/a.mm"),
        _spec("std/b.mm", ["std/a.mm"]),
        _spec("std/c.mm", ["std/b.mm"]),
    ]
    dependency_lists: list[list[tuple[str, str]]] = []
    cache_keys: list[str] = []

    def run_batch(a_code: str) -> None:
        def fake_run(*, index: int, spec: dict, **kwargs):
            target = spec["target_file"]
            code = a_code if target == "std/a.mm" else f"code for {target}"
            if target == "std/c.mm":
                dependencies = kwargs["in_batch_dependency_codes"]
                dependency_lists.append(dependencies)
                cache_keys.append(
                    _spec_cache_key(spec, None, in_batch_dependency_codes=dependencies)
                )
            return index, {**_forge_result(spec), "code": code}, Metrics()

        monkeypatch.setattr(proliferate, "_run_forge_generation", fake_run)
        monkeypatch.setattr(proliferate, "_collect_g4_lemmas", lambda *args: [])
        proliferate._parallel_forge(
            specs,
            config=MagicMock(),
            mumei_client=MagicMock(),
            harness_metrics=MagicMock(),
            cache_path=tmp_path / "cache.json",
            mumei_repo_dir=None,
            max_workers=1,
        )

    run_batch("A first")
    run_batch("A changed")

    assert dependency_lists[0] == [
        ("std/b.mm", "code for std/b.mm"),
        ("std/a.mm", "A first"),
    ]
    assert dependency_lists[1] == [
        ("std/b.mm", "code for std/b.mm"),
        ("std/a.mm", "A changed"),
    ]
    assert cache_keys[0] != cache_keys[1]


@pytest.mark.parametrize("unsafe_kind", ["absolute", "traversal", "symlink"])
def test_group_publish_rejects_unsafe_targets_before_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unsafe_kind: str,
) -> None:
    root = tmp_path / "std" / "root.mm"
    std_dir = root.parent
    std_dir.mkdir(parents=True)
    outside_file: Path
    if unsafe_kind == "absolute":
        outside_file = tmp_path.parent / "outside-absolute.mm"
        unsafe_target = str(outside_file)
    elif unsafe_kind == "traversal":
        outside_file = tmp_path.parent / "outside-traversal.mm"
        unsafe_target = "../outside-traversal.mm"
    else:
        outside_dir = tmp_path.parent / "outside-symlink"
        outside_dir.mkdir()
        link = std_dir / "escaped"
        try:
            link.symlink_to(outside_dir, target_is_directory=True)
        except OSError as exc:
            pytest.skip(f"symlinks unavailable: {exc}")
        outside_file = outside_dir / "child.mm"
        unsafe_target = "std/escaped/child.mm"
    outside_file.write_text("outside sentinel", encoding="utf-8")
    specs = [
        _spec("std/root.mm"),
        _spec(unsafe_target, ["std/root.mm"]),
    ]
    results = [_forge_result(spec) for spec in specs]
    monkeypatch.setattr(
        proliferate,
        "check_blast_radius",
        lambda *args: pytest.fail("unsafe targets must be rejected before checks"),
    )
    monkeypatch.setattr(
        proliferate,
        "publish",
        lambda **kwargs: pytest.fail("unsafe targets must not be published"),
    )

    grouped = proliferate._publish_dependency_group(
        [0, 1],
        specs=specs,
        forged_results=results,
        mumei_repo=tmp_path,
        proposals_by_target={},
        config=MagicMock(),
        effective_mumei_bin="mumei",
        mumei_client=MagicMock(),
        harness_metrics=HarnessMetrics(),
        health_before=None,
        dry_run=False,
        enable_lean_fallback=False,
    )

    assert all(result["reason"] == "unsafe_target" for result in grouped.values())
    assert not root.exists()
    assert outside_file.read_text(encoding="utf-8") == "outside sentinel"


def test_group_publish_uses_each_dependent_certificate_for_lean_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    specs, results = _group_inputs(tmp_path)
    root_certificate = {
        "file": "std/root.mm",
        "atoms": [{"name": "root_unknown", "z3_check_result": "unknown"}],
    }
    child_certificate = {
        "file": "std/child.mm",
        "atoms": [{"name": "child_unknown", "z3_check_result": "unknown"}],
    }
    monkeypatch.setattr(
        proliferate,
        "check_blast_radius",
        lambda *args: {"all_passed": True, "broken_files": []},
    )
    monkeypatch.setattr(
        proliferate,
        "publish",
        lambda **kwargs: {
            "success": True,
            "proof_certificate": root_certificate,
            "extra_file_verifications": [
                {"file": "std/child.mm", "report": child_certificate}
            ],
        },
    )

    grouped = proliferate._publish_dependency_group(
        [0, 1],
        specs=specs,
        forged_results=results,
        mumei_repo=tmp_path,
        proposals_by_target={},
        config=MagicMock(),
        effective_mumei_bin="mumei",
        mumei_client=MagicMock(),
        harness_metrics=HarnessMetrics(),
        health_before=None,
        dry_run=False,
        enable_lean_fallback=True,
    )

    assert grouped[0]["publish_result"]["proof_certificate"] is root_certificate
    assert grouped[1]["publish_result"] is not grouped[0]["publish_result"]
    assert grouped[1]["publish_result"]["proof_certificate"] is child_certificate

    seen_atom_names: list[list[str]] = []

    def run_lean_bridge(**kwargs):
        certificate = json.loads(Path(kwargs["cert_path"]).read_text(encoding="utf-8"))
        seen_atom_names.append([atom["name"] for atom in certificate["atoms"]])
        return {"success": True, "returncode": 0, "lean_cert": None}

    monkeypatch.setattr(lean_bridge, "lean_fallback_available", lambda _repo: True)
    monkeypatch.setattr(lean_bridge, "run_lean_bridge", run_lean_bridge)
    proliferate._run_lean_fallback_inner(
        [grouped[0], grouped[1]],
        mumei_lean_repo="fake-lean-repo",
    )

    assert seen_atom_names == [["root_unknown"], ["child_unknown"]]
    assert grouped[1]["lean_fallback"]["unknown_count"] == 1


def test_dependent_publish_result_drops_root_certificate_when_report_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    specs, results = _group_inputs(tmp_path)
    root_certificate = {"atoms": [{"name": "root_unknown"}]}
    monkeypatch.setattr(
        proliferate,
        "check_blast_radius",
        lambda *args: {"all_passed": True, "broken_files": []},
    )
    monkeypatch.setattr(
        proliferate,
        "publish",
        lambda **kwargs: {
            "success": True,
            "proof_certificate": root_certificate,
            "certificate": root_certificate,
            "extra_file_verifications": [
                {"file": "std/child.mm", "report": None}
            ],
        },
    )

    grouped = proliferate._publish_dependency_group(
        [0, 1],
        specs=specs,
        forged_results=results,
        mumei_repo=tmp_path,
        proposals_by_target={},
        config=MagicMock(),
        effective_mumei_bin="mumei",
        mumei_client=MagicMock(),
        harness_metrics=HarnessMetrics(),
        health_before=None,
        dry_run=False,
        enable_lean_fallback=False,
    )

    assert grouped[0]["publish_result"]["proof_certificate"] is root_certificate
    assert "proof_certificate" not in grouped[1]["publish_result"]
    assert "certificate" not in grouped[1]["publish_result"]


def test_health_regression_closes_duplicate_pr_urls_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pr_url = "https://github.com/mumei-lang/mumei-agent/pull/627"
    results = [{"pr_url": pr_url}, {"pr_url": pr_url}]
    closed: list[tuple[str, float]] = []
    monkeypatch.setattr(
        proliferate,
        "_close_pr_for_regression",
        lambda url, delta: closed.append((url, delta)) or True,
    )

    proliferate._close_prs_for_regression(results, -0.25)

    assert closed == [(pr_url, -0.25)]
    assert all(result["pr_closed"] is True for result in results)
    assert all(result["should_close_pr"] is True for result in results)
