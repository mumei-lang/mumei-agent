from __future__ import annotations

import errno
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from agent import plan_history_log
from agent.plan_history_log import append_plan_history, read_plan_history
from agent.verification_planner import (
    AdapterDescriptor,
    AdapterRegistry,
    PlannerPolicy,
    RouteRequirements,
    RuntimeObservation,
    VerificationPlan,
)

PROFILE = "mumei.pure-i64-comparison/v1"
REQUEST = RouteRequirements(PROFILE, "deductive_proof", frozenset({"lia"}))


def _plan(adapter_id: str) -> VerificationPlan:
    registry = AdapterRegistry()
    registry.register(
        AdapterDescriptor(
            adapter_id,
            "1.0.0",
            frozenset({PROFILE}),
            frozenset({"deductive_proof"}),
            frozenset({"lia"}),
        )
    )
    return registry.plan(
        REQUEST,
        PlannerPolicy(),
        (RuntimeObservation(adapter_id, "available", "4.13.0"),),
    )


def _plans():
    return (_plan("adapter-a"), _plan("adapter-b"), _plan("adapter-c"))


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


def _json_plan(plan: VerificationPlan) -> dict:
    return json.loads(_canonical(plan.to_dict()))


def _seed(path: Path, plans=None) -> tuple[str, ...]:
    selected_plans = _plans() if plans is None else tuple(plans)
    return tuple(
        append_plan_history(str(path), plan) for plan in selected_plans
    )


def _lines(path: Path) -> list[bytes]:
    return path.read_bytes().splitlines(keepends=True)


def _rewrite_first(
    path: Path, mutate, *, recompute_digest: bool = False, prefix: bytes = b""
) -> None:
    lines = _lines(path)
    entry = json.loads(lines[0])
    mutate(entry)
    if recompute_digest:
        unsigned = {key: value for key, value in entry.items() if key != "digest"}
        entry["digest"] = hashlib.sha256(_canonical(unsigned)).hexdigest()
    lines[0] = prefix + _canonical(entry) + b"\n"
    path.write_bytes(b"".join(lines))


def test_round_trip_three_appends_and_expected_head(tmp_path):
    path = tmp_path / "history.jsonl"
    plans = _plans()

    digests = [append_plan_history(str(path), plan) for plan in plans]

    assert len({json.dumps(plan.to_dict(), sort_keys=True) for plan in plans}) == 3
    assert read_plan_history(str(path)) == tuple(_json_plan(plan) for plan in plans)
    entries = [json.loads(line) for line in _lines(path)]
    assert [entry["digest"] for entry in entries] == digests
    assert [entry["prev_digest"] for entry in entries] == [None, *digests[:-1]]
    assert read_plan_history(str(path), expected_head=digests[-1]) == tuple(
        _json_plan(plan) for plan in plans
    )


def test_missing_file_is_empty_but_cannot_match_an_expected_head(tmp_path):
    path = tmp_path / "missing.jsonl"

    assert read_plan_history(str(path)) == ()
    with pytest.raises(ValueError, match="head mismatch"):
        read_plan_history(str(path), expected_head="0" * 64)


def test_expected_head_shape_is_validated(tmp_path):
    path = tmp_path / "history.jsonl"
    with pytest.raises(ValueError, match="invalid expected"):
        read_plan_history(str(path), expected_head="ABC")


def test_plan_field_tamper_with_old_digest_is_rejected(tmp_path):
    path = tmp_path / "history.jsonl"
    _seed(path)
    _rewrite_first(
        path,
        lambda entry: entry["plan"]["request"].__setitem__(
            "profile", "sentinel-plan-history-content"
        ),
    )

    with pytest.raises(ValueError):
        read_plan_history(str(path))


def test_reordered_entries_are_rejected(tmp_path):
    path = tmp_path / "history.jsonl"
    _seed(path)
    lines = _lines(path)
    lines[0], lines[1] = lines[1], lines[0]
    path.write_bytes(b"".join(lines))

    with pytest.raises(ValueError):
        read_plan_history(str(path))


def test_middle_entry_deletion_is_rejected(tmp_path):
    path = tmp_path / "history.jsonl"
    _seed(path)
    lines = _lines(path)
    path.write_bytes(lines[0] + lines[2])

    with pytest.raises(ValueError):
        read_plan_history(str(path))


def test_tail_truncation_requires_a_pinned_expected_head(tmp_path):
    path = tmp_path / "history.jsonl"
    plans = _plans()
    digests = _seed(path, plans)
    path.write_bytes(b"".join(_lines(path)[:-1]))

    assert read_plan_history(str(path)) == tuple(
        _json_plan(plan) for plan in plans[:-1]
    )
    with pytest.raises(ValueError, match="head mismatch"):
        read_plan_history(str(path), expected_head=digests[-1])


def test_partial_final_line_is_rejected(tmp_path):
    path = tmp_path / "history.jsonl"
    _seed(path)
    path.write_bytes(path.read_bytes()[:-1])

    with pytest.raises(ValueError):
        read_plan_history(str(path))


def test_blank_line_is_rejected(tmp_path):
    path = tmp_path / "history.jsonl"
    _seed(path)
    path.write_bytes(path.read_bytes() + b"\n")

    with pytest.raises(ValueError):
        read_plan_history(str(path))


def test_non_utf8_entry_is_rejected(tmp_path):
    path = tmp_path / "history.jsonl"
    path.write_bytes(b"\xff\n")

    with pytest.raises(ValueError):
        read_plan_history(str(path))


def test_extra_entry_key_is_rejected(tmp_path):
    path = tmp_path / "history.jsonl"
    _seed(path)
    _rewrite_first(
        path,
        lambda entry: entry.__setitem__("extra", "not-allowed"),
        recompute_digest=True,
    )

    with pytest.raises(ValueError):
        read_plan_history(str(path))


def test_wrong_entry_schema_is_rejected(tmp_path):
    path = tmp_path / "history.jsonl"
    _seed(path)
    _rewrite_first(
        path,
        lambda entry: entry.__setitem__("schema_version", "other/v1"),
        recompute_digest=True,
    )

    with pytest.raises(ValueError):
        read_plan_history(str(path))


def test_wrong_plan_schema_is_rejected(tmp_path):
    path = tmp_path / "history.jsonl"
    _seed(path)
    _rewrite_first(
        path,
        lambda entry: entry["plan"].__setitem__("schema_version", "other/v1"),
        recompute_digest=True,
    )

    with pytest.raises(ValueError):
        read_plan_history(str(path))


def test_boolean_index_is_rejected(tmp_path):
    path = tmp_path / "history.jsonl"
    _seed(path)
    _rewrite_first(
        path,
        lambda entry: entry.__setitem__("index", True),
        recompute_digest=True,
    )

    with pytest.raises(ValueError):
        read_plan_history(str(path))


def test_previous_digest_chain_mismatch_is_rejected(tmp_path):
    path = tmp_path / "history.jsonl"
    _seed(path)
    lines = _lines(path)
    entry = json.loads(lines[1])
    entry["prev_digest"] = None
    unsigned = {key: value for key, value in entry.items() if key != "digest"}
    entry["digest"] = hashlib.sha256(_canonical(unsigned)).hexdigest()
    lines[1] = _canonical(entry) + b"\n"
    path.write_bytes(b"".join(lines))

    with pytest.raises(ValueError):
        read_plan_history(str(path))


def test_malformed_digest_is_rejected(tmp_path):
    path = tmp_path / "history.jsonl"
    _seed(path)
    _rewrite_first(
        path, lambda entry: entry.__setitem__("digest", "A" * 64)
    )

    with pytest.raises(ValueError):
        read_plan_history(str(path))


def test_noncanonical_whitespace_is_rejected(tmp_path):
    path = tmp_path / "history.jsonl"
    _seed(path)
    _rewrite_first(path, lambda entry: None, prefix=b" ")

    with pytest.raises(ValueError):
        read_plan_history(str(path))


def test_extremely_nested_plan_is_rejected_with_value_error(tmp_path):
    path = tmp_path / "history.jsonl"
    depth = 100_000
    nested = b"[" * depth + b"0" + b"]" * depth
    path.write_bytes(
        b'{"digest":"'
        + b"0" * 64
        + b'","index":0,"plan":{"deep":'
        + nested
        + b',"schema_version":"mumei.verification-plan/v1"},'
        + b'"prev_digest":null,"schema_version":"'
        + plan_history_log.ENTRY_SCHEMA.encode()
        + b'"}\n'
    )

    with pytest.raises(ValueError):
        read_plan_history(str(path))


def test_non_finite_json_constant_is_rejected_even_with_matching_digest(tmp_path):
    path = tmp_path / "history.jsonl"
    plan = _json_plan(_plan("adapter-nan"))
    plan["nonfinite"] = float("nan")
    unsigned = {
        "schema_version": plan_history_log.ENTRY_SCHEMA,
        "index": 0,
        "prev_digest": None,
        "plan": plan,
    }
    entry = {
        **unsigned,
        "digest": hashlib.sha256(_canonical(unsigned)).hexdigest(),
    }
    path.write_bytes(_canonical(entry) + b"\n")

    with pytest.raises(ValueError, match="invalid plan history log"):
        read_plan_history(str(path))


def test_corrupted_log_refuses_append_without_changing_file_bytes(tmp_path):
    path = tmp_path / "history.jsonl"
    path.write_bytes(b'{"sentinel-plan-history-content":')
    original = path.read_bytes()

    with pytest.raises(ValueError):
        append_plan_history(str(path), _plan("adapter-new"))

    assert path.read_bytes() == original


def test_failed_partial_append_rolls_back_to_validated_prefix(tmp_path, monkeypatch):
    path = tmp_path / "history.jsonl"
    append_plan_history(str(path), _plan("adapter-before-failure"))
    original = path.read_bytes()
    write = plan_history_log.os.write
    calls = 0

    def partial_then_fail(file_fd, data):
        nonlocal calls
        calls += 1
        if calls == 1:
            return write(file_fd, data[:7])
        raise OSError(errno.ENOSPC, "no space")

    with monkeypatch.context() as patch:
        patch.setattr(plan_history_log.os, "write", partial_then_fail)
        with pytest.raises(ValueError):
            append_plan_history(str(path), _plan("adapter-failing-append"))

    assert path.read_bytes() == original
    append_plan_history(str(path), _plan("adapter-after-failure"))
    assert len(read_plan_history(str(path))) == 2


def test_non_verification_plan_is_rejected(tmp_path):
    path = tmp_path / "history.jsonl"

    with pytest.raises(ValueError):
        append_plan_history(str(path), {"schema_version": "mumei.verification-plan/v1"})

    assert not path.exists()


def test_append_enforces_entry_and_log_size_caps(tmp_path, monkeypatch):
    path = tmp_path / "history.jsonl"
    monkeypatch.setattr(plan_history_log, "MAX_ENTRY_BYTES", 1)

    with pytest.raises(ValueError, match="entry exceeds"):
        append_plan_history(str(path), _plan("adapter-entry-limit"))

    monkeypatch.undo()
    first_digest = append_plan_history(str(path), _plan("adapter-first"))
    original = path.read_bytes()
    monkeypatch.setattr(plan_history_log, "MAX_LOG_BYTES", len(original) + 1)

    with pytest.raises(ValueError, match="log exceeds"):
        append_plan_history(str(path), _plan("adapter-second"))

    assert read_plan_history(str(path), expected_head=first_digest)
    assert path.read_bytes() == original


def test_read_enforces_log_and_entry_size_caps(tmp_path, monkeypatch):
    path = tmp_path / "history.jsonl"
    _seed(path, (_plan("adapter-size"),))
    raw = path.read_bytes()
    monkeypatch.setattr(plan_history_log, "MAX_LOG_BYTES", len(raw) - 1)

    with pytest.raises(ValueError, match="log exceeds"):
        read_plan_history(str(path))

    monkeypatch.setattr(plan_history_log, "MAX_LOG_BYTES", len(raw))
    monkeypatch.setattr(plan_history_log, "MAX_ENTRY_BYTES", len(raw) - 1)
    with pytest.raises(ValueError, match="entry exceeds"):
        read_plan_history(str(path))


def test_error_messages_do_not_include_path_or_log_content(tmp_path):
    path = tmp_path / "history.jsonl"
    sentinel = "sentinel-plan-history-content"
    path.write_text(sentinel, encoding="utf-8")

    with pytest.raises(ValueError) as error:
        read_plan_history(str(path))

    assert str(tmp_path) not in str(error.value)
    assert sentinel not in str(error.value)
    with pytest.raises(ValueError) as error:
        append_plan_history(str(path), _plan("adapter-error-message"))
    assert str(tmp_path) not in str(error.value)
    assert sentinel not in str(error.value)


def test_log_never_persists_environment_secrets(tmp_path, monkeypatch):
    path = tmp_path / "history.jsonl"
    sentinel = "sentinel-secret-plan-history"
    monkeypatch.setenv("LLM_API_KEY", sentinel)

    append_plan_history(str(path), _plan("adapter-secret-check"))

    assert sentinel.encode() not in path.read_bytes()


def test_two_threads_append_a_valid_shared_chain(tmp_path):
    path = tmp_path / "history.jsonl"
    groups = [
        tuple(_plan(f"adapter-{group}-{index}") for index in range(20))
        for group in ("a", "b")
    ]

    def append_group(plans):
        return [
            append_plan_history(str(path), plan)
            for plan in plans
        ]

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(append_group, group) for group in groups]
        returned_digests = [digest for future in futures for digest in future.result()]

    entries = [json.loads(line) for line in _lines(path)]
    assert len(entries) == 40
    assert set(returned_digests) == {entry["digest"] for entry in entries}
    assert [entry["index"] for entry in entries] == list(range(40))
    assert [entry["prev_digest"] for entry in entries] == [
        None,
        *[entry["digest"] for entry in entries[:-1]],
    ]
    assert len(read_plan_history(str(path))) == 40


def test_symlink_aliases_share_lock_for_concurrent_appends(tmp_path):
    real_path = tmp_path / "history.jsonl"
    alias_path = tmp_path / "alias.jsonl"
    append_plan_history(str(real_path), _plan("adapter-initial"))
    try:
        alias_path.symlink_to(real_path)
    except (NotImplementedError, OSError):
        pytest.skip("symlinks are unavailable")

    groups = [
        tuple(_plan(f"adapter-{group}-{index}") for index in range(20))
        for group in ("real", "alias")
    ]
    paths = (str(real_path), str(alias_path))
    start = Barrier(2)

    def append_group(path, plans):
        start.wait()
        return [
            append_plan_history(path, plan)
            for plan in plans
        ]

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(append_group, path, plans)
            for path, plans in zip(paths, groups)
        ]
        returned_digests = [digest for future in futures for digest in future.result()]

    entries = [json.loads(line) for line in _lines(real_path)]
    assert len(entries) == 41
    assert set(returned_digests) == {entry["digest"] for entry in entries[1:]}
    assert [entry["index"] for entry in entries] == list(range(41))
    assert [entry["prev_digest"] for entry in entries] == [
        None,
        *[entry["digest"] for entry in entries[:-1]],
    ]
    assert len(read_plan_history(str(alias_path))) == 41


def test_new_parent_directories_are_fsynced(tmp_path, monkeypatch):
    path = tmp_path / "a" / "b" / "history.jsonl"
    calls = []
    monkeypatch.setattr(
        plan_history_log, "_fsync_directory", lambda directory: calls.append(directory)
    )

    append_plan_history(str(path), _plan("adapter-new-directories"))

    assert set(calls) == {tmp_path, tmp_path / "a", tmp_path / "a" / "b"}


def test_empty_existing_log_directory_is_fsynced(tmp_path, monkeypatch):
    path = tmp_path / "history.jsonl"
    path.write_bytes(b"")
    calls = []
    monkeypatch.setattr(
        plan_history_log, "_fsync_directory", lambda directory: calls.append(directory)
    )

    append_plan_history(str(path), _plan("adapter-empty-log"))

    assert calls == [tmp_path]
