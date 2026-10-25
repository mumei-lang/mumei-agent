from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from agent.context_files import load_context_files
from agent.mumei_client import MumeiClient
from agent.proliferate import _run_forge_generation
from agent.propose_helpers import build_spec_from_proposal


def _recording_client(
    response_text: str,
) -> tuple[MagicMock, list[list[dict[str, Any]]]]:
    client = MagicMock()
    requests: list[list[dict[str, Any]]] = []

    def create(**kwargs: Any) -> SimpleNamespace:
        messages = kwargs["messages"]
        requests.append(messages)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content=response_text))
            ]
        )

    client.chat.completions.create.side_effect = create
    return client, requests


def _run_generation(
    *,
    spec: dict[str, Any],
    repo_dir: Path | None,
    cache_path: Path,
    llm_client: MagicMock,
) -> dict[str, Any]:
    mumei_client = MagicMock(spec=MumeiClient)
    mumei_client.verify.return_value = {
        "success": True,
        "report": {"status": "ok"},
        "stdout": "",
        "stderr": "",
    }
    config = SimpleNamespace(
        create_client=lambda: llm_client,
        model="fake-model",
        max_retries=0,
        enable_self_correction=False,
    )
    _index, result, _metrics = _run_forge_generation(
        index=1,
        spec=spec,
        config=config,  # type: ignore[arg-type]
        mumei_client=mumei_client,
        cache_path=cache_path,
        mumei_repo_dir=repo_dir,
    )
    return result


def _proposal_spec(depends_on: list[str] | None = None) -> dict[str, Any]:
    proposal: dict[str, Any] = {
        "name": "std/math/dependency_context_probe.mm",
    }
    if depends_on is not None:
        proposal["depends_on"] = depends_on
    return build_spec_from_proposal(proposal)


def _response_for_spec(spec: dict[str, Any]) -> str:
    atom_name = spec["atoms"][0]["name"]
    return (
        f"```mumei\n"
        f"atom {atom_name}(x: i64) requires: true; "
        "ensures: result >= 0 || result < 0; body: x;\n"
        "```"
    )


def test_proliferate_generation_includes_proposal_dependency_context(
    tmp_path: Path,
) -> None:
    repo_dir = tmp_path / "mumei"
    core_path = repo_dir / "std" / "core.mm"
    core_path.parent.mkdir(parents=True)
    core_path.write_text(
        "// DEPENDENCY_CONTEXT_SENTINEL\n"
        "atom core_dependency_context_probe(x: i64) "
        "requires: true; ensures: result == x; body: x;\n",
        encoding="utf-8",
    )
    spec = _proposal_spec(["std/core.mm"])
    llm_client, requests = _recording_client(_response_for_spec(spec))
    cache_path = tmp_path / "cache.json"

    result = _run_generation(
        spec=spec,
        repo_dir=repo_dir,
        cache_path=cache_path,
        llm_client=llm_client,
    )

    assert result["verified"] is True
    prompt = requests[0][1]["content"]
    assert "DEPENDENCY_CONTEXT_SENTINEL" in prompt
    assert "# Context file: `std/core.mm`" in prompt
    assert (
        '# Import these dependency modules with:\n'
        '```mumei\nimport "std/core" as core;\n```'
    ) in prompt
    assert spec is result["spec"]
    assert "cross_file_context" not in spec
    assert "cross_file_context" not in result["spec"]
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    assert len(cache) == 1
    assert "cross_file_context" not in next(iter(cache.values()))


def test_two_dependency_modules_are_rendered_in_order(tmp_path: Path) -> None:
    repo_dir = tmp_path / "mumei"
    std_dir = repo_dir / "std"
    std_dir.mkdir(parents=True)
    (std_dir / "first.mm").write_text(
        "atom first_dependency_marker() requires: true; ensures: true; body: 1;",
        encoding="utf-8",
    )
    (std_dir / "second.mm").write_text(
        "atom second_dependency_marker() requires: true; ensures: true; body: 2;",
        encoding="utf-8",
    )
    spec = _proposal_spec(["std/first.mm", "std/second.mm"])
    llm_client, requests = _recording_client(_response_for_spec(spec))

    _run_generation(
        spec=spec,
        repo_dir=repo_dir,
        cache_path=tmp_path / "cache.json",
        llm_client=llm_client,
    )

    prompt = requests[0][1]["content"]
    assert prompt.index("first_dependency_marker") < prompt.index(
        "second_dependency_marker"
    )


def test_missing_dependency_is_skipped_while_other_context_is_included(
    tmp_path: Path,
) -> None:
    repo_dir = tmp_path / "mumei"
    std_dir = repo_dir / "std"
    std_dir.mkdir(parents=True)
    (std_dir / "present.mm").write_text(
        "atom present_dependency_marker() "
        "requires: true; ensures: true; body: 3;",
        encoding="utf-8",
    )
    spec = _proposal_spec(["std/missing.mm", "std/present.mm"])
    llm_client, requests = _recording_client(_response_for_spec(spec))

    _run_generation(
        spec=spec,
        repo_dir=repo_dir,
        cache_path=tmp_path / "cache.json",
        llm_client=llm_client,
    )

    prompt = requests[0][1]["content"]
    assert "present_dependency_marker" in prompt
    assert "# Context file: `std/present.mm`" in prompt
    assert "# Context file: `std/missing.mm`" not in prompt


def test_traversal_dependency_is_excluded(tmp_path: Path, caplog: Any) -> None:
    repo_dir = tmp_path / "mumei"
    repo_dir.mkdir()
    outside = tmp_path / "outside.mm"
    outside.write_text("OUTSIDE_DEPENDENCY_SENTINEL", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="agent.context_files"):
        context = load_context_files(["../outside.mm"], repo_dir)

    assert context == ""
    assert "OUTSIDE_DEPENDENCY_SENTINEL" not in context
    assert "context_file escapes repo root: ../outside.mm" in caplog.text


def test_no_context_files_preserves_the_original_prompt(tmp_path: Path) -> None:
    repo_dir = tmp_path / "mumei"
    repo_dir.mkdir()
    spec = _proposal_spec()
    assert "context_files" not in spec

    client_with_repo, requests_with_repo = _recording_client(_response_for_spec(spec))
    client_without_repo, requests_without_repo = _recording_client(
        _response_for_spec(spec)
    )
    _run_generation(
        spec=spec,
        repo_dir=repo_dir,
        cache_path=tmp_path / "cache-with-repo.json",
        llm_client=client_with_repo,
    )
    _run_generation(
        spec=spec,
        repo_dir=None,
        cache_path=tmp_path / "cache-without-repo.json",
        llm_client=client_without_repo,
    )

    assert requests_with_repo[0][1]["content"] == requests_without_repo[0][1][
        "content"
    ]


def test_cache_hit_skips_generation_for_dependency_context(tmp_path: Path) -> None:
    repo_dir = tmp_path / "mumei"
    core_path = repo_dir / "std" / "core.mm"
    core_path.parent.mkdir(parents=True)
    core_path.write_text(
        "atom cache_dependency_marker() requires: true; ensures: true; body: 4;",
        encoding="utf-8",
    )
    spec = _proposal_spec(["std/core.mm"])
    llm_client, requests = _recording_client(_response_for_spec(spec))
    cache_path = tmp_path / "cache.json"

    first = _run_generation(
        spec=spec,
        repo_dir=repo_dir,
        cache_path=cache_path,
        llm_client=llm_client,
    )
    second = _run_generation(
        spec=spec,
        repo_dir=repo_dir,
        cache_path=cache_path,
        llm_client=llm_client,
    )

    assert first["verified"] is True
    assert second["cache_hit"] is True
    assert len(requests) == 1


def test_load_context_files_handles_empty_non_list_and_non_string_entries(
    tmp_path: Path,
) -> None:
    repo_dir = tmp_path / "mumei"
    std_dir = repo_dir / "std"
    std_dir.mkdir(parents=True)
    (std_dir / "usable.mm").write_text(
        "atom usable_context_marker() requires: true; ensures: true; body: 5;",
        encoding="utf-8",
    )

    assert load_context_files([], repo_dir) == ""
    assert load_context_files("std/usable.mm", repo_dir) == ""
    context = load_context_files([None, 42, "std/usable.mm"], repo_dir)
    assert "usable_context_marker" in context


def test_load_context_files_skips_unreadable_file(
    tmp_path: Path,
    monkeypatch: Any,
    caplog: Any,
) -> None:
    repo_dir = tmp_path / "mumei"
    std_dir = repo_dir / "std"
    std_dir.mkdir(parents=True)
    unreadable = std_dir / "unreadable.mm"
    unreadable.write_text("atom unreadable() body: 0;", encoding="utf-8")
    readable = std_dir / "readable.mm"
    readable.write_text(
        "atom readable_context_marker() requires: true; ensures: true; body: 6;",
        encoding="utf-8",
    )

    original_read_text = Path.read_text

    def read_text(path: Path, *args: Any, **kwargs: Any) -> str:
        if path == unreadable.resolve():
            raise PermissionError("permission denied")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)
    with caplog.at_level(logging.WARNING, logger="agent.context_files"):
        context = load_context_files(
            ["std/unreadable.mm", "std/readable.mm"], repo_dir
        )

    assert "unreadable_context_marker" not in context
    assert "readable_context_marker" in context
    assert (
        "Failed to read context_file std/unreadable.mm: permission denied"
        in caplog.text
    )
