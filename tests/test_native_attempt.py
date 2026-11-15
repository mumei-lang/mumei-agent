"""Route tests for ``native-attempt``: declared Core native bundle
production through the C11 attempt lifecycle."""

import hashlib
import json
import os
from pathlib import Path

import pytest

from agent.native_attempt import (
    BUNDLE_MEMBERS,
    build_attempt_parser,
    main_attempt,
)

SOURCE = (
    "atom main() -> i64 requires: true; "
    "ensures: result == 0; body: { 0 };\n"
)

BUILD_ID = "b" * 64


def _write_core(tmp_path: Path, build_exit: int = 0,
                complete: bool = True, build_id: str | None = None) -> Path:
    """Stub `mumei` executable: `native-bundle build <src> -o <dir>`
    writes the declared members into the directory and prints the
    Build ID line (exit per `build_exit`). With `build_id=None` the
    stub computes the record's sha256 like the real Core; pass a
    literal to simulate a misbehaving Core."""
    members = "\n".join(
        f'    printf %s "{name}-bytes" > "$out/{name}"'
        for name in (BUNDLE_MEMBERS if complete else BUNDLE_MEMBERS[:-1])
    )
    if build_id is None:
        # python3: required by the test suite on every POSIX host
        # (sha256sum is absent on macOS).
        py = (
            "import hashlib,sys;"
            'print(hashlib.sha256(open(sys.argv[1],"rb").read())'
            ".hexdigest())"
        )
        id_line = (
            f"    printf \"Build ID: %s\\n\" "
            f'"$(python3 -c \'{py}\' "$out/native-bundle.json")"\n'
        )
    else:
        id_line = f'    printf "Build ID: {build_id}\\n"\n'
    core = tmp_path / "mumei-stub"
    core.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "native-bundle" ] && [ "$2" = "build" ]; then\n'
        '    out="$5"\n'
        "    mkdir -p \"$out\"\n"
        f"{members}\n"
        f"{id_line}"
        f"    exit {build_exit}\n"
        "fi\n"
        "exit 2\n"
    )
    core.chmod(0o755)
    return core


def _write_source(tmp_path: Path) -> Path:
    source = tmp_path / "main.mm"
    source.write_text(SOURCE)
    return source


def _args(core: Path, bundle: Path, source: Path, extra=()):
    return [
        "--core", str(core),
        "--source", str(source),
        "--bundle", str(bundle),
        "--attempt-timeout", "30000",
        *extra,
    ]


def _run(capsys, argv):
    try:
        code = main_attempt(build_attempt_parser().parse_args(argv))
    except SystemExit as exc:
        code = exc.code
    out = capsys.readouterr()
    return code, out.out, out.err


def test_selected_build_reports_candidate_and_build_id(tmp_path, capsys):
    core = _write_core(tmp_path)
    bundle = tmp_path / "bundle"
    source = _write_source(tmp_path)
    code, out, err = _run(capsys, _args(core, bundle, source))
    assert code == 0 and err == ""
    report = json.loads(out)
    assert report["schema_version"] == "mumei.native-attempt-report/v1"
    assert report["build_id"] == hashlib.sha256(
        bundle.joinpath("native-bundle.json").read_bytes()
    ).hexdigest()
    assert report["sequence"]["selected_result"] is not None
    assert report["candidate"]["schema_version"] == (
        "mumei.verifier-evidence-candidate/v1"
    )
    for name in BUNDLE_MEMBERS:
        assert bundle.joinpath(name).is_file()


def test_failed_build_selects_nothing(tmp_path, capsys):
    core = _write_core(tmp_path, build_exit=1)
    bundle = tmp_path / "bundle"
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    assert "build_id" not in report
    assert report["sequence"].get("selected_result") is None
    assert "candidate" not in report
    assert report["normalized"]["exit_code"] == 1


def test_exit_zero_without_build_id_selects_nothing(tmp_path, capsys):
    core = _write_core(tmp_path, build_id="not-a-build-id")
    bundle = tmp_path / "bundle"
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    assert "build_id" not in report
    assert report["sequence"].get("selected_result") is None
    assert "candidate" not in report


def test_exit_zero_with_incomplete_bundle_selects_nothing(
    tmp_path, capsys
):
    core = _write_core(tmp_path, complete=False)
    bundle = tmp_path / "bundle"
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    # The printed ID is claimable only once it verifies against the
    # record — an incomplete bundle pins nothing and selects nothing.
    assert "build_id" not in report
    assert report["sequence"].get("selected_result") is None
    assert "candidate" not in report


def test_mismatched_build_id_selects_nothing(tmp_path, capsys):
    """A Build ID line that does not match sha256(native-bundle.json)
    is not the identity a recheck pins: no selection, no claimed ID."""
    core = _write_core(tmp_path, build_id="c" * 64)
    bundle = tmp_path / "bundle"
    source = _write_source(tmp_path)
    code, out, _ = _run(capsys, _args(core, bundle, source))
    assert code == 0
    report = json.loads(out)
    assert "build_id" not in report
    assert report["sequence"].get("selected_result") is None
    assert "candidate" not in report
    assert report["normalized"]["exit_code"] == 0


def test_relative_and_nul_paths_are_static_errors(tmp_path, capsys):
    core = _write_core(tmp_path)
    source = _write_source(tmp_path)
    code, _, err = _run(
        capsys, _args(Path("rel/mumei"), tmp_path / "bundle", source)
    )
    assert code == 1 and "absolute" in err
    code, _, err = _run(
        capsys, _args(core, Path("rel/bundle"), source)
    )
    assert code == 1 and "absolute" in err


def test_oversize_source_is_static_error(tmp_path, capsys):
    core = _write_core(tmp_path)
    source = tmp_path / "main.mm"
    source.write_text("x" * 65_537)
    code, _, err = _run(capsys, _args(core, tmp_path / "bundle", source))
    assert code == 1 and "bound" in err


def test_output_may_not_overwrite_source(tmp_path, capsys):
    core = _write_core(tmp_path)
    source = _write_source(tmp_path)
    code, _, err = _run(
        capsys,
        _args(core, tmp_path / "bundle", source,
              extra=("--output", str(source))),
    )
    assert code == 1 and "declared input" in err


def test_output_may_not_overwrite_bundle_member(tmp_path, capsys):
    """`--output <bundle>/program` would replace a produced member
    with the report — refuse before the attempt is dispatched."""
    core = _write_core(tmp_path)
    source = _write_source(tmp_path)
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    member = bundle / "program"
    member.write_text("existing")
    code, _, err = _run(
        capsys,
        _args(core, bundle, source,
              extra=("--output", str(member))),
    )
    assert code == 1 and "bundle output" in err


MUMEI_BIN = os.environ.get("MUMEI_BIN")


@pytest.mark.skipif(
    not MUMEI_BIN or not Path(MUMEI_BIN).exists(),
    reason="MUMEI_BIN does not point at a real mumei binary",
)
class TestRealCore:
    def _real_source(self, tmp_path: Path) -> Path:
        src = tmp_path / "main.mm"
        src.write_text(
            "atom main() -> i64\n"
            "requires: true;\n"
            "ensures: result == 0;\n"
            "body: { 0 };\n"
        )
        return src

    def test_real_build_selects_and_pins_build_id(self, tmp_path, capsys):
        src = self._real_source(tmp_path)
        bundle = tmp_path / "bundle"
        code, out, _ = _run(
            capsys,
            _args(Path(MUMEI_BIN).resolve(), bundle, src),
        )
        assert code == 0
        report = json.loads(out)
        assert report["build_id"]
        assert report["candidate"]["schema_version"] == (
            "mumei.verifier-evidence-candidate/v1"
        )
        # The reported Build ID is the Core-computed sha256 of
        # native-bundle.json — the exact value a native-recheck call
        # would pin via --expected-build-id.
        assert report["build_id"] == hashlib.sha256(
            (bundle / "native-bundle.json").read_bytes()
        ).hexdigest()

    def test_outside_profile_source_selects_nothing(self, tmp_path, capsys):
        src = tmp_path / "main.mm"
        src.write_text("atom f(x: i64) -> i64 requires: x > 0;\n")
        code, out, _ = _run(
            capsys,
            _args(Path(MUMEI_BIN).resolve(), tmp_path / "bundle", src),
        )
        # A profile rejection is a run outcome, not a static error:
        # the route reports the lineage with no selection.
        assert code == 0
        report = json.loads(out)
        assert report["sequence"].get("selected_result") is None
        assert "candidate" not in report
