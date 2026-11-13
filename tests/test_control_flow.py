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


# ---- bounded fixed-point assignment facts ----


def facts(body: str):
    cfg = graph(body)
    return cfg, control_flow.assignment_facts(body, cfg)


def facts_at(cfg, results, kind, index=0):
    node = nodes(cfg, kind)[index]
    return results[node.node_id]


def test_assignment_facts_require_the_matching_body():
    cfg = graph("x := 1")
    with pytest.raises(ValueError, match="graph source digest"):
        control_flow.assignment_facts("y := 1", cfg)


def test_assignment_facts_are_linearly_flow_sensitive():
    cfg, result = facts("x := 1\ny := 2\nreturn y")
    assert facts_at(cfg, result, "define", 0) == control_flow.AssignmentFacts(
        frozenset({"x"}), frozenset({"x"})
    )
    assert facts_at(cfg, result, "define", 1) == control_flow.AssignmentFacts(
        frozenset({"x", "y"}), frozenset({"x", "y"})
    )
    assert result[cfg.exit].all_paths == frozenset({"x", "y"})
    assert result[cfg.entry] == control_flow.AssignmentFacts(
        frozenset(), frozenset()
    )


def test_assignment_facts_join_branches_per_path():
    cfg, result = facts("x := 1\nif c { y = 1 } else { z = 1 }\nreturn x")
    join = facts_at(cfg, result, "return")
    assert join.all_paths == frozenset({"x"})
    assert join.some_path == frozenset({"x", "y", "z"})


def test_assignment_facts_merge_when_every_branch_assigns():
    cfg, result = facts("if c { y = 1 } else { y = 2 }\nreturn y")
    join = facts_at(cfg, result, "return")
    assert join.all_paths == frozenset({"y"})
    assert join.some_path == frozenset({"y"})


def test_assignment_facts_loop_body_is_may_only():
    cfg, result = facts("x := 0\nfor c { x = 1 }\nreturn x")
    join = facts_at(cfg, result, "return")
    assert join.all_paths == frozenset({"x"})
    assert "i" not in join.some_path


def test_assignment_facts_for_init_and_post_flow_through():
    cfg, result = facts("for i := 0; i < n; i++ { x = i }\nreturn x")
    join = facts_at(cfg, result, "return")
    assert join.all_paths == frozenset({"i"})
    assert join.some_path == frozenset({"i", "x"})


def test_assignment_facts_unbounded_loop_body_still_assigns():
    cfg, result = facts("for { x = 1 }\nreturn x")
    body_node = nodes(cfg, "assign")[0]
    assert result[body_node.node_id].all_paths == frozenset({"x"})


@pytest.mark.parametrize(
    "statement",
    [
        "x := f()",
        "x = f()",
        "x += 1",
        "x -= 1",
        "x *= 2",
        "x /= 2",
        "x %= 2",
        "x <<= 1",
        "x >>= 1",
        "x &= 1",
        "x |= 1",
        "x ^= 1",
        "x &^= 1",
        "x++",
        "x--",
        "var x int",
        "var x = 1",
        "var x, y int",
        "const x = 1",
        "x, y := f()",
        "x, y = swap()",
    ],
)
def test_assignment_facts_recognize_assignment_forms(statement):
    cfg, result = facts(f"{statement}\nreturn")
    assert "x" in result[cfg.exit].some_path


@pytest.mark.parametrize(
    "statement",
    [
        "s.f = 1",
        "arr[0] = 1",
        "_ = f()",
        "f(x)",
        "if c { }",
        "for c { }",
    ],
)
def test_assignment_facts_ignore_non_name_targets(statement):
    cfg, result = facts(f"{statement}\nreturn")
    assert result[cfg.exit].some_path == frozenset()


def test_assignment_facts_blank_identifier_is_not_a_name():
    cfg, result = facts("_, b := f()\nreturn b")
    assert result[cfg.exit].all_paths == frozenset({"b"})


def test_assignment_facts_range_targets_assign():
    cfg, result = facts("for _, v := range xs { }\nreturn v")
    assert result[cfg.exit].all_paths == frozenset({"v"})


def test_assignment_facts_unreachable_nodes_hold_vacuous_all_paths():
    cfg, result = facts("return\nx := 1")
    dead = nodes(cfg, "define")[0]
    assert result[dead.node_id].all_paths == frozenset({"x"})
    assert result[dead.node_id].some_path == frozenset({"x"})


# ---- possibly-unassigned use hints over the fixed-point facts ----


def uses(body: str):
    cfg = graph(body)
    return cfg, control_flow.unassigned_uses(body, cfg)


def test_unassigned_uses_flag_one_sided_branch_assignment():
    cfg, result = uses("x := 1\nif c { y = 1 }\nreturn y")
    node = nodes(cfg, "return")[0]
    assert result == (
        control_flow.UnassignedUse(node.node_id, "y", node.span),
    )


def test_unassigned_uses_clear_when_every_branch_assigns():
    cfg, result = uses("if c { y = 1 } else { y = 2 }\nreturn y")
    assert result == ()


def test_unassigned_uses_flag_loop_gated_assignment():
    cfg, result = uses("for c { y = 1 }\nreturn y")
    assert [use.name for use in result] == ["y"]


def test_unassigned_uses_flag_completely_unassigned_name():
    cfg, result = uses("if c { y = 1 }\nreturn y\nz := y")
    names = {use.name for use in result}
    assert "y" in names


def test_unassigned_uses_ignore_names_never_assigned_anywhere():
    cfg, result = uses("return q")
    assert result == ()


def test_unassigned_uses_respect_init_before_condition():
    cfg, result = uses("if x := f(); x > 0 { return x }\nreturn 0")
    assert result == ()


def test_unassigned_uses_do_not_count_the_assignment_itself():
    cfg, result = uses("x := f()\nreturn x")
    assert result == ()


def test_unassigned_uses_check_rhs_before_target():
    cfg, result = uses("if c { x = 1 }\ny := x\nreturn y")
    names = {use.name for use in result}
    assert "x" in names
    assert "y" not in names


def test_unassigned_uses_empty_when_nothing_is_used():
    cfg, result = uses("x := 1\ny = 2")
    assert result == ()


def test_unassigned_uses_report_node_and_span():
    cfg, result = uses("if c { y = 1 }\nreturn y")
    (use,) = result
    node = nodes(cfg, "return")[0]
    assert use.node_id == node.node_id
    assert use.span == node.span


def test_unassigned_uses_definite_when_assignment_comes_later():
    cfg, result = uses("print(x)\nx := 1")
    node = nodes(cfg, "expr")[0]
    assert result == (
        control_flow.UnassignedUse(
            node.node_id, "x", node.span, definite=True
        ),
    )


def test_unassigned_uses_definite_when_only_unreachable_assignment():
    cfg, result = uses("if c { return x }\nreturn 0\nx := 1")
    (use,) = result
    assert use.name == "x"
    assert use.definite is True


def test_unassigned_uses_definite_in_untaken_branch():
    cfg, result = uses("if c { x = 1 } else { print(x) }\nreturn 0")
    (use,) = result
    assert use.name == "x"
    assert use.definite is True


def test_unassigned_uses_maybe_when_one_branch_assigns():
    cfg, result = uses("if c { y = 1 }\nreturn y")
    (use,) = result
    assert use.name == "y"
    assert use.definite is False


def test_unassigned_uses_maybe_via_loop_back_edge():
    cfg, result = uses("for c { y = 1 }\nreturn y")
    (use,) = result
    assert use.definite is False


def test_unassigned_uses_mix_definite_and_maybe():
    cfg, result = uses("if c { x = 1 } else { print(x) }\nreturn x")
    assert len(result) == 2
    maybe, definite = sorted(result, key=lambda use: use.definite)
    assert maybe.definite is False
    assert definite.definite is True
    assert {use.name for use in result} == {"x"}


@pytest.mark.parametrize(
    "body",
    [
        "print(x)\nx := 1",
        "return x\nx := 1",
        "if x > 0 { y = 1 }\nx := 1",
        "for x > 0 { y = 1 }\nx := 1",
        "z := x\nx := 1",
    ],
)
def test_unassigned_uses_definite_across_use_kinds(body):
    cfg, result = uses(body)
    assert len(result) == 1
    assert result[0].name == "x"
    assert result[0].definite is True


def test_unassigned_uses_ignore_unreachable_uses():
    cfg, result = uses("x := 1\nreturn 0\nprint(x)")
    assert result == ()


def test_unassigned_uses_never_assigned_not_marked_definite():
    cfg, result = uses("return q")
    assert result == ()
