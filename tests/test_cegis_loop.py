from unittest.mock import MagicMock, patch

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
    while i < n
    {
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


def test_escalate_to_lean_bundle_v2_adds_contract_and_history(tmp_path):
    import json

    from agent.strategies.cegis_loop_helpers import (
        ESCALATION_BUNDLE_SCHEMA_VERSION,
        InvariantCandidate,
    )

    source_file = tmp_path / "sample.mm"
    source_file.write_text("atom sample() body: 0;", encoding="utf-8")

    path = escalate_to_lean(
        str(source_file),
        {"line": 12, "context": {"variables": ["i"]}},
        atom={
            "name": "sample",
            "requires": "n >= 0",
            "ensures": "result >= 0",
            "body": "let i = 0; while i < n { i = i + 1; }",
            "z3_check_result": "unknown",
            "irrelevant": "dropped",
        },
        counterexamples=[{"i": 3}, {"i": 5}],
        invariant_candidates=[
            InvariantCandidate("i >= 0", "llm", 1, [{"i": 3}]),
            InvariantCandidate("i <= n", "refine", 2, [{"i": 5}]),
        ],
    )

    bundle = json.loads(path.read_text(encoding="utf-8"))
    # Existing v1 keys are unchanged.
    assert bundle["source_file"] == str(source_file)
    assert bundle["loop_line"] == 12
    assert bundle["loop_context"] == {"variables": ["i"]}
    assert bundle["reason"] == "cegis_max_iterations_reached"
    # v2 additions.
    assert bundle["bundle_schema_version"] == ESCALATION_BUNDLE_SCHEMA_VERSION
    assert bundle["atom"] == {
        "name": "sample",
        "requires": "n >= 0",
        "ensures": "result >= 0",
        "body": "let i = 0; while i < n { i = i + 1; }",
    }
    assert bundle["counterexamples"] == [{"i": 3}, {"i": 5}]
    assert bundle["tried_invariants"] == [
        {"expression": "i >= 0", "source": "llm", "iteration": 1, "counterexamples": [{"i": 3}]},
        {"expression": "i <= n", "source": "refine", "iteration": 2, "counterexamples": [{"i": 5}]},
    ]


def test_escalate_to_lean_without_extras_keeps_v1_shape_plus_version(tmp_path):
    import json

    source_file = tmp_path / "sample.mm"
    source_file.write_text("atom sample() body: 0;", encoding="utf-8")
    path = escalate_to_lean(str(source_file), {"line": 1, "context": {}})
    bundle = json.loads(path.read_text(encoding="utf-8"))
    assert set(bundle) == {
        "source_file",
        "loop_line",
        "loop_context",
        "reason",
        "bundle_schema_version",
    }


def test_try_cegis_repair_escalation_bundle_carries_contract_and_history(tmp_path):
    import json

    from agent.self_healing_repair import _try_cegis_repair
    from agent.thought_log import ThoughtProcess

    source_file = tmp_path / "count.mm"
    source = """atom count(n: i64)
requires: n >= 0;
ensures: result >= 0;
body: {
    let i = 0;
    while i < n
    invariant: true
    {
        i = i + 1;
    }
};"""
    source_file.write_text(source, encoding="utf-8")
    mumei = MagicMock()
    mumei.verify.return_value = {
        "success": False,
        "report": {"counterexample": {"i": 3}},
        "stdout": "",
        "stderr": "",
    }
    config = AgentConfig(
        api_key="",
        enable_cegis_loop=True,
        cegis_max_iterations=2,
        cegis_escalate_to_lean=True,
    )
    report = {
        "failure_type": "invariant_violated",
        "atom": "count",
        "atoms": [
            {
                "name": "count",
                "requires": "n >= 0",
                "ensures": "result >= 0",
                "body": "let i = 0; while i < n { i = i + 1; }",
            }
        ],
        "loop_info": {"line": 6, "context": {"variables": ["i", "n"]}},
    }

    with patch.object(
        CEGISLoop, "generate_initial_invariant", return_value="i >= 0"
    ), patch.object(CEGISLoop, "refine_invariant", return_value="i >= 0"):
        outcome = _try_cegis_repair(
            config=config,
            mumei=mumei,
            source_file=str(source_file),
            source=source,
            report=report,
            thought=ThoughtProcess(target_file=str(source_file)),
        )

    assert outcome is None  # escalated: no repaired source
    bundle = json.loads(
        (tmp_path / "count.escalation-bundle.json").read_text(encoding="utf-8")
    )
    assert bundle["reason"] == "cegis_max_iterations_reached"
    assert bundle["atom"]["requires"] == "n >= 0"
    assert bundle["atom"]["ensures"] == "result >= 0"
    assert bundle["counterexamples"] == [{"i": 3}, {"i": 3}]
    assert [c["iteration"] for c in bundle["tried_invariants"]] == [1, 2]
    assert all(c["expression"] == "i >= 0" for c in bundle["tried_invariants"])
