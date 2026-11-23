"""Regenerate the pinned Rust analyzer LSIF envelopes in this directory."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote, urlparse

ENVELOPE_PROFILE = "mumei.rust-analyzer-lsif-envelope/v1"
RUST_ANALYZER_VERSION = "1.100.0 (0ef1bc3 2026-11-09)"
FIXTURE_NAMES = (
    "local_shadowing",
    "cross_file",
    "external_stdlib",
    "macro_usage",
    "build_script",
    "member_access",
)
TARGETS = {name: "src/main.rs" for name in FIXTURE_NAMES}


def _file_path(uri: str) -> Path:
    parsed = urlparse(uri)
    if parsed.scheme != "file" or parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("rust-analyzer emitted an unsupported file URI")
    return Path(unquote(parsed.path)).resolve()


def _rewrite_uri(uri: str, project_root: Path) -> str:
    path = _file_path(uri)
    try:
        relative = path.relative_to(project_root).as_posix()
    except ValueError:
        parts = path.parts
        marker = ("lib", "rustlib", "src", "rust")
        marker_start = next(
            (
                index
                for index in range(len(parts) - len(marker) + 1)
                if parts[index : index + len(marker)] == marker
            ),
            None,
        )
        if marker_start is None:
            raise ValueError("rust-analyzer emitted a URI outside the project and sysroot")
        relative = PurePosixPath(*parts[marker_start + len(marker) :]).as_posix()
        return "file:///sysroot" + (
            f"/{quote(relative, safe='/')}" if relative != "." else ""
        )
    return "file:///project" + (
        f"/{quote(relative, safe='/')}" if relative != "." else ""
    )


def _rewrite(value: object, project_root: Path) -> object:
    if type(value) is dict:
        return {key: _rewrite(item, project_root) for key, item in value.items()}
    if type(value) is list:
        return [_rewrite(item, project_root) for item in value]
    if type(value) is str and value.startswith("file://"):
        return _rewrite_uri(value, project_root)
    return value


def _document(path: str, project_root: Path) -> dict[str, str]:
    source_path = (project_root / path).resolve()
    source_path.relative_to(project_root)
    content_bytes = source_path.read_bytes()
    content = content_bytes.decode("utf-8")
    return {
        "path": path,
        "sha256": f"sha256:{hashlib.sha256(content_bytes).hexdigest()}",
        "content": content,
    }


def _capture(rust_analyzer: str, fixture_dir: Path, name: str) -> None:
    project_root = (fixture_dir / name).resolve()
    result = subprocess.run(
        [rust_analyzer, "lsif", str(project_root)],
        capture_output=True,
        check=True,
        text=True,
    )
    rows = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    if not rows or rows[0].get("label") != "metaData":
        raise ValueError("rust-analyzer LSIF metadata is not first")
    metadata = rows[0]
    tool_info = metadata.get("toolInfo")
    if (
        type(tool_info) is not dict
        or tool_info.get("version") != RUST_ANALYZER_VERSION
    ):
        raise ValueError("rust-analyzer LSIF version does not match the pinned version")
    original_root = _file_path(metadata["projectRoot"])
    if original_root != project_root:
        raise ValueError("rust-analyzer LSIF project root does not match the fixture")

    document_paths = {
        _rewrite_uri(row["uri"], project_root)
        for row in rows
        if row.get("type") == "vertex" and row.get("label") == "document"
        and row.get("uri", "").startswith("file://")
        and row["uri"].startswith(metadata["projectRoot"].rstrip("/") + "/")
    }
    paths = {
        unquote(urlparse(uri).path.removeprefix("/project/"))
        for uri in document_paths
    }
    paths.update({"Cargo.toml", "Cargo.lock", TARGETS[name]})
    if (project_root / "build.rs").is_file():
        paths.add("build.rs")
    documents = [_document(path, project_root) for path in sorted(paths)]
    envelope = {
        "profile": ENVELOPE_PROFILE,
        "rust_analyzer_version": RUST_ANALYZER_VERSION,
        "target": TARGETS[name],
        "documents": documents,
        "lsif": _rewrite(rows, project_root),
    }
    destination = fixture_dir / f"{name}.envelope.json"
    destination.write_text(
        json.dumps(envelope, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"captured {destination.name}")


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: regenerate.py /path/to/rust-analyzer")
    rust_analyzer = sys.argv[1]
    version = subprocess.run(
        [rust_analyzer, "--version"],
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()
    if version != f"rust-analyzer {RUST_ANALYZER_VERSION}":
        raise SystemExit("rust-analyzer version does not match the pinned version")
    fixture_dir = Path(__file__).resolve().parent
    for name in FIXTURE_NAMES:
        _capture(rust_analyzer, fixture_dir, name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
