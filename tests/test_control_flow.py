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
        ("switch v := x.(type) { case int: fallthrough; default: return 1 }", "unsupported_fallthrough"),
        ("goto missing; return 0", "unresolved_label"),
        ("for { continue outer }", "unresolved_label"),
        ("for { break missing }", "unresolved_label"),
        ("outer: for { break missing }", "unresolved_label"),
        ("break", "jump_without_loop"),
        ("continue", "jump_without_loop"),
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
    flow = dataflow_facts.analyze_function(
        "mu.Lock(); for { break missing }; return x", "go"
    )
    assert flow is not None and flow.cfg is None
    assert flow.cfg_gaps[0].reason == "unresolved_label"
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
        "var x = 1",
        "const x = 1",
        "x, y := f()",
        "x, y = swap()",
    ],
)
def test_assignment_facts_recognize_assignment_forms(statement):
    cfg, result = facts(f"{statement}\nreturn")
    assert "x" in result[cfg.exit].some_path


def test_bare_var_is_a_declaration_not_an_assignment():
    body = "var x int\nreturn x"
    cfg, result = facts(body)
    declaration = nodes(cfg, "var")[0]
    assert result[declaration.node_id].some_path == frozenset()
    assert result[cfg.exit].some_path == frozenset()

    (use,) = control_flow.unassigned_uses(body, cfg)
    assert use.name == "x"
    assert use.definite is True


def test_bare_var_list_tracks_every_declaration_target():
    body = "var x, y int\nuse(x); use(y)"
    cfg, result = facts(body)
    assert result[cfg.exit].some_path == frozenset()
    uses = control_flow.unassigned_uses(body, cfg)
    assert {use.name for use in uses} == {"x", "y"}
    assert all(use.definite for use in uses)


def test_conditional_assignment_after_bare_var_is_maybe_assigned():
    body = "var x int\nif c { x = 1 }\nreturn x"
    cfg = graph(body)
    (use,) = control_flow.unassigned_uses(body, cfg)
    assert use.name == "x"
    assert use.definite is False


def test_bare_var_in_loop_body_kills_a_prior_assignment():
    body = "x := 1\nfor c { x = 2; var x int; use(x) }"
    cfg = graph(body)
    facts_by_node = control_flow.assignment_facts(body, cfg)
    declaration = nodes(cfg, "var")[0]
    use_node = nodes(cfg, "expr")[0]
    assert "x" in facts_by_node[nodes(cfg, "assign")[0].node_id].some_path
    assert "x" not in facts_by_node[declaration.node_id].some_path
    (use,) = control_flow.unassigned_uses(body, cfg)
    assert use.node_id == use_node.node_id
    assert use.name == "x"
    assert use.definite is True


def test_entry_assigned_seeds_parameter_reads_and_defaults_to_empty():
    body = "use(p); p = 1; use(p)"
    cfg = graph(body)
    seeded = control_flow.assignment_facts(
        body, cfg, entry_assigned=frozenset({"p"})
    )
    assert seeded[cfg.entry] == control_flow.AssignmentFacts(
        frozenset({"p"}), frozenset({"p"})
    )
    assert control_flow.flow_hints(
        body, cfg, entry_assigned=frozenset({"p"})
    ).unassigned == ()

    default = control_flow.assignment_facts(body, cfg)
    assert default[cfg.entry] == control_flow.AssignmentFacts(
        frozenset(), frozenset()
    )
    (use,) = control_flow.flow_hints(body, cfg).unassigned
    assert use.name == "p"
    assert use.definite is True


@pytest.mark.parametrize(
    "entry_assigned",
    [{"x"}, ["x"], frozenset({"x", 1})],
)
def test_assignment_facts_reject_invalid_entry_names(entry_assigned):
    body = "use(x)"
    cfg = graph(body)
    with pytest.raises(
        ValueError, match="entry_assigned must be a frozenset of strings"
    ):
        control_flow.assignment_facts(
            body, cfg, entry_assigned=entry_assigned
        )


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


def unuses(body):
    cfg = graph(body)
    return cfg, control_flow.unused_assignments(body, cfg)


def test_unused_assignments_flag_never_read_name():
    cfg, result = unuses("x := 1")
    node = nodes(cfg, "define")[0]
    assert result == (
        control_flow.UnusedAssignment(node.node_id, "x", node.span),
    )


def test_unused_assignments_clear_when_read():
    cfg, result = unuses("x := 1\nreturn x")
    assert result == ()


def test_unused_assignments_ignore_bare_var_declarations():
    cfg, result = unuses("var x int")
    assert result == ()


def test_unused_assignments_flag_each_unread_name():
    cfg, result = unuses("x := 1\ny = 2")
    assert {use.name for use in result} == {"x", "y"}
    assert len(result) == 2


def test_unused_assignments_flag_unused_range_targets():
    cfg, result = unuses("for i, v := range xs { print(i) }")
    assert [use.name for use in result] == ["v"]


def test_unused_assignments_inc_dec_count_as_read():
    cfg, result = unuses("x := 1\nx++")
    assert result == ()


def test_unused_assignments_self_rhs_counts_as_read():
    cfg, result = unuses("x = x + 1")
    assert result == ()


def test_unused_assignments_rhs_read_clears_name():
    cfg, result = unuses("y := x")
    assert [use.name for use in result] == ["y"]


def test_unused_assignments_count_unreachable_reads():
    cfg, result = unuses("x := 1\nreturn 0\nprint(x)")
    assert result == ()


def test_unused_assignments_ignore_blank_and_selector_targets():
    cfg, result = unuses("_ := f()\na.b = 1")
    assert result == ()


def test_unused_assignments_read_in_condition_counts():
    cfg, result = unuses("x := 1\nif x > 0 { y = 2 }")
    assert [use.name for use in result] == ["y"]


def test_unused_assignments_flag_every_writer_of_unread_name():
    cfg, result = unuses("x := 1\nx = 2")
    assert [use.name for use in result] == ["x", "x"]
    assert len({use.node_id for use in result}) == 2


def test_unused_assignments_require_matching_digest():
    cfg = graph("x := 1")
    with pytest.raises(ValueError, match="does not match"):
        control_flow.unused_assignments("y := 2", cfg)


def test_unreachable_statements_flag_after_return():
    cfg = graph("return 0\nx := 1")
    result = control_flow.unreachable_statements(cfg)
    node = nodes(cfg, "define")[0]
    assert result == (
        control_flow.UnreachableStatement(node.node_id, "define", node.span),
    )


def test_unreachable_statements_empty_when_all_reached():
    cfg = graph("x := 1\nif c { x = 2 } else { x = 3 }\nreturn x")
    assert control_flow.unreachable_statements(cfg) == ()


def test_unreachable_statements_skip_entry_and_exit():
    cfg = graph("return 0")
    result = control_flow.unreachable_statements(cfg)
    assert all(use.kind not in {"entry", "exit"} for use in result)


def test_unreachable_statements_flag_each_dead_node():
    cfg = graph("return 0\nx := 1\nprint(x)")
    kinds = [use.kind for use in control_flow.unreachable_statements(cfg)]
    assert kinds == ["expr", "define"]


def test_unreachable_statements_reachable_after_break():
    cfg = graph("for { break }\nreturn 1")
    assert control_flow.unreachable_statements(cfg) == ()


def flow(body):
    cfg = graph(body)
    return cfg, control_flow.flow_hints(body, cfg)


def test_flow_hints_aggregate_all_families():
    cfg, hints = flow("if c { x = 1 }\nreturn x\ny := 2\nz := 3")
    assert [use.name for use in hints.unassigned] == ["x"]
    assert [use.name for use in hints.unused] == ["z", "y"]
    assert [use.kind for use in hints.unreachable] == ["define", "define"]


def test_flow_hints_empty_body_is_empty_report():
    cfg, hints = flow("")
    assert hints == control_flow.FlowHints((), (), ())


def test_flow_hints_match_individual_calls():
    body = "x := 1\nreturn x\ny := 2"
    cfg = graph(body)
    hints = control_flow.flow_hints(body, cfg)
    assert hints.unassigned == control_flow.unassigned_uses(body, cfg)
    assert hints.unused == control_flow.unused_assignments(body, cfg)
    assert hints.unreachable == control_flow.unreachable_statements(cfg)


def test_flow_hints_require_matching_digest():
    cfg = graph("x := 1")
    with pytest.raises(ValueError, match="does not match"):
        control_flow.flow_hints("y := 2", cfg)


def test_flow_hints_definite_class_preserved():
    cfg, hints = flow("print(x)\nx := 1")
    (use,) = hints.unassigned
    assert use.definite is True


def metrics(body, expected):
    cfg = graph(body)
    hints = control_flow.flow_hints(body, cfg)
    return control_flow.evaluate_flow_hints(hints, expected)


def test_evaluate_flow_hints_all_matched():
    cfg = graph("return 0\nx := 1")
    hints = control_flow.flow_hints("return 0\nx := 1", cfg)
    node = nodes(cfg, "define")[0]
    expected = control_flow.HintExpectations(
        unused=((node.node_id, "x"),),
        unreachable=(node.node_id,),
    )
    result = control_flow.evaluate_flow_hints(hints, expected)
    assert result.unused == control_flow.FamilyMetrics(1, 0, 0)
    assert result.unreachable == control_flow.FamilyMetrics(1, 0, 0)
    assert result.unassigned == control_flow.FamilyMetrics(0, 0, 0)


def test_evaluate_flow_hints_missed_expected():
    cfg = graph("x := 1\nreturn x")
    hints = control_flow.flow_hints("x := 1\nreturn x", cfg)
    expected = control_flow.HintExpectations(unassigned=((2, "x"),))
    result = control_flow.evaluate_flow_hints(hints, expected)
    assert result.unassigned == control_flow.FamilyMetrics(0, 1, 0)


def test_evaluate_flow_hints_unexpected_findings():
    cfg = graph("print(x)\nx := 1")
    hints = control_flow.flow_hints("print(x)\nx := 1", cfg)
    result = control_flow.evaluate_flow_hints(
        hints, control_flow.HintExpectations()
    )
    assert result.unassigned == control_flow.FamilyMetrics(0, 0, 1)
    assert result.unused == control_flow.FamilyMetrics(0, 0, 0)


def test_evaluate_flow_hints_mixed_per_family():
    cfg, hints = flow("if c { x = 1 }\nreturn x\ny := 2\nz := 3")
    unreach = [
        use.node_id for use in hints.unreachable
    ]
    expected = control_flow.HintExpectations(
        unassigned=tuple(
            (use.node_id, "x") for use in hints.unassigned
        ),
        unused=((hints.unused[0].node_id, "z"),),
        unreachable=tuple(unreach[:1]),
    )
    result = control_flow.evaluate_flow_hints(hints, expected)
    assert result.unassigned.matched == 1
    assert result.unassigned.missed == 0
    assert result.unassigned.unexpected == 0
    assert result.unused.matched == 1
    assert result.unused.missed == 0
    assert result.unused.unexpected == 1
    assert result.unreachable == control_flow.FamilyMetrics(1, 0, 1)


def test_evaluate_flow_hints_empty_report_and_expectations():
    cfg, hints = flow("x := 1\nreturn x")
    result = control_flow.evaluate_flow_hints(
        hints, control_flow.HintExpectations()
    )
    assert result == control_flow.HintMetrics(
        control_flow.FamilyMetrics(0, 0, 0),
        control_flow.FamilyMetrics(0, 0, 0),
        control_flow.FamilyMetrics(0, 0, 0),
    )


@pytest.mark.parametrize(
    "expected",
    [
        control_flow.HintExpectations(unassigned=(("x", 2),)),
        control_flow.HintExpectations(unassigned=((2, 3),)),
        control_flow.HintExpectations(unassigned=((True, "x"),)),
        control_flow.HintExpectations(unassigned=((2, "x", 9),)),
        control_flow.HintExpectations(unassigned=("x",)),
        control_flow.HintExpectations(unused=((2.0, "x"),)),
        control_flow.HintExpectations(unreachable=("x",)),
        control_flow.HintExpectations(unreachable=(True,)),
        control_flow.HintExpectations(unreachable=(2.5,)),
    ],
)
def test_evaluate_flow_hints_rejects_invalid_expectations(expected):
    cfg, hints = flow("x := 1\nreturn x")
    with pytest.raises(ValueError, match="invalid hint expectation"):
        control_flow.evaluate_flow_hints(hints, expected)


def test_evaluate_flow_hints_definite_flag_not_part_of_key():
    cfg = graph("print(x)\nx := 1")
    hints = control_flow.flow_hints("print(x)\nx := 1", cfg)
    use = hints.unassigned[0]
    expected = control_flow.HintExpectations(
        unassigned=((use.node_id, "x"),)
    )
    result = control_flow.evaluate_flow_hints(hints, expected)
    assert result.unassigned == control_flow.FamilyMetrics(1, 0, 0)


GO_SOURCE = """package demo

func inc(x int) int {
	x := 1
	return x + 1
}

func reset() int {
	return 0
}
"""


def units(source=GO_SOURCE):
    return control_flow.go_file_units(source)


def test_go_file_units_index_each_function():
    result = units()
    assert result.gaps == ()
    assert [fn.name for fn in result.functions] == ["inc", "reset"]
    assert result.source_sha256 == hashlib.sha256(
        GO_SOURCE.encode("utf-8")
    ).hexdigest()


def test_go_file_units_record_body_spans_and_digests():
    result = units()
    fn = result.functions[0]
    body = GO_SOURCE[fn.body_span.start : fn.body_span.end]
    assert body.startswith("\n\tx := 1")
    assert hashlib.sha256(body.encode("utf-8")).hexdigest() == (
        fn.body_sha256
    )
    declaration = GO_SOURCE[fn.declaration.start : fn.declaration.end]
    assert declaration.startswith("func inc")


def test_go_file_units_empty_source_yields_no_functions():
    result = units("")
    assert result.functions == ()
    assert result.gaps == ()


def test_go_file_units_unsupported_source_reports_gap():
    result = units("not go at all {{{")
    assert result.functions == ()
    assert result.gaps == (
        control_flow.CFGGap("syntax_or_parser_unavailable"),
    )


def test_go_file_units_declaration_without_body_is_a_gap():
    result = units("package p\nfunc asm()\n")
    (fn,) = result.functions
    assert fn.body_span is None
    assert fn.body_sha256 is None
    assert [gap.reason for gap in result.gaps] == [
        "declaration_without_body"
    ]
    assert result.gaps[0].span == fn.declaration


def test_function_body_returns_the_exact_inner_text():
    result = units()
    fn = result.functions[0]
    body = control_flow.function_body(GO_SOURCE, result, fn)
    cfg = control_flow.build_go_cfg(body).graph
    assert cfg is not None
    assert cfg.source_sha256 == hashlib.sha256(
        body.encode("utf-8")
    ).hexdigest()


def test_go_entry_assigned_names_include_signature_and_file_names():
    source = """// 雪 before the declaration
package demo

var (
\tpackageVar int
\t_, packageVar2 = 1, 2
)
const (
\tpackageConst = 3
\t_ = 4
)
type T struct{}

func (receiver *T) Method(param, _ int) (result int, ok bool) {
\tvar local int
\t_ = local
\treturn
}
"""
    file_units = control_flow.go_file_units(source)
    assert file_units.gaps == ()
    (function,) = file_units.functions
    assert control_flow.go_entry_assigned_names(
        source, file_units, function
    ) == frozenset(
        {
            "packageVar",
            "packageVar2",
            "packageConst",
            "receiver",
            "param",
            "result",
            "ok",
        }
    )


def test_go_entry_assigned_names_handle_function_declarations():
    source = """package demo
var global int
const limit = 8

func calculate(input int) (result int) {
\treturn
}
"""
    file_units = control_flow.go_file_units(source)
    (function,) = file_units.functions
    assert control_flow.go_entry_assigned_names(
        source, file_units, function
    ) == frozenset({"global", "limit", "input", "result"})


def test_go_entry_assigned_names_reject_mismatched_provenance():
    source = "package p\nfunc f(param int) (result int) { return }\n"
    file_units = control_flow.go_file_units(source)
    function = file_units.functions[0]
    with pytest.raises(ValueError, match="source does not match"):
        control_flow.go_entry_assigned_names(
            source + "// changed\n", file_units, function
        )

    other_units = control_flow.go_file_units("package p\nfunc other() {}\n")
    with pytest.raises(ValueError, match="not declared"):
        control_flow.go_entry_assigned_names(
            source, file_units, other_units.functions[0]
        )


def test_function_body_rejects_a_foreign_source():
    result = units()
    with pytest.raises(ValueError, match="does not match"):
        control_flow.function_body(
            "package other\n", result, result.functions[0]
        )


def test_function_body_rejects_a_foreign_function():
    ours = units()
    other = units("package demo\nfunc other() int {\n\treturn 1\n}\n")
    with pytest.raises(ValueError, match="not declared"):
        control_flow.function_body(
            GO_SOURCE, ours, other.functions[0]
        )


def test_function_body_round_trips_through_flow_hints():
    result = units("package p\nfunc f() int {\n\tx := 1\n\treturn x\n}\n")
    body = control_flow.function_body(
        "package p\nfunc f() int {\n\tx := 1\n\treturn x\n}\n",
        result,
        result.functions[0],
    )
    cfg = control_flow.build_go_cfg(body).graph
    assert control_flow.flow_hints(body, cfg).unassigned == ()


def test_function_body_declaration_without_body_rejected():
    source = "package p\nfunc asm()\n"
    result = units(source)
    with pytest.raises(ValueError, match="no declared body"):
        control_flow.function_body(source, result, result.functions[0])


def by_text(cfg, body: str, needle: str):
    return [
        node
        for node in cfg.nodes
        if node.span is not None
        and body[node.span.start : node.span.end].startswith(needle)
    ]


def edges_to(cfg, source: int):
    return {edge.target for edge in cfg.edges if edge.source == source}


def kinds_at(cfg, targets):
    return {cfg.nodes[t].kind for t in targets}


def test_labelled_break_targets_the_labelled_loop():
    result = control_flow.build_go_cfg(
        "outer: for { if done { break outer }; work() }; after()"
    )
    cfg = result.graph
    assert result.gaps == ()
    (jump,) = nodes(cfg, "break")
    # The labelled break exits the outer loop to after(), not the if's
    # fallthrough.
    assert kinds_at(cfg, edges_to(cfg, jump.node_id)) == {"expr"}


def test_labelled_continue_targets_the_labelled_loop_post():
    result = control_flow.build_go_cfg(
        "outer: for i := 0; i < 9; i++ { continue outer }; after()"
    )
    cfg = result.graph
    (jump,) = nodes(cfg, "continue")
    # continue outer re-enters the loop update, not the exit.
    assert kinds_at(cfg, edges_to(cfg, jump.node_id)) == {"inc"}


def test_unlabelled_jumps_inside_labelled_loops_still_bind_innermost():
    result = control_flow.build_go_cfg(
        "outer: for { for { break }; after_inner() }; after()"
    )
    cfg = result.graph
    (jump,) = nodes(cfg, "break")
    assert kinds_at(cfg, edges_to(cfg, jump.node_id)) == {"expr"}


def test_labelled_break_through_nested_unlabelled_loop():
    result = control_flow.build_go_cfg(
        "outer: for { for { break outer }; x() }; after()"
    )
    cfg = result.graph
    (jump,) = nodes(cfg, "break")
    assert kinds_at(cfg, edges_to(cfg, jump.node_id)) == {"expr"}


def test_labelled_continue_keeps_everything_reachable():
    body = "outer: for x := 0; x < 9; x++ { continue outer }"
    cfg = control_flow.build_go_cfg(body).graph
    assert cfg is not None
    hints = control_flow.flow_hints(body, cfg)
    assert hints.unassigned == ()
    assert hints.unreachable == ()


def test_labelled_break_marks_the_post_unreachable():
    body = "outer: for x := 0; x < 9; x++ { break outer }"
    cfg = control_flow.build_go_cfg(body).graph
    assert cfg is not None
    hints = control_flow.flow_hints(body, cfg)
    assert hints.unassigned == ()
    assert {use.kind for use in hints.unreachable} == {"inc"}


def test_labelled_loop_facts_and_hints_still_bind():
    body = "outer: for x := 0; x < 9; x++ { if big { break outer }; y := x }"
    cfg = control_flow.build_go_cfg(body).graph
    assert cfg is not None
    hint_names = {use.name for use in control_flow.flow_hints(body, cfg).unassigned}
    assert "x" not in hint_names


def test_labelled_range_break_and_continue():
    result = control_flow.build_go_cfg(
        "outer: for _, x := range xs { if skip { continue outer }; if done { break outer }; use(x) }; after()"
    )
    cfg = result.graph
    assert result.gaps == ()
    (jump,) = nodes(cfg, "break")
    assert kinds_at(cfg, edges_to(cfg, jump.node_id)) == {"expr"}
    (jump,) = nodes(cfg, "continue")
    # A range has no update clause: continue re-enters the loop header.
    assert kinds_at(cfg, edges_to(cfg, jump.node_id)) == {"range"}


def test_terminating_call_edges_to_exit():
    result = control_flow.build_go_cfg("panic(x); return 0")
    cfg = result.graph
    assert result.gaps == ()
    (term,) = nodes(cfg, "terminate")
    assert edges_to(cfg, term.node_id) == {cfg.exit}
    (ret,) = nodes(cfg, "return")
    assert ret.node_id not in cfg.reachable()


@pytest.mark.parametrize(
    "call",
    ["panic(x)", "os.Exit(1)", "log.Fatal(err)", 'log.Fatalf("%s", err)',
     "logger.Fatal(err)", 'log.Panicf("%s", err)', "runtime.Goexit()"],
)
def test_terminating_call_variants_end_normal_flow(call):
    body = f"x := 1; {call}; x := 2"
    result = control_flow.build_go_cfg(body)
    cfg = result.graph
    assert result.gaps == ()
    (term,) = nodes(cfg, "terminate")
    assert edges_to(cfg, term.node_id) == {cfg.exit}


def test_terminate_inside_branches_leaves_other_paths_reachable():
    result = control_flow.build_go_cfg(
        "if bad { panic(x) }; work(); return 0"
    )
    cfg = result.graph
    (term,) = nodes(cfg, "terminate")
    assert edges_to(cfg, term.node_id) == {cfg.exit}
    kinds = {node.kind for node in cfg.nodes}
    assert {"if", "terminate", "expr", "return"} <= kinds
    assert len(cfg.reachable()) == len(cfg.nodes)


def test_terminate_unreachable_hint_after_panic():
    body = "panic(x); y := 1; return y"
    cfg = control_flow.build_go_cfg(body).graph
    hints = control_flow.flow_hints(body, cfg)
    assert {use.kind for use in hints.unreachable} == {"define", "return"}


def test_terminate_keeps_assignment_facts_correct_on_live_paths():
    cfg, result = facts("x := 1; panic(x)")
    assert cfg is not None
    (term,) = nodes(cfg, "terminate")
    assert "x" in result[term.node_id].all_paths


def test_closure_assigned_names_are_never_definite():
    # x is written inside a closure literal; a call to f (unmodelled)
    # could deliver x to use(x), so the use must not be "definite".
    body = "f := func() { x = 2 }; use(x); if true { x := 3 }"
    cfg = graph(body)
    hints = control_flow.flow_hints(body, cfg)
    uses = [use for use in hints.unassigned if use.name == "x"]
    assert uses and all(not use.definite for use in uses)
    assert "x" in hints.unreliable


def test_address_taken_names_are_never_definite():
    body = "use(x); p := &x; if true { x := 3 }"
    cfg = graph(body)
    hints = control_flow.flow_hints(body, cfg)
    uses = [use for use in hints.unassigned if use.name == "x"]
    assert uses and all(not use.definite for use in uses)
    assert "x" in hints.unreliable


def test_reliable_names_still_get_definite_marks():
    body = "use(x); if true { x := 3 }"
    cfg = graph(body)
    hints = control_flow.flow_hints(body, cfg)
    uses = [use for use in hints.unassigned if use.name == "x"]
    assert uses and uses[0].definite
    assert hints.unreliable == frozenset()


def test_unreliable_names_stay_hintable_not_definite():
    # The weaker class still fires: x misses all_paths at the use.
    body = "f := func() { x = 2 }; if c { use(x) }; x := 3"
    cfg = graph(body)
    hints = control_flow.flow_hints(body, cfg)
    uses = [use for use in hints.unassigned if use.name == "x"]
    assert uses and not uses[0].definite


def test_unassigned_scan_skips_closure_body_at_definition():
    body = (
        "var state *int\n"
        "writer := func() { state = new(int) }\n"
        "if condition { writer() }\n"
        "return *state"
    )
    cfg = graph(body)
    hints = control_flow.flow_hints(body, cfg)
    definition = nodes(cfg, "define")[0]
    read = nodes(cfg, "return")[0]
    assert not any(
        use.node_id == definition.node_id and use.name == "state"
        for use in hints.unassigned
    )
    (return_use,) = [
        use
        for use in hints.unassigned
        if use.node_id == read.node_id and use.name == "state"
    ]
    assert return_use.definite is False


def test_unassigned_scan_does_not_treat_direct_address_as_a_value_read():
    body = "p := &x\nx := 1"
    cfg = graph(body)
    assert control_flow.unassigned_uses(body, cfg) == ()


def test_unassigned_scan_still_reads_root_of_addressed_selector():
    body = "p := &x.f\nx := 1"
    cfg = graph(body)
    (use,) = control_flow.unassigned_uses(body, cfg)
    assert use.name == "x"
    assert use.node_id == nodes(cfg, "define")[0].node_id


def test_unassigned_value_read_scan_falls_back_to_regex_on_parse_failure(
    monkeypatch,
):
    body = "use(x)"
    tree = control_flow.tree_sitter_extract.extract_statements(body, "go")
    assert tree is not None
    statement = tree.statements[0]
    expected = frozenset(
        control_flow._IDENTIFIER.findall(control_flow._use_text(statement))
    )
    monkeypatch.setattr(
        control_flow.tree_sitter_extract,
        "parse",
        lambda source, language: (None, None),
    )
    assert control_flow._value_read_names(statement) == expected


def test_unused_assignments_count_closure_body_reads():
    body = "x := 1\nreader := func() { use(x) }"
    cfg, result = unuses(body)
    assert "x" not in {assignment.name for assignment in result}


def test_flow_hints_declares_empty_unreliable_for_plain_bodies():
    body = "x := 1; use(x)"
    cfg = graph(body)
    assert control_flow.flow_hints(body, cfg).unreliable == frozenset()


def test_expression_switch_builds_case_alternatives():
    result = control_flow.build_go_cfg(
        "switch x { case 0: a(); case 1, 2: b(); default: c() }; return 0"
    )
    cfg = result.graph
    assert result.gaps == ()
    (switch,) = nodes(cfg, "switch")
    cases = nodes(cfg, "case") + nodes(cfg, "default")
    assert len(cases) == 3
    assert edges_to(cfg, switch.node_id) == {c.node_id for c in cases}
    # No default-less fallback edge when a default exists.
    assert len(cfg.reachable()) == len(cfg.nodes)


def test_select_cases_edge_like_switch_alternatives():
    # A select's communication cases are exclusive alternatives
    # joined at the following statement — like a switch whose
    # guards are comm ops.
    body = "select { case v := <-ch: a(v); case ch2 <- y: b(); default: c() }"
    result = control_flow.build_go_cfg(body)
    assert result.graph is not None
    cfg = result.graph
    select_node = next(n for n in cfg.nodes if n.kind == "switch")
    case_targets = {
        e.target for e in cfg.edges if e.source == select_node.node_id
    }
    assert len(case_targets) == 3  # two comm cases + default
    # A select without a default BLOCKS until a case is ready —
    # no fall-through edge to the following statement.
    body2 = "select { case v := <-ch: a(v); case ch2 <- y: b() }; d()"
    result2 = control_flow.build_go_cfg(body2)
    assert result2.graph is not None
    select2 = next(
        n for n in result2.graph.nodes if n.kind == "switch"
    )
    assert all(e.kind == "case" for e in result2.graph.edges if e.source == select2.node_id)


def test_select_case_body_with_fallthrough_stays_unsupported():
    # `fallthrough` is not legal in select cases — one parsed
    # anyway stays unmodelled rather than silently edged.
    body = "select { case v := <-ch: fallthrough; default: a() }"
    result = control_flow.build_go_cfg(body)
    assert result.graph is None
    assert "unsupported_fallthrough" in {g.reason for g in result.gaps}


def test_type_switch_cases_edge_like_switch_alternatives():
    # Type cases are exclusive alternatives joined at the
    # following statement — same shape as an expression switch.
    body = "switch v := x.(type) { case int: a(v); case string, bool: b(); default: c() }; d()"
    result = control_flow.build_go_cfg(body)
    assert result.graph is not None
    cfg = result.graph
    switch_node = next(n for n in cfg.nodes if n.kind == "switch")
    case_targets = {
        e.target for e in cfg.edges if e.source == switch_node.node_id
    }
    assert len(case_targets) == 3  # two type cases + default
    assert all(
        cfg.nodes[t].kind in {"case", "default"} for t in case_targets
    )
    # A type switch with no default CAN fall through when no case
    # type matches — keep the edge to the following statement.
    body2 = "switch x.(type) { case int: a() }; b()"
    cfg2 = graph(body2)
    (switch2,) = nodes(cfg2, "switch")
    assert any(
        e.kind != "case" for e in cfg2.edges if e.source == switch2.node_id
    )


def test_type_switch_init_binding_and_break_exit():
    cfg = graph(
        "for { switch v := x.(type) { case int: break; default: c() }; after() }; done()"
    )
    (jump,) = nodes(cfg, "break")
    body = "for { switch v := x.(type) { case int: break; default: c() }; after() }; done()"
    (after,) = by_text(cfg, body, "after()")
    assert edges_to(cfg, jump.node_id) == {after.node_id}
    # `v := x.(type)` binds in the initializer before the case fan-out.
    (define,) = [
        n for n in nodes(cfg, "define") if ":=" in body[n.span.start : n.span.end]
    ]
    (switch,) = nodes(cfg, "switch")
    assert any(e.target == switch.node_id for e in cfg.edges if e.source == define.node_id)


def test_type_switch_assignment_facts_merge_over_cases():
    cfg, result = facts(
        "switch v := x.(type) { case int: y = 1; case string: y = 2 }; use(y)"
    )
    # `y` is assigned on some path through the switch.
    (use,) = nodes(cfg, "expr")
    assert "y" in result[use.node_id].some_path


def test_type_switch_case_body_with_fallthrough_stays_unsupported():
    # `fallthrough` is not legal in type cases — one parsed
    # anyway stays unmodelled rather than silently edged.
    body = "switch v := x.(type) { case int: fallthrough; default: a() }"
    result = control_flow.build_go_cfg(body)
    assert result.graph is None
    assert "unsupported_fallthrough" in {g.reason for g in result.gaps}


def test_type_switch_guard_whitespace_keeps_the_graph():
    # `x.( type )` is valid Go — the synthesized guard define must
    # span the source verbatim instead of normalizing it away.
    for body in (
        "switch v := x.( type ) { case int: a(v) }; b()",
        "switch v := x.(\ttype\n) { case int: a(v) }; b()",
    ):
        result = control_flow.build_go_cfg(body)
        assert result.graph is not None, body
        (define,) = [
            n for n in result.graph.nodes if n.kind == "define"
        ]
        assert body[define.span.start : define.span.end].endswith(")")


def test_type_switch_with_initializer_keeps_both_bindings():
    # `switch n := g(); v := x.(type)` — the SimpleStmt initializer
    # and the guard binding both enter the graph.
    cfg, result = facts(
        "switch n := g(); v := x.(type) { case int: use(v, n) }"
    )
    assert {n.kind for n in cfg.nodes} >= {"define", "switch"}
    defines = nodes(cfg, "define")
    assert len(defines) == 2
    texts = [cfg.nodes[d.node_id].span for d in defines]
    body = "switch n := g(); v := x.(type) { case int: use(v, n) }"
    assert sorted(body[s.start : s.end] for s in texts) == [
        "n := g()",
        "v := x.(type)",
    ]


def test_type_switch_guard_does_not_report_nil_assertion():
    # `x.(type)` on a nil interface routes to `case nil` — it never
    # panics, so the guard must not read as a plain type assertion.
    flow = dataflow_facts.analyze_function(
        "var x any; switch x.(type) { case nil: return 0; case int: return 1 }; return 2",
        "go",
    )
    assert flow is not None and flow.cfg is not None
    assert "uninitialized_use" not in {i.category for i in flow.issues}


def test_type_switch_guard_call_still_checks_nil_function():
    # `f().(type)` DOES panic when f is a nil func value — the operand
    # stays visible to the uninit check (evaluated after the init).
    flow = dataflow_facts.analyze_function(
        "var f func() any; switch f = f; f().(type) { case int: return 1 }; return 0",
        "go",
    )
    assert flow is not None and flow.cfg is not None
    # `f = f` reads `f` before writing it, so its nil state survives.
    assert "uninitialized_use" in {i.category for i in flow.issues}
    flow = dataflow_facts.analyze_function(
        "var f func() any; switch f().(type) { case int: return 1 }; return 0",
        "go",
    )
    assert flow is not None and flow.cfg is not None
    assert "uninitialized_use" in {i.category for i in flow.issues}


def test_switch_initializer_shadowing_restores_outer_binding():
    # `p := …` in a switch init is scoped to the switch: an outer nil
    # pointer of the same name must still be reported after it.
    flow = dataflow_facts.analyze_function(
        "var p *int; switch p := 1; x { case 0: _ = p }; return *p",
        "go",
    )
    assert flow is not None
    assert "uninitialized_use" in {i.category for i in flow.issues}
    # An `=` init write, by contrast, updates the outer binding and
    # persists past the switch.
    flow = dataflow_facts.analyze_function(
        "var p *int; q := 1; switch p = &q; x { case 0: }; return *p",
        "go",
    )
    assert flow is not None
    assert "uninitialized_use" not in {i.category for i in flow.issues}


def test_switch_init_result_is_visible_to_guard_checks():
    # `switch f = fallback; f().(type)` — the guard is checked against
    # the post-init environment, so the resolved call is not flagged.
    flow = dataflow_facts.analyze_function(
        "var f func() any; fallback := func() any { return nil };"
        " switch f = fallback; f().(type) { case int: return 1 }; return 0",
        "go",
    )
    assert flow is not None and flow.cfg is not None
    assert "uninitialized_use" not in {i.category for i in flow.issues}


def test_switch_without_default_edges_to_following():
    cfg = graph("switch x { case 0: a(); case 1: b() }; after()")
    (switch,) = nodes(cfg, "switch")
    targets = edges_to(cfg, switch.node_id)
    (after,) = by_text(cfg, "switch x { case 0: a(); case 1: b() }; after()", "after()")
    assert after.node_id in targets


def test_case_bodies_exit_to_following_not_each_other():
    body = "switch x { case 0: a(); case 1: b() }; after()"
    cfg = graph(body)
    body = "switch x { case 0: a(); case 1: b() }; after()"
    exprs = nodes(cfg, "expr")
    assert len(exprs) == 3  # a(), b(), after()
    (after,) = by_text(cfg, body, "after()")
    for e in exprs:
        if e.node_id != after.node_id:
            assert edges_to(cfg, e.node_id) == {after.node_id}


def test_break_inside_switch_exits_the_switch_not_the_loop():
    cfg = graph(
        "for { switch x { case 0: break; case 1: c() }; after() }; done()"
    )
    (jump,) = nodes(cfg, "break")
    body = "for { switch x { case 0: break; case 1: c() }; after() }; done()"
    exprs = nodes(cfg, "expr")
    assert len(exprs) == 3  # c(), after(), done()
    (after,) = by_text(cfg, body, "after()")
    assert edges_to(cfg, jump.node_id) == {after.node_id}


def test_continue_inside_switch_targets_enclosing_loop():
    cfg = graph(
        "for i := 0; i < 9; i++ { switch x { case 0: continue } }; done()"
    )
    (jump,) = nodes(cfg, "continue")
    assert kinds_at(cfg, edges_to(cfg, jump.node_id)) == {"inc"}


def test_unlabelled_break_in_switch_without_loop_is_allowed():
    result = control_flow.build_go_cfg("switch x { case 0: break }; after()")
    assert result.gaps == ()
    assert result.graph is not None


def test_switch_init_is_modelled():
    cfg, result = facts("switch i := 0; i { case 0: use(i) }; after()")
    assert cfg is not None


def test_case_guard_identifiers_count_as_uses():
    body = "x := 1; y := 2; switch x { case y: a() }; after()"
    cfg = graph(body)
    hints = control_flow.flow_hints(body, cfg)
    # x (tag) and y (case guard) are both reads — neither is unused.
    assert hints.unused == ()


def test_switch_all_cases_return_marks_following_unreachable():
    body = "switch x { case 0: return 1; default: return 2 }; z := 1"
    cfg = graph(body)
    hints = control_flow.flow_hints(body, cfg)
    assert {use.kind for use in hints.unreachable} == {"define"}


def test_labelled_break_through_switch_targets_the_loop():
    cfg = graph(
        "outer: for { switch x { case 0: break outer } }; after()"
    )
    (jump,) = nodes(cfg, "break")
    assert kinds_at(cfg, edges_to(cfg, jump.node_id)) == {"expr"}


def test_labelled_switch_statement_registers_a_goto_target():
    # A label on a switch is a legal ``goto`` target and does not change
    # the unlabelled ``break`` — it still exits to the next statement.
    body = "outer: switch x { case 0: break }; after()"
    cfg = graph(body)
    (jump,) = nodes(cfg, "break")
    (call,) = by_text(cfg, body, "after()")
    assert edges_to(cfg, jump.node_id) == {call.node_id}


def test_goto_forward_jump_skips_unreachable_statements():
    body = "x := 1; goto end; x = 2; end: return x"
    cfg = graph(body)
    (jump,) = nodes(cfg, "goto")
    (ret,) = nodes(cfg, "return")
    assert edges_to(cfg, jump.node_id) == {ret.node_id}
    (dead,) = by_text(cfg, body, "x = 2")
    assert dead.node_id not in cfg.reachable()
    assert ret.node_id in cfg.reachable()


def test_goto_backward_jump_targets_the_labelled_statement():
    body = "i := 0; top: i += 1; if i < 3 { goto top }; return i"
    cfg = graph(body)
    (jump,) = nodes(cfg, "goto")
    (labelled,) = by_text(cfg, body, "i += 1")
    assert edges_to(cfg, jump.node_id) == {labelled.node_id}


def test_goto_marks_no_fallthrough_for_the_following_statement():
    # ``goto`` never falls through — statements after it stay
    # unreachable until another edge lands on them.
    body = "goto done; x := 1; done: return x"
    cfg = graph(body)
    (dead,) = by_text(cfg, body, "x := 1")
    assert dead.node_id not in cfg.reachable()


def test_goto_resolves_to_a_label_inside_a_nested_block():
    # Go restricts jumping into blocks, but the CFG models labels as
    # function-scoped names — the edge lands on the labelled statement.
    body = "x := 0; if true { inner: x = 1 }; goto inner"
    cfg = graph(body)
    (jump,) = nodes(cfg, "goto")
    (labelled,) = by_text(cfg, body, "x = 1")
    assert edges_to(cfg, jump.node_id) == {labelled.node_id}


def test_goto_dead_assignment_stays_a_definite_unassigned_use():
    # The skipped ``y = 1`` must not leak ``y`` into the live
    # ``some_path`` pre-state at the label — only reachable
    # predecessors feed a use.
    body = "x := 0; goto done; y = 1; done: return x + y"
    cfg = graph(body)
    (use,) = control_flow.unassigned_uses(body, cfg)
    assert (use.name, use.definite) == ("y", True)


def test_goto_label_parses_unicode_and_commented_operands():
    # Go identifiers are Unicode, and comments may sit between the
    # keyword and the label — both forms resolve to the same edge.
    for body in (
        "x := 0; goto 終了; x = 1; 終了: _ = x",
        "x := 0; goto /* c */ done; x = 1; done: _ = x",
        "x := 0; goto // c\ndone; x = 1; done: _ = x",
    ):
        cfg = graph(body)
        (jump,) = nodes(cfg, "goto")
        (labelled,) = by_text(cfg, body, "_ = x")
        assert edges_to(cfg, jump.node_id) == {labelled.node_id}


def test_goto_labelled_break_and_continue_share_the_parser():
    # Labelled loop jumps take the same comment/Unicode operand forms.
    body = (
        "x := 0; L1: for true { break /* c */ L1 }; "
        "L2: for true { continue L2 }; x = 1"
    )
    cfg = graph(body)
    (leave,) = nodes(cfg, "break")
    (again,) = nodes(cfg, "continue")
    assert edges_to(cfg, leave.node_id) != set()
    assert edges_to(cfg, again.node_id) != set()


def test_stacked_and_empty_labels_both_resolve():
    # ``L1: L2: stmt`` keeps both labels; ``L: ;`` keeps the label on
    # an empty statement — neither reports unresolved_label. The outer
    # label lands on a wrapping block that leads to the statement; the
    # inner one lands on the statement itself.
    body = "x := 0; goto L2; x = 1; L1: L2: _ = x"
    cfg = graph(body)
    (jump,) = nodes(cfg, "goto")
    (labelled,) = by_text(cfg, body, "_ = x")
    assert edges_to(cfg, jump.node_id) == {labelled.node_id}
    body = "x := 0; goto L1; x = 1; L1: L2: _ = x"
    cfg = graph(body)
    (jump,) = nodes(cfg, "goto")
    (labelled,) = by_text(cfg, body, "_ = x")
    # the block the outer label lands on flows straight into the statement
    (block_target,) = edges_to(cfg, jump.node_id)
    assert edges_to(cfg, block_target) == {labelled.node_id}
    body = "x := 0; goto L; x = 1; L: ;"
    cfg = graph(body)
    (jump,) = nodes(cfg, "goto")
    (labelled,) = by_text(cfg, body, "L: ;")
    assert edges_to(cfg, jump.node_id) == {labelled.node_id}


def test_goto_label_before_closing_brace_resolves():
    # `L:` immediately before `}` carries no child statement either —
    # the label still exists as a goto target, modelled as a no-op.
    body = "x := 0; goto L; x = 1; L: "
    cfg = graph(body)
    (jump,) = nodes(cfg, "goto")
    (labelled,) = by_text(cfg, body, "L:")
    assert edges_to(cfg, jump.node_id) == {labelled.node_id}
    # The empty label falls through to the function exit.
    assert edges_to(cfg, labelled.node_id) == {cfg.exit}
    body = "x := 0; { goto L; x = 1; L: }; after()"
    cfg = graph(body)
    (jump,) = nodes(cfg, "goto")
    (labelled,) = by_text(cfg, body, "L:")
    assert edges_to(cfg, jump.node_id) == {labelled.node_id}
    # Inside a block, the empty label flows to the statement after `}`.
    (after,) = by_text(cfg, body, "after()")
    assert edges_to(cfg, labelled.node_id) == {after.node_id}


def test_terminal_fallthrough_edges_into_the_next_case_body():
    # `case 0: fallthrough` falls into case 1's body, so `a()` is
    # reached through the case-0 alternative too.
    body = "switch x { case 0: fallthrough; case 1: a(); default: b() }"
    cfg = graph(body)
    (jump,) = nodes(cfg, "fallthrough")
    (call,) = by_text(cfg, body, "a()")
    assert edges_to(cfg, jump.node_id) == {call.node_id}
    assert {edge.kind for edge in cfg.edges if edge.source == jump.node_id} == {
        "fallthrough"
    }


def test_terminal_fallthrough_in_a_mid_case_is_modelled():
    cfg = graph(
        "switch x { case 0: a(); case 1: fallthrough; case 2: b() }"
    )
    (jump,) = nodes(cfg, "fallthrough")
    assert {edge.kind for edge in cfg.edges if edge.source == jump.node_id} == {
        "fallthrough"
    }


def test_fallthrough_in_the_last_case_remains_a_declared_gap():
    result = control_flow.build_go_cfg(
        "switch x { case 0: a(); case 1: fallthrough }"
    )
    assert result.graph is None
    assert {gap.reason for gap in result.gaps} == {"unsupported_fallthrough"}


def test_fallthrough_outside_a_switch_remains_a_declared_gap():
    result = control_flow.build_go_cfg("fallthrough")
    assert result.graph is None
    assert {gap.reason for gap in result.gaps} == {"unsupported_fallthrough"}


def test_nonterminal_fallthrough_remains_a_declared_gap():
    result = control_flow.build_go_cfg(
        "switch x { case 0: fallthrough; a(); case 1: b() }"
    )
    assert result.graph is None
    assert {gap.reason for gap in result.gaps} == {"unsupported_fallthrough"}


def test_terminal_default_clause_fallthrough_is_modelled():
    # A non-final `default:` clause may also fall through.
    body = "switch x { default: fallthrough; case 0: a() }"
    cfg = graph(body)
    (jump,) = nodes(cfg, "fallthrough")
    (call,) = by_text(cfg, body, "a()")
    assert edges_to(cfg, jump.node_id) == {call.node_id}


def test_fallthrough_body_still_allows_break():
    body = (
        "switch x { case 0: if y { break }; fallthrough; case 1: a() }"
    )
    cfg = graph(body)
    (brk,) = nodes(cfg, "break")
    (after_target,) = (cfg.exit,)
    assert edges_to(cfg, brk.node_id) == {after_target}
    (jump,) = nodes(cfg, "fallthrough")
    (call,) = by_text(cfg, body, "a()")
    assert edges_to(cfg, jump.node_id) == {call.node_id}




def test_switch_inside_case_body_and_unreachable_after():
    cfg = graph(
        "switch x { case 0: switch y { case 1: a() } }; after()"
    )
    switches = nodes(cfg, "switch")
    assert len(switches) == 2
    assert len(cfg.reachable()) == len(cfg.nodes)


@pytest.mark.parametrize(
    "body,name",
    [
        ("x := 1; x.f = 2", "x"),
        ("a := []int{0}; a[i] = 2", "a"),
        ("i := 0; a[i] = 2", "i"),
        ("p := new(int); *p = 3", "p"),
        ("s := S{}; s.f.g = 2", "s"),
        ("x := 1; y := 0; y.f = x", "y"),
    ],
)
def test_compound_targets_count_as_reads(body, name):
    cfg = graph(body)
    hints = control_flow.flow_hints(body, cfg)
    assert name not in {use.name for use in hints.unused}


def test_plain_assign_target_is_not_a_self_read():
    cfg = graph("x = 1")
    hints = control_flow.flow_hints("x = 1", cfg)
    assert {use.name for use in hints.unused} == {"x"}


def test_compound_write_to_unassigned_root_still_universe_gated():
    # x.f writes read x but do not assign it; without a textual
    # assignment anywhere, x stays outside the declared universe.
    cfg = graph("x.f = 1")
    hints = control_flow.flow_hints("x.f = 1", cfg)
    assert [use.name for use in hints.unassigned] == []


def test_compound_assign_does_not_assign_the_root():
    # x.f = 2 never puts x into the assignment facts — only the
    # plain-identifier write later does.
    body = "x.f = 2; y := 1"
    cfg = graph(body)
    facts_map = control_flow.assignment_facts(body, cfg)
    (write,) = by_text(cfg, body, "x.f")
    (after,) = by_text(cfg, body, "y :=")
    assert "x" not in facts_map[write.node_id].all_paths
    assert "x" not in facts_map[after.node_id].all_paths


def test_select_comm_channel_counts_as_use():
    body = "ch := in; select { case <-ch: }; after()"
    cfg = graph(body)
    hints = control_flow.flow_hints(body, cfg)
    # `<-ch` inside the communication case reads ch — the `ch := in`
    # assignment is not dead.
    assert hints.unused == ()


def test_select_send_channel_and_value_count_as_uses():
    body = "ch := in; x := 1; select { case ch <- x: }; after()"
    cfg = graph(body)
    hints = control_flow.flow_hints(body, cfg)
    assert hints.unused == ()


def test_select_receive_assignment_counts_in_facts():
    body = "select { case x = <-ch: default: }; use(x)"
    cfg = graph(body)
    hints = control_flow.flow_hints(body, cfg)
    # `x = <-ch` assigns x on the case path only: the post-select
    # read is a possible (not definite) unassigned use.
    assert [(u.name, u.definite) for u in hints.unassigned] == [
        ("x", False)
    ]


def test_unassigned_uses_see_go_and_defer_argument_reads():
    # `go`/`defer` statements read their call arguments — a name
    # assigned only on one branch is a possible unassigned read
    # there, exactly like a plain call would be.
    cfg, result = uses("if c { y = 1 }\ngo use(y)\nreturn 0")
    assert "y" in {use.name for use in result}
    cfg, result = uses("if c { y = 1 }\ndefer use(y)\nreturn 0")
    assert "y" in {use.name for use in result}
