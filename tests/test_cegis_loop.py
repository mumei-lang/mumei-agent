from unittest.mock import MagicMock

from agent.config import AgentConfig
from agent.strategies.cegis_loop import (
    CEGISLoop,
    apply_invariant,
    escalate_to_lean,
    normalize_loop_line,
)


def test_apply_invariant():
    source = """atom count(n: i64)
requires: n >= 0;
ensures: result >= 0;
body: {
    let i = 0;
    while i < n invariant: i >= 0 {
        i = i + 1;
    }
};"""

    result = apply_invariant(source, "i >= 0 && i <= n", 6)

    assert "    while i < n\n    invariant: i >= 0 && i <= n" in result


def test_cegis_loop_convergence(tmp_path):
    source_file = tmp_path / "sample.mm"
    source_file.write_text("while i < n {\n    i = i + 1;\n}\n", encoding="utf-8")

    mumei = MagicMock()
    mumei.verify.side_effect = [
        {
            "success": False,
            "report": {"counterexample": {"i": -1}},
            "stdout": "",
            "stderr": "",
        },
        {"success": True, "report": {}, "stdout": "", "stderr": ""},
    ]
    config = AgentConfig(api_key="")
    cegis = CEGISLoop(config, mumei, max_iterations=3)
    cegis.generate_initial_invariant = MagicMock(return_value="i >= 0")
    cegis.refine_invariant = MagicMock(return_value="i >= 0 && i <= n")

    result = cegis.run(
        str(source_file),
        1,
        {"variables": ["i", "n"], "postcondition": "i == n"},
    )

    assert result.success
    assert result.final_invariant == "i >= 0 && i <= n"
    assert result.iterations == 2
    assert result.total_counterexamples == 1
    assert source_file.read_text(encoding="utf-8") == "while i < n {\n    i = i + 1;\n}\n"


def test_cegis_loop_escalates_after_max_iterations(tmp_path):
    source_file = tmp_path / "sample.mm"
    source_file.write_text("while i < n {\n    i = i + 1;\n}\n", encoding="utf-8")

    mumei = MagicMock()
    mumei.verify.return_value = {
        "success": False,
        "report": {"counterexample": {"i": 3}},
        "stdout": "",
        "stderr": "",
    }
    cegis = CEGISLoop(AgentConfig(api_key=""), mumei, max_iterations=2)
    cegis.generate_initial_invariant = MagicMock(return_value="i >= 0")
    cegis.refine_invariant = MagicMock(return_value="i >= 0")

    result = cegis.run(str(source_file), 1, {"variables": ["i"]})

    assert not result.success
    assert result.reason == "escalation_to_lean"
    assert result.iterations == 2
    assert result.total_counterexamples == 2


def test_escalate_to_lean_writes_bundle(tmp_path):
    source_file = tmp_path / "sample.mm"
    source_file.write_text("atom sample() body: 0;", encoding="utf-8")

    path = escalate_to_lean(
        str(source_file),
        {"line": 12, "context": {"variables": ["i"]}},
    )

    assert path.name == "sample.escalation-bundle.json"
    text = path.read_text(encoding="utf-8")
    assert '"loop_line": 12' in text
    assert "cegis_max_iterations_reached" in text


def test_normalize_loop_line_finds_nearest_loop():
    source = """atom count(n: i64)
body: {
    let i = 0;
    while i < n
    invariant: true
    {
        i = i + 1;
    }
};"""

    assert normalize_loop_line(source, 1) == 4
