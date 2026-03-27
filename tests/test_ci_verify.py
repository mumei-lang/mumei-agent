"""Tests for the CI verification gate script."""
import sys
from pathlib import Path

# Import the module under test
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


class TestDiscoverMmFiles:
    """Test .mm file discovery."""

    def test_discovers_mm_files(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.mm").write_text("atom test() requires: true; ensures: true; body: 0;")
        (tmp_path / "lib.mm").write_text("atom lib() requires: true; ensures: true; body: 1;")
        (tmp_path / ".hidden").mkdir()
        (tmp_path / ".hidden" / "skip.mm").write_text("atom skip() requires: true; ensures: true; body: 2;")

        from ci_verify import discover_mm_files
        files = discover_mm_files(tmp_path)
        names = [f.name for f in files]
        assert "main.mm" in names
        assert "lib.mm" in names
        assert "skip.mm" not in names

    def test_empty_directory(self, tmp_path):
        from ci_verify import discover_mm_files
        files = discover_mm_files(tmp_path)
        assert files == []


class TestFormatMarkdownSummary:
    """Test markdown formatting."""

    def test_all_passed(self):
        from ci_verify import format_markdown_summary
        results = [
            {"file": "test.mm", "success": True, "report": {"status": "success"}, "stderr": ""},
        ]
        md = format_markdown_summary(results, [])
        assert "All 1 file(s) verified successfully" in md
        assert ":white_check_mark:" in md

    def test_with_failure(self):
        from ci_verify import format_markdown_summary
        results = [
            {
                "file": "bad.mm",
                "success": False,
                "report": {
                    "status": "failed",
                    "atom": "unsafe_div",
                    "failure_type": "division_by_zero",
                    "counterexample": {"a": "10", "b": "0"},
                    "suggestion": "Add requires: b != 0",
                },
                "stderr": "Verification failed\n",
            },
        ]
        md = format_markdown_summary(results, [])
        assert "1 of 1 file(s) failed" in md
        assert "division_by_zero" in md
        assert "Counterexample" in md
        assert "a=10, b=0" in md

    def test_with_proof_certs(self):
        from ci_verify import format_markdown_summary
        results = [{"file": "test.mm", "success": True, "report": {}, "stderr": ""}]
        certs = [Path("proof-certs/test.proof.json")]
        md = format_markdown_summary(results, certs)
        assert "Proof Certificates" in md
        assert "1 proof certificate(s)" in md
