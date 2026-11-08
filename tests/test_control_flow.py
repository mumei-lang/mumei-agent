from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

import pytest

from agent import control_flow, dataflow_facts


def graph(body: str) -> control_flow.ControlFlowGraph:
    result = control_flow.build_go_cfg(body)
    assert result.gaps == ()
    assert result.graph is not None
    return result.graph


def nodes(cfg: control_flow.ControlFlowGraph, kind: str) -> list[control_flow.CFGNode]:
    return sorted(
        (node for node in cfg.nodes if node.kind == kind),
        key=lambda node: node.span.start if node.span else -1,
    )


def test_empty_body_and_stable_source_identity() -> None:
    cfg = graph("")
    assert cfg.source_sha256 == hashlib.sha256(b"").hexdigest()
    assert cfg.edges == (control_flow.CFGEdge(0, 1, "next"),)
    assert cfg.reachable() == frozenset({0, 1})
    assert graph("x := 1; return x") == graph("x := 1; return x")
    assert graph("return 1").source_sha256 != graph("return 2").source_sha256


def test_source_spans_use_body_relative_unicode_codepoints() -> None:
    body = '// 雪\nname := "é"\nif len(name) > 0 { return 1 }; return 0'
    cfg = graph(body)
    for node in cfg.nodes:
        if node.span is not None:
            text = body[node.span.start : node.span.end]
            assert text.startswith(
                {"define": "name", "if": "if", "return": "return"}[node.kind]
            )
    assert nodes(cfg, "define")[0].span.start == len("// 雪\n")


def test_if_edges_keep_both_guards_and_early_returns_do_not_join() -> None:
    cfg = graph("if d == 0 { return 0 }; return n/d")
    branch = nodes(cfg, "if")[0]
    returns = nodes(cfg, "return")
    assert {(edge.kind, edge.target) for edge in cfg.successors(branch.node_id)} == {
        ("true", returns[0].node_id),
        ("false", returns[1].node_id),
    }
    for node in returns:
        assert cfg.successors(node.node_id) == (
            control_flow.CFGEdge(node.node_id, cfg.exit, "return"),
        )


def test_else_if_and_initializers_have_distinct_nodes() -> None:
    cfg = graph(
        "if n := size(); n > 0 { return n } else if n < 0 { return -1 }; return 0"
    )
    assert len(nodes(cfg, "if")) == 2
    init = nodes(cfg, "define")[0]
    assert cfg.successors(cfg.entry)[0].target == init.node_id
    assert cfg.nodes[cfg.successors(init.node_id)[0].target].kind == "if"


def test_loop_continue_runs_post_and_break_exits_the_loop() -> None:
    cfg = graph(
        "for i:=0; i<n; i++ { if i==2 {continue}; if i==3 {break}; x+=i }; return x"
    )
    cont, brk, post, loop, ret = (
        nodes(cfg, kind)[0] for kind in ("continue", "break", "inc", "for", "return")
    )
    assert cfg.successors(cont.node_id)[0].target == post.node_id
    assert cfg.successors(post.node_id)[0].target == loop.node_id
    assert cfg.successors(brk.node_id)[0].target == ret.node_id
    assert ("false", ret.node_id) in {
        (edge.kind, edge.target) for edge in cfg.successors(loop.node_id)
    }
    assert cfg.nodes[cfg.successors(cfg.entry)[0].target].kind == "define"


def test_nested_loop_break_does_not_escape_the_outer_loop() -> None:
    cfg = graph("for a { for b { break }; x++ }; return x")
    brk = nodes(cfg, "break")[0]
    assert cfg.successors(brk.node_id)[0].target == nodes(cfg, "inc")[0].node_id


def test_range_has_iteration_and_exhaustion_edges() -> None:
    cfg = graph(
        "for _, item := range xs { if item == 0 { continue }; x += item }; return x"
    )
    loop = nodes(cfg, "range")[0]
    assert {edge.kind for edge in cfg.successors(loop.node_id)} == {"true", "false"}
    assert cfg.successors(nodes(cfg, "continue")[0].node_id)[0].target == loop.node_id


def test_infinite_loop_has_no_synthetic_fallthrough_or_return_facts() -> None:
    body = "for {}\nreturn 1"
    cfg = graph(body)
    assert cfg.exit not in cfg.reachable()
    flow = dataflow_facts.analyze_function(body, "go")
    assert flow is not None
    assert flow.facts_for_return(nodes(cfg, "return")[0].node_id) is None


def test_returns_after_unconditional_return_are_disconnected() -> None:
    cfg = graph("return 1; return 2")
    first, second = nodes(cfg, "return")
    assert first.node_id in cfg.reachable()
    assert second.node_id not in cfg.reachable()


@pytest.mark.parametrize(
    "body,reason",
    [
        ("switch x { case 0: return 1 }; return 0", "unsupported_switch"),
        ("select { default: return 0 }", "unsupported_switch"),
        ("defer f(); return 0", "unsupported_defer"),
        ("go f(); return 0", "unsupported_go"),
        ("panic(x); return 0", "unsupported_terminate"),
        ("goto done; done: return 0", "unsupported_goto"),
        ("outer: for { break outer }", "labelled_statement"),
        ("for { continue outer }", "labelled_jump"),
        ("break", "jump_without_loop"),
        ("continue", "jump_without_loop"),
        ("ch <- x", "unsupported_other"),
    ],
)
def test_unsupported_control_flow_returns_gaps_not_partial_graphs(
    body: str, reason: str
) -> None:
    result = control_flow.build_go_cfg(body)
    assert result.graph is None
    assert reason in {gap.reason for gap in result.gaps}
    assert all(gap.span is not None for gap in result.gaps)


def test_syntax_failure_and_missing_parser_are_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert (
        control_flow.build_go_cfg("if {").gaps[0].reason
        == "syntax_or_parser_unavailable"
    )
    monkeypatch.setattr(control_flow.tree_sitter_extract, "_get_parser", lambda _: None)
    assert control_flow.build_go_cfg("return 0").graph is None


def test_graph_metadata_does_not_copy_source_strings_or_claim_proofs() -> None:
    sentinel = "FAKE_SECRET_ONLY_FOR_TEST"
    encoded = json.dumps(asdict(graph(f'x := "{sentinel}"; return len(x)')))
    assert sentinel not in encoded
    assert not {"verified", "proved", "grade", "source", "text"} & set(
        json.loads(encoded)
    )


def test_return_site_facts_distinguish_identical_expressions() -> None:
    body = "if d != 0 { return n/d }; return n/d"
    flow = dataflow_facts.analyze_function(body, "go", param_names={"n", "d"})
    assert flow is not None and flow.cfg is not None
    first, second = nodes(flow.cfg, "return")
    assert "d" in flow.facts_for_return(first.node_id).nonzero
    assert "d" not in flow.facts_for_return(second.node_id).nonzero
    assert "d" not in flow.facts_for_expression("n/d").nonzero
    assert flow.facts_for_return(-1) is None
    assert flow.facts_for_return(len(flow.cfg.nodes)) is None
    assert flow.facts_for_return(flow.cfg.entry) is None


def test_assignments_kill_guard_facts_and_shadowing_is_local() -> None:
    body = "if d != 0 { d = 0; return n/d }; { d := 2; x = d }; return n/d"
    flow = dataflow_facts.analyze_function(body, "go", param_names={"n", "d"})
    assert flow is not None and flow.cfg is not None
    first, second = nodes(flow.cfg, "return")
    assert "d" not in flow.facts_for_return(first.node_id).nonzero
    assert "d" not in flow.facts_for_return(second.node_id).nonzero


def test_gap_does_not_discard_existing_resource_findings() -> None:
    flow = dataflow_facts.analyze_function("mu.Lock(); defer other(); return 0", "go")
    assert flow is not None and flow.cfg is None
    assert flow.cfg_gaps[0].reason == "unsupported_defer"
    assert "lock_held_at_return" in {issue.category for issue in flow.issues}
    assert flow.facts_for_return(2) is None


def test_non_go_analysis_remains_unsupported() -> None:
    assert dataflow_facts.analyze_function("return 1", "python") is None
