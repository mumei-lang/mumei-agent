import json
import os

import pytest

import agent.sol_interprocedural as sol


def _summarize(source: str) -> sol.SolSummarySet:
    return sol.summarize_solidity(source)


def _fn(source: str, name: str) -> sol.SolFunctionSummary:
    s = _summarize(source)
    result = next(s2 for s2 in s.functions if s2.name.endswith("." + name))
    return result


CONTRACT = """contract C {
  function add(uint256 a, uint256 b) public pure returns (uint256) {
    return a + b;
  }
  function pick(uint256 x, uint256 y) public pure returns (uint256) {
    return add(y, x);
  }
}"""


def test_simple_scalar_return():
    s = _fn(CONTRACT, "add")
    assert s.available
    assert s.return_dependencies == frozenset({0, 1})


def test_call_composes_formal_to_actual():
    s = _fn(CONTRACT, "pick")
    assert s.available
    # add's {0,1} on actuals (y, x) → params {1, 0}
    assert s.return_dependencies == frozenset({0, 1})
    assert len(s.calls) == 1
    assert s.calls[0].callee == "add"


def test_ignored_actual_not_in_result():
    src = """contract C {
  function first(uint256 a, uint256 b) public pure returns (uint256) {
    return a;
  }
  function f(uint256 x, uint256 y) public pure returns (uint256) {
    return first(x, y);
  }
}"""
    s = _fn(src, "f")
    assert s.available
    assert s.return_dependencies == frozenset({0})


def test_local_declaration():
    src = """contract C {
  function f(uint256 x, uint256 y) public pure returns (uint256) {
    uint256 z = x + y;
    return z;
  }
}"""
    s = _fn(src, "f")
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_local_overwrite_drops_dep():
    src = """contract C {
  function f(uint256 x, uint256 y) public pure returns (uint256) {
    uint256 z = x;
    z = y;
    return z;
  }
}"""
    s = _fn(src, "f")
    assert s.available and s.return_dependencies == frozenset({1})


def test_if_else_join():
    src = """contract C {
  function f(uint256 x, uint256 c) public pure returns (uint256) {
    uint256 y = 0;
    if (c > 0) { y = x; } else { y = c; }
    return y;
  }
}"""
    s = _fn(src, "f")
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_assignment_and_update():
    src = """contract C {
  function f(uint256 x, uint256 y) public pure returns (uint256) {
    uint256 z = x;
    z += y;
    z++;
    return z;
  }
}"""
    s = _fn(src, "f")
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_ternary():
    src = """contract C {
  function f(uint256 x, uint256 y, uint256 c) public pure returns (uint256) {
    return c > 0 ? x : y;
  }
}"""
    s = _fn(src, "f")
    assert s.available and s.return_dependencies == frozenset({0, 1, 2})


def test_require_builtin_call():
    src = """contract C {
  function f(uint256 x) public pure returns (uint256) {
    require(x > 0);
    return x;
  }
}"""
    s = _fn(src, "f")
    assert s.available and s.return_dependencies == frozenset({0})
    assert s.calls[0].callee == "require"


def test_member_call_closes():
    src = """contract C {
  function f(uint256 x) public pure returns (uint256) {
    return this.g(x);
  }
}"""
    s = _fn(src, "f")
    assert not s.available


def test_empty_loop_admitted():
    src = """contract C {
  function f(uint256 x) public pure returns (uint256) {
    for (uint256 i = 0; i < x; i++) { }
    return x;
  }
}"""
    s = _fn(src, "f")
    assert s.available and s.return_dependencies == frozenset({0})


def test_break_in_loop_admitted():
    # Slice 14: break/continue are no-ops under the single-pass
    # may-analysis — later statements stay reachable.
    src = """contract C {
  function f(uint256 x) public pure returns (uint256) {
    uint256 s = x;
    for (uint256 i = 0; i < x; i++) { if (i > 2) { break; } s += i; }
    return s;
  }
}"""
    s = _fn(src, "f")
    assert s.available
    assert s.return_dependencies == frozenset({0})


def test_non_scalar_param_closes():
    src = """contract C {
  function f(uint256[] memory xs) public pure returns (uint256) {
    return 1;
  }
}"""
    s = _fn(src, "f")
    assert not s.available
    assert s.gaps[0].reason == "unsupported_signature"


def test_no_return_closes():
    src = """contract C {
  function f(uint256 x) public pure returns (uint256) {
    uint256 y = x;
  }
}"""
    s = _fn(src, "f")
    assert not s.available
    assert s.gaps[0].reason == "missing_return"


def test_unavailable_callee_blocks_caller():
    src = """contract C {
  function bad(uint256 a) public pure returns (uint256) {
    return ext(a);
  }
  function f(uint256 x) public pure returns (uint256) {
    return bad(x);
  }
}"""
    s = _fn(src, "f")
    assert not s.available
    assert any(g.reason == "call_unresolved" for g in s.gaps)


def test_context_key_stable_and_source_bound():
    s1 = _summarize(CONTRACT)
    s2 = _summarize(CONTRACT)
    s3 = _summarize(CONTRACT.replace("add", "sum"))
    assert s1.context_key == s2.context_key != s3.context_key
    assert s1.profile == "mumei.sol-scalar-parameter-deps/v1"


def test_named_return_slot():
    src = """contract C {
  function f(uint256 x) public pure returns (uint256 r) {
    r = x + 1;
    return;
  }
}"""
    s = _fn(src, "f")
    assert s.available and s.return_dependencies == frozenset({0})


def test_caller_contract_preferred_for_same_name():
    src = """contract A {
  function g(uint256 a) public pure returns (uint256) { return a; }
}
contract B {
  function g(uint256 a, uint256 b) public pure returns (uint256) { return b; }
  function f(uint256 x, uint256 y) public pure returns (uint256) {
    return g(x, y);
  }
}"""
    s = _fn(src, "f")
    assert s.available and s.return_dependencies == frozenset({1})


def test_emit_records_opaque_call():
    src = """contract C {
  event Send(address a);
  function f(uint256 x, uint256 y) public pure returns (uint256) {
    emit Send(msg.sender);
    return y;
  }
}"""
    s = _fn(src, "f")
    assert s.available and s.return_dependencies == frozenset({1})
    assert any(c.callee == "Send" for c in s.calls)


def test_opaque_globals_are_dep_free():
    src = """contract C {
  function f(uint256 x) public view returns (uint256) {
    uint256 t = uint256(uint160(msg.sender));
    return t;
  }
}"""
    s = _fn(src, "f")
    assert s.available and s.return_dependencies == frozenset()


def test_payable_conversion():
    src = """contract C {
  function f(address to, uint256 x) public pure returns (uint256) {
    address payable p = payable(to);
    return x;
  }
}"""
    s = _fn(src, "f")
    assert s.available and s.return_dependencies == frozenset({1})


def test_this_member_call_composes():
    src = """contract C {
  function g(uint256 a) internal pure returns (uint256) { return a; }
  function f(uint256 x, uint256 y) public pure returns (uint256) {
    return this.g(x) + y;
  }
}"""
    s = _fn(src, "f")
    # this.g is external-positioned but composes identically
    assert s.available and s.return_dependencies == frozenset({0, 1})


def test_void_unknown_call_is_opaque_not_closed():
    src = """contract C {
  error Bad(uint256 code);
  function f(uint256 x, uint256 y) public pure returns (uint256) {
    if (x > 0) { revert Bad(y); }
    return x;
  }
}"""
    s = _fn(src, "f")
    assert s.available and s.return_dependencies == frozenset({0})


def test_unknown_call_result_position_closes():
    src = """contract C {
  function f(uint256 x) public pure returns (uint256) {
    return ext(x);
  }
}"""
    s = _fn(src, "f")
    assert not s.available
    assert any(g.reason == "call_unresolved" for g in s.gaps)


def test_for_loop_may_write():
    src = """contract C {
  function f(uint256 n, uint256 x) public pure returns (uint256) {
    uint256 s = x;
    for (uint256 i = 0; i < n; i++) { s += i; }
    return s;
  }
}"""
    s = _fn(src, "f")
    assert s.available
    assert 0 in s.return_dependencies and 1 in s.return_dependencies


def test_while_loop():
    src = """contract C {
  function f(uint256 n, uint256 x) public pure returns (uint256) {
    uint256 s = x;
    while (s < n) { s += 1; }
    return s;
  }
}"""
    s = _fn(src, "f")
    assert s.available
    assert 0 in s.return_dependencies and 1 in s.return_dependencies


def test_unchecked_block():
    src = """contract C {
  function f(uint256 x) public pure returns (uint256) {
    uint256 s = 0;
    unchecked { s += x; }
    return s;
  }
}"""
    s = _fn(src, "f")
    assert s.available and s.return_dependencies == frozenset({0})


def test_keccak_and_abi_encode_carry_deps():
    src = """contract C {
  function f(uint256 x, uint256 y) public pure returns (uint256) {
    bytes32 h = keccak256(abi.encodePacked(x));
    return y;
  }
}"""
    s = _fn(src, "f")
    assert s.available and s.return_dependencies == frozenset({1})
    assert any(
        c.callee in {"keccak256", "abi.encodePacked"}
        for c in s.calls
    )


def test_state_var_read_is_dep_free():
    src = """contract C {
  uint256 s;
  function f(uint256 x) public view returns (uint256) {
    return s + 0;
  }
}"""
    s = _fn(src, "f")
    assert s.available and s.return_dependencies == frozenset()


def test_state_var_write_flows_and_sets_effects():
    src = """contract C {
  uint256 s;
  function f(uint256 x) public returns (uint256) {
    s = x + 1;
    return s;
  }
}"""
    s = _fn(src, "f")
    assert s.available and s.return_dependencies == frozenset({0})
    assert s.effects == "state_writes"


def test_this_state_member_write():
    src = """contract C {
  uint256 s;
  function f(uint256 x) public returns (uint256) {
    this.s = x;
    return this.s;
  }
}"""
    s = _fn(src, "f")
    assert s.available and s.return_dependencies == frozenset({0})
    assert s.effects == "state_writes"


def test_non_scalar_state_var_read_is_dep_free():
    # Slice 11: index reads on non-scalar state vars are opaque
    # external reads — dep-free (a literal index contributes no
    # deps), but admitted.
    src = """contract C {
  uint256[] xs;
  function f(uint256 x) public view returns (uint256) {
    return xs[0];
  }
}"""
    s = _fn(src, "f")
    assert s.available
    assert s.return_dependencies == frozenset()


def test_if_else_return_carries_cond_deps():
    src = """contract C {
  function f(uint256 c, uint256 a, uint256 b) public pure returns (uint256) {
    if (c > 0) { return a; } else { return b; }
  }
}"""
    s = _fn(src, "f")
    assert s.available
    assert s.return_dependencies == frozenset({0, 1, 2})


def test_block_scoped_decl_does_not_shadow_outer():
    src = """contract C {
  function f(uint256 x) public pure returns (uint256) {
    uint256 y = x;
    { uint256 y = 0; }
    return y;
  }
}"""
    s = _fn(src, "f")
    assert s.available and s.return_dependencies == frozenset({0})


def test_block_assignment_to_outer_propagates():
    src = """contract C {
  function f(uint256 x, uint256 y) public pure returns (uint256) {
    uint256 s = x;
    { s = y; }
    return s;
  }
}"""
    s = _fn(src, "f")
    assert s.available and s.return_dependencies == frozenset({1})


def test_nested_call_restores_caller_named_return():
    src = """contract C {
  function g(uint256 a) internal pure returns (uint256 out) {
    out = a;
    return;
  }
  function f(uint256 x) public pure returns (uint256 r) {
    r = g(x);
    return;
  }
}"""
    s = _fn(src, "f")
    assert s.available and s.return_dependencies == frozenset({0})


def test_overload_arity_resolution():
    src = """contract C {
  function g(uint256 a) public pure returns (uint256) { return a; }
  function g(uint256 a, uint256 b) public pure returns (uint256) { return b; }
  function f(uint256 x) public pure returns (uint256) { return g(x); }
}"""
    s = _fn(src, "f")
    assert s.available and s.return_dependencies == frozenset({0})
    r = _summarize(src)
    names = {f.name for f in r.functions}
    assert "C.g" in names and "C.g#2" in names


def test_overload_two_arg_call():
    src = """contract C {
  function g(uint256 a) public pure returns (uint256) { return a; }
  function g(uint256 a, uint256 b) public pure returns (uint256) { return b; }
  function f(uint256 x, uint256 y) public pure returns (uint256) { return g(x, y); }
}"""
    s = _fn(src, "f")
    assert s.available and s.return_dependencies == frozenset({1})


def test_slice4_modifier_wraps_body():
    s = _fn(
        """contract C {
    modifier onlyPos(uint p) {
        require(p > 0);
        _;
    }
    function f(uint a) public onlyPos(a) returns (uint) {
        return a;
    }
}""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0})
    assert any(c.callee == "require" for c in s.calls)


def test_slice4_modifier_param_binds_actual():
    s = _fn(
        """contract C {
    uint t;
    modifier bound(uint lo) {
        t = lo;
        _;
    }
    function f(uint a) public bound(a) returns (uint) {
        return a;
    }
}""",
        "f",
    )
    assert s.available and s.effects == "state_writes"


def test_slice4_modifier_chain():
    s = _fn(
        """contract C {
    modifier m1 { _; }
    modifier m2(uint q) { _; }
    function f(uint a) public m1 m2(a) returns (uint) {
        return a;
    }
}""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_slice4_modifier_nested_placeholder():
    s = _fn(
        """contract C {
    modifier m(uint p) {
        if (p > 0) { _; }
    }
    function f(uint a) public m(a) returns (uint) {
        return a;
    }
}""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_slice4_modifier_without_placeholder_skips_body():
    s = _fn(
        """contract C {
    modifier m { uint z = 1; }
    function f(uint a) public m returns (uint) {
        return a;
    }
}""",
        "f",
    )
    # `_;` never runs → the body's return is unreachable.
    assert not s.available or not s.return_dependencies


def test_slice4_unresolved_modifier_is_opaque():
    s = _fn(
        """contract C {
    function f(uint a) public onlyOwner returns (uint) {
        return a;
    }
}""",
        "f",
    )
    assert s.available
    assert s.return_dependencies == frozenset({0})
    assert s.effects == "unknown"
    assert any(c.callee == "onlyOwner" for c in s.calls)


def test_slice4_modifier_state_var_write():
    s = _fn(
        """contract C {
    uint s;
    modifier m(uint p) {
        s = p;
        _;
    }
    function f(uint a) public m(a) returns (uint) {
        return a;
    }
}""",
        "f",
    )
    assert s.available and s.effects == "state_writes"


def test_slice4_modifier_arity_mismatch_is_opaque():
    s = _fn(
        """contract C {
    modifier m(uint p, uint q) { _; }
    function f(uint a) public m(a) returns (uint) {
        return a;
    }
}""",
        "f",
    )
    assert s.available
    assert s.effects == "unknown"
    assert any(c.callee == "m" for c in s.calls)


def test_slice5_tuple_declaration():
    s = _fn(
        """contract C {
    function g(uint a) returns (uint, uint) { return (a, a + 1); }
    function f(uint a) public returns (uint) {
        (uint x, uint y) = g(a);
        return x;
    }
}""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_slice5_tuple_assignment():
    s = _fn(
        """contract C {
    function g(uint a) returns (uint, uint) { return (a, a + 1); }
    function f(uint a) public returns (uint) {
        uint x; uint y;
        (x, y) = g(a);
        return y;
    }
}""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_slice5_named_multi_return_bare_return():
    s = _fn(
        """contract C {
    function f(uint a) public returns (uint r, uint s) {
        r = a;
        s = a + 1;
        return;
    }
}""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_slice5_tuple_member_target_writes_state():
    s = _fn(
        """contract C {
    uint t;
    function g(uint a) returns (uint, uint) { return (a, a); }
    function f(uint a) public returns (uint) {
        uint x;
        (x, this.t) = g(a);
        return x;
    }
}""",
        "f",
    )
    assert s.available and s.effects == "state_writes"


def test_slice5_non_scalar_return_param_closes():
    s = _fn(
        """contract C {
    function f(uint a) public returns (uint, uint[]) {
        uint[] memory arr;
        return (a, arr);
    }
}""",
        "f",
    )
    assert not s.available
    assert any(g.reason == "unsupported_signature" for g in s.gaps)


def test_slice6_inherited_function_call():
    s = _fn(
        """contract A {
    function g(uint a) returns (uint) { return a + 1; }
}
contract B is A {
    function f(uint a) public returns (uint) { return g(a); }
}""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_slice6_super_call():
    s = _fn(
        """contract A {
    function g(uint a) returns (uint) { return a + 1; }
}
contract B is A {
    function f(uint a) public returns (uint) { return super.g(a); }
}""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_slice6_super_skips_own_contract():
    # `super.g` must not resolve to B's own `g` (which would
    # recurse) — it picks the ancestor's.
    src = """contract A {
    function g(uint a) returns (uint) { return a + 1; }
}
contract B is A {
    function g(uint a) returns (uint) { return super.g(a); }
    function f(uint a) public returns (uint) { return super.g(a); }
}"""
    r = _summarize(src)
    bf = next(f for f in r.functions if f.name.endswith(".f"))
    assert bf.available and bf.return_dependencies == frozenset({0})


def test_slice6_inherited_state_var():
    s = _fn(
        """contract A { uint s; }
contract B is A {
    function f(uint a) public returns (uint) {
        s = a;
        return this.s;
    }
}""",
        "f",
    )
    assert s.available and s.effects == "state_writes"


def test_slice6_inherited_modifier():
    s = _fn(
        """contract A {
    modifier m(uint p) { _; }
}
contract B is A {
    function f(uint a) public m(a) returns (uint) { return a; }
}""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_slice6_transitive_ancestor():
    s = _fn(
        """contract A { function g(uint a) returns (uint) { return a; } }
contract B is A { }
contract C is B {
    function f(uint a) public returns (uint) { return g(a); }
}""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_slice7_delete_local_clears_deps():
    s = _fn(
        """contract C {
    function f(uint a) public returns (uint) {
        uint x = a;
        delete x;
        return x;
    }
}""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset()


def test_slice7_delete_state_marks_writes():
    s = _fn(
        """contract C {
    uint s;
    function f(uint a) public returns (uint) {
        s = a;
        delete s;
        return this.s;
    }
}""",
        "f",
    )
    assert s.available and s.effects == "state_writes"


def test_slice7_try_catch_joins_branches():
    s = _fn(
        """contract C {
    function g(uint a) returns (uint) { return a; }
    function f(uint a) public returns (uint) {
        uint x = 0;
        try g(a) returns (uint r) { x = r; } catch { x = a; }
        return x;
    }
}""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_slice7_try_returns_from_both_paths():
    s = _fn(
        """contract C {
    function g(uint a) returns (uint) { return a; }
    function f(uint a) public returns (uint) {
        try g(a) returns (uint r) { return r; } catch { return 0; }
        return a;
    }
}""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_slice8_external_member_call_is_opaque():
    s = _fn(
        """contract C {
    function f(uint a) public returns (uint) {
        uint x = ext.balanceOf(a);
        return x;
    }
}""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0})
    assert s.effects == "unknown"
    assert any(c.callee == "ext.balanceOf" for c in s.calls)


def test_slice8_interface_cast_member_call():
    src = """interface IERC20 {
    function balanceOf(uint a) external returns (uint);
}
contract C {
    address token;
    function f(uint a) public returns (uint) {
        return IERC20(token).balanceOf(a);
    }
}"""
    s = _fn(src, "f")
    assert s.available and s.return_dependencies == frozenset({0})
    assert any("balanceOf" in (c.callee or "") for c in s.calls)


def test_slice8_library_qualified_call_resolves():
    s = _fn(
        """library L {
    function mul(uint a, uint b) internal returns (uint) {
        return a;
    }
}
contract C {
    function f(uint a) public returns (uint) {
        return L.mul(a, a);
    }
}""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_slice8_qualified_call_uses_named_contract():
    s = _fn(
        """contract C {
    function g(uint a) returns (uint) { return 0; }
    function f(uint a) public returns (uint) {
        return Other.f(a);
    }
}
contract Other {
    function f(uint a) public returns (uint) { return a; }
}""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_slice8_ext_member_skips_unrelated_fallback():
    # `ext.f(...)` where another contract declares `f` must not
    # resolve to that contract's member.
    s = _fn(
        """contract C {
    function f(uint a) public returns (uint) {
        return ext.f(a);
    }
}
contract Other {
    function f(uint a) public returns (uint) { return 0; }
}""",
        "f",
    )
    assert s.available
    assert s.effects == "unknown"
    assert any(c.callee == "ext.f" for c in s.calls)


def test_slice9_using_for_method_syntax():
    s = _fn(
        """library L {
    function mul(uint a, uint b) internal returns (uint) {
        return a;
    }
}
contract C {
    using L for uint;
    function f(uint a) public returns (uint) {
        return a.mul(2);
    }
}""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_slice9_using_receiver_dep_flows():
    # The receiver `a` becomes arg0 — its dep must reach the call.
    s = _fn(
        """library L {
    function mul(uint a, uint b) internal returns (uint) {
        return a;
    }
}
contract C {
    using L for uint;
    function f(uint a, uint b) public returns (uint) {
        return b.mul(a);
    }
}""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({1})


def test_slice9_using_missing_member_stays_opaque():
    s = _fn(
        """library L {
    function mul(uint a, uint b) internal returns (uint) {
        return a;
    }
}
contract C {
    using L for uint;
    function f(uint a) public returns (uint) {
        return a.miss(2);
    }
}""",
        "f",
    )
    assert s.available and s.effects == "unknown"


def test_slice10_no_returns_clause_admitted():
    s = _fn(
        """contract C {
    function f(uint a) public { uint x = a; }
}""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset()


def test_slice10_free_function_resolves():
    s = _fn(
        """function g(uint a) returns (uint) { return a; }
contract C {
    function f(uint a) public returns (uint) { return g(a); }
}""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_slice10_constructor_summarized():
    src = """contract C {
    uint s;
    constructor(uint a) { s = a; }
    function f(uint a) public returns (uint) { return s + a; }
}"""
    r = _summarize(src)
    ctor = next(
        f for f in r.functions if f.name.endswith(".constructor")
    )
    assert ctor.available and ctor.effects == "state_writes"


def test_slice10_fallback_receive_summarized():
    src = """contract C {
    uint s;
    fallback() external { s = 1; }
    receive() external payable { s = 2; }
}"""
    r = _summarize(src)
    names = {f.name for f in r.functions}
    assert any(".fallback" in n for n in names)
    assert any(".receive" in n for n in names)


def test_slice11_mapping_write_marks_state():
    s = _fn(
        """contract C {
    mapping(uint => uint) m;
    function f(uint a, uint k) public returns (uint) {
        m[k] = a;
        return a;
    }
}""",
        "f",
    )
    assert s.available and s.effects == "state_writes"


def test_slice11_index_read_carries_index_deps():
    s = _fn(
        """contract C {
    mapping(uint => uint) m;
    function f(uint a, uint k) public returns (uint) {
        uint x = m[k];
        return x;
    }
}""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({1})


def test_slice11_index_write_then_read():
    s = _fn(
        """contract C {
    uint[] arr;
    function f(uint a, uint k) public returns (uint) {
        arr[k] = a;
        return arr[k];
    }
}""",
        "f",
    )
    assert s.available
    assert s.return_dependencies == frozenset({0, 1})
    assert s.effects == "state_writes"


def test_slice11_nested_index_write():
    s = _fn(
        """contract C {
    mapping(uint => mapping(uint => uint)) m;
    function f(uint a, uint k) public returns (uint) {
        m[k][a] = k;
        return a;
    }
}""",
        "f",
    )
    assert s.available and s.effects == "state_writes"


def test_slice12_storage_length_read_dep_free():
    s = _fn(
        """contract C {
    uint[] arr;
    function f(uint a) public returns (uint) {
        uint n = arr.length;
        return a;
    }
}""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_slice12_push_marks_state_and_flows():
    s = _fn(
        """contract C {
    uint[] arr;
    function f(uint a) public returns (uint) {
        arr.push(a);
        return arr[0];
    }
}""",
        "f",
    )
    assert s.available
    assert s.effects == "state_writes"
    assert s.return_dependencies == frozenset({0})


def test_slice12_pop_returns_slot():
    s = _fn(
        """contract C {
    uint[] arr;
    function f(uint a) public returns (uint) {
        arr.push(a);
        uint x = arr.pop();
        return x;
    }
}""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_slice12_this_member_read_dep_free():
    s = _fn(
        """contract C {
    uint[] arr;
    function f(uint a) public returns (uint) {
        uint n = this.arr.length;
        return a;
    }
}""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_slice13_new_contract_inlines_constructor():
    s = _fn(
        """contract D { uint x; constructor(uint b) { x = b; } }
contract C {
    function f(uint a) public returns (uint) {
        D d = new D(a);
        return a;
    }
}""",
        "f",
    )
    assert s.available and s.effects == "state_writes"


def test_slice13_new_array_opaque():
    s = _fn(
        """contract C {
    function f(uint a) public returns (uint) {
        uint[] memory xs = new uint[](a);
        return a;
    }
}""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_slice13_delete_index_marks_state():
    s = _fn(
        """contract C {
    uint[] arr;
    function f(uint a) public returns (uint) {
        delete arr[0];
        return a;
    }
}""",
        "f",
    )
    assert s.available and s.effects == "state_writes"


def test_slice13_non_scalar_local_decl_binds():
    s = _fn(
        """contract D { function g(uint b) public returns (uint) { return b; } }
contract C {
    function f(uint a) public returns (uint) {
        D d = new D(a);
        return d.g(a);
    }
}""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_slice14_struct_literal_binds_fields():
    s = _fn(
        """contract C { struct S { uint x; uint y; }
    function f(uint a) public returns (uint) {
        S memory s = S(a, 2);
        return a;
    }
}""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_slice14_struct_literal_named_fields():
    s = _fn(
        """contract C { struct S { uint x; uint y; }
    function f(uint a) public returns (uint) {
        S memory s = S({x: a, y: 0});
        return a;
    }
}""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_slice14_call_options_flow():
    s = _fn(
        """contract C {
    function f(uint a) public returns (uint) {
        ext.g{value: a}();
        return a;
    }
}""",
        "f",
    )
    assert s.available and s.effects == "unknown"


def test_slice14_break_continue_noop():
    s = _fn(
        """contract C {
    function f(uint a) public returns (uint) {
        uint s = 0;
        for (uint i = 0; i < a; i++) { if (i > 5) break; s = i; }
        return s;
    }
}""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_slice15_selfdestruct_marks_unknown():
    s = _fn(
        """contract C {
    function f(uint a) public { selfdestruct(payable(msg.sender)); }
}""",
        "f",
    )
    assert s.available and s.effects == "unknown"


def test_slice15_env_builtins_flow():
    s = _fn(
        """contract C {
    function f(uint a) public returns (uint) {
        uint x = addmod(a, 1, blockhash(a));
        return x;
    }
}""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_review_loop_return_gains_cond_deps():
    s = _fn(
        """contract C {
    function f(uint n) public returns (uint) {
        while (n > 0) { return 1; }
        return 0;
    }
}""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_review_for_without_init_reads_condition():
    s = _fn(
        """contract C {
    function f(uint x) public returns (uint) {
        uint s = 0;
        for (; s < x; s++) {}
        return s;
    }
}""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_review_internal_call_propagates_state_writes():
    s = _fn(
        """contract C {
    uint x;
    function g(uint b) public { x = b; }
    function f(uint a) public returns (uint) { g(a); return a; }
}""",
        "f",
    )
    assert s.available and s.effects == "state_writes"


def test_review_discarded_unknown_call_admitted():
    s = _fn(
        """contract C {
    function f(uint x) public returns (uint) { mystery(); return x; }
}""",
        "f",
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_review_free_function_overloads():
    s = _fn(
        """function g(uint a) returns (uint) { return a; }
function g(uint a, uint b) returns (uint) { return b; }
contract C {
    function h(uint x) public returns (uint) { return g(x); }
}""",
        "h",
    )
    assert s.available and s.return_dependencies == frozenset({0})


def test_review_shadowed_state_var_not_state_write():
    s = _fn(
        """contract C {
    uint s;
    function f(uint x) public returns (uint) {
        uint s = x;
        s = 2;
        return x;
    }
}""",
        "f",
    )
    assert s.available
    assert s.effects == "none_in_supported_fragment"


def test_review_emit_marks_unknown():
    s = _fn(
        """contract C {
    event E();
    function f() public { emit E(); }
}""",
        "f",
    )
    assert s.available and s.effects == "unknown"


def test_review2_for_init_decl_scoped_to_loop():
    s = _fn(
        """contract C { uint s;
function f(uint x) public {
    for (uint s = 0; s < 3; s++) { }
    s = x;
} }""",
        "f",
    )
    assert s.available and s.effects == "state_writes"


def test_review2_loop_local_decl_shadows_state_var():
    s = _fn(
        """contract C { uint s;
function f(uint x) public {
    for (uint s = 0; s < 3; s++) { s = x; }
} }""",
        "f",
    )
    assert s.available
    assert s.effects == "none_in_supported_fragment"


def test_review2_nested_block_decl_shadows_state_var():
    s = _fn(
        """contract C { uint s;
function f(uint x) public {
    { uint s; { s = x; } }
    s = 1;
} }""",
        "f",
    )
    assert s.available and s.effects == "state_writes"


def test_review2_void_unknown_call_marks_unknown():
    s = _fn(
        """contract C {
function f(uint x) public returns (uint) {
    mystery(x);
    return x;
} }""",
        "f",
    )
    assert s.available
    assert s.effects == "unknown"
    assert s.return_dependencies == frozenset({0})


def test_review3_callee_write_not_shadowed_by_caller_local():
    r = _summarize(
        """contract C { uint s;
function f(uint x) public { uint s = 1; g(); }
function g() internal { s = 1; } }"""
    )
    g = next(s2 for s2 in r.functions if s2.name.endswith(".g"))
    assert g.available and g.effects == "state_writes"


def test_review3_cond_write_on_loop_local_not_state_write():
    s = _fn(
        """contract C { uint s;
function f(uint x) public {
    for (uint s = 0; (s = x) < 5; ) { }
} }""",
        "f",
    )
    assert s.available
    assert s.effects == "none_in_supported_fragment"


def test_review3_cond_write_on_state_var_still_marks():
    s = _fn(
        """contract C { uint s;
function f(uint x) public {
    for (uint i = 0; (s = x) < 5; ) { }
} }""",
        "f",
    )
    assert s.available and s.effects == "state_writes"


def test_review4_cond_state_write_not_shadowed_by_body_local():
    s = _fn(
        """contract C { uint s;
function f(uint x) public {
    for (uint i = 0; (s = 1) < 5; i++) { uint s = 0; }
} }""",
        "f",
    )
    assert s.available and s.effects == "state_writes"


def test_review4_update_state_write_not_shadowed_by_body_local():
    s = _fn(
        """contract C { uint s;
function f(uint x) public {
    for (uint i = 0; i < 5; s = i) { uint s = 0; }
} }""",
        "f",
    )
    assert s.available and s.effects == "state_writes"


def test_review4_inner_loop_write_reaches_outer_may_union():
    s = _fn(
        """contract C { uint s;
function f(uint x) public returns (uint) {
    uint s = 0;
    for (uint i = 0; i < x; i++) {
        for (uint j = 0; (s = 0) < 5; j++) { }
    }
    return s;
} }""",
        "f",
    )
    assert s.available
    assert s.return_dependencies == {0}


def test_manifest_round_trip_restores_the_summary_set():
    s = sol.summarize_solidity(
        "contract C {"
        " uint256 s;"
        " function f(uint256 x, uint256 y) public returns (uint256) {"
        "   return g(x) + y;"
        " }"
        " function g(uint256 v) internal returns (uint256) { return v + 1; }"
        "}"
    )
    restored = sol.SolSummarySet.from_dict(
        json.loads(json.dumps(s.to_dict()))
    )
    assert restored == s


def test_manifest_restoration_rejects_a_wrong_schema():
    s = sol.summarize_solidity(
        "contract C { function f(uint256 x) public returns (uint256) {"
        " return x; } }"
    )
    bad = s.to_dict()
    bad["schema_version"] = "mumei.other/v1"
    with pytest.raises(ValueError, match="malformed"):
        sol.SolSummarySet.from_dict(bad)


def test_manifest_restoration_rejects_unknown_and_missing_keys():
    s = sol.summarize_solidity(
        "contract C { function f(uint256 x) public returns (uint256) {"
        " return x; } }"
    )
    good = s.to_dict()
    bad = dict(good, extra_key=1)
    with pytest.raises(ValueError, match="malformed"):
        sol.SolSummarySet.from_dict(bad)
    bad = dict(good)
    del bad["context_key"]
    with pytest.raises(ValueError, match="malformed"):
        sol.SolSummarySet.from_dict(bad)


def test_manifest_restoration_rejects_a_contradictory_available_flag():
    s = sol.summarize_solidity(
        "contract C { function f(uint256 x) public returns (uint256) {"
        " return x; } }"
    )
    good = s.to_dict()
    forged = dict(good)
    forged["functions"] = [
        dict(good["functions"][0], available=False)
    ]
    # `available: false` alongside a derived result claims the
    # record has a gap it does not declare — malformed.
    with pytest.raises(ValueError, match="malformed"):
        sol.SolSummarySet.from_dict(forged)


def test_manifest_restoration_rejects_wrong_types():
    s = sol.summarize_solidity(
        "contract C { function f(uint256 x) public returns (uint256) {"
        " return x; } }"
    )
    good = s.to_dict()
    bad = dict(good, context_key=123)
    with pytest.raises(ValueError, match="malformed"):
        sol.SolSummarySet.from_dict(bad)
    fn = dict(good["functions"][0])
    fn["calls"] = [
        {
            "byte": 0,
            "callee": "g",
            "arguments": [["x"]],
            "result": [0],
        }
    ]
    bad = dict(good, functions=[fn])
    with pytest.raises(ValueError, match="malformed"):
        sol.SolSummarySet.from_dict(bad)


# --- slice 17: sol-summaries / sol-summaries-accept routes --------------------

def _sol_args(source, manifest=None, function=None):
    return type(
        "A",
        (),
        {
            "source": str(source),
            "manifest": str(manifest) if manifest else None,
            "function": function,
        },
    )()


_SOL_SRC = (
    "contract C { uint s;"
    " function f(uint x) public returns (uint) { return g(x); }"
    " function g(uint v) public returns (uint) { return v + 1; } }"
)


def test_summaries_route_emits_json(tmp_path, capsys):
    src = tmp_path / "a.sol"
    src.write_text(_SOL_SRC)
    sol.main(_sol_args(src))
    out = json.loads(capsys.readouterr().out)
    assert out["schema_version"] == "mumei.sol-scalar-parameter-deps/v1"
    assert out["functions"][0]["name"] == "C.f"


def test_accept_route_accepts_a_surviving_function(tmp_path, capsys):
    src = tmp_path / "a.sol"
    src.write_text(_SOL_SRC)
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(sol.summarize_solidity(_SOL_SRC).to_dict())
    )
    with pytest.raises(SystemExit) as exc:
        sol.main_accept(_sol_args(src, manifest, "f"))
    assert exc.value.code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["schema_version"] == "mumei.sol-summary-accept/v1"
    assert out["accepted"] is True
    assert out["summary"]["name"] == "C.f"


def test_accept_route_accepts_a_qualified_function_name(
    tmp_path, capsys
):
    src = tmp_path / "a.sol"
    src.write_text(_SOL_SRC)
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(sol.summarize_solidity(_SOL_SRC).to_dict())
    )
    with pytest.raises(SystemExit):
        sol.main_accept(_sol_args(src, manifest, "C.g"))
    out = json.loads(capsys.readouterr().out)
    assert out["accepted"] is True
    assert out["summary"]["name"] == "C.g"
    assert out["summary"]["contract"] == "C"


def test_accept_route_refuses_a_changed_context(tmp_path, capsys):
    src = tmp_path / "a.sol"
    src.write_text(_SOL_SRC)
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(
            sol.summarize_solidity(_SOL_SRC + "//x").to_dict()
        )
    )
    with pytest.raises(SystemExit):
        sol.main_accept(_sol_args(src, manifest, "f"))
    out = json.loads(capsys.readouterr().out)
    assert out["accepted"] is False
    assert out["reason"] == "context_mismatch"
    assert "summary" not in out


def test_accept_route_refuses_an_unknown_function(tmp_path, capsys):
    src = tmp_path / "a.sol"
    src.write_text(_SOL_SRC)
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(sol.summarize_solidity(_SOL_SRC).to_dict())
    )
    with pytest.raises(SystemExit):
        sol.main_accept(_sol_args(src, manifest, "absent"))
    out = json.loads(capsys.readouterr().out)
    assert out["accepted"] is False
    assert out["reason"] == "unknown_function"


def test_accept_route_emits_the_live_record_not_the_forged_one(
    tmp_path, capsys
):
    src = tmp_path / "a.sol"
    src.write_text(_SOL_SRC)
    manifest = tmp_path / "m.json"
    forged = sol.summarize_solidity(_SOL_SRC).to_dict()
    forged["functions"][0]["return_dependencies"] = []
    manifest.write_text(json.dumps(forged))
    with pytest.raises(SystemExit):
        sol.main_accept(_sol_args(src, manifest, "f"))
    out = json.loads(capsys.readouterr().out)
    assert out["accepted"] is True
    assert out["summary"]["return_dependencies"] == [0]


def test_accept_route_rejects_a_malformed_manifest(tmp_path, capsys):
    src = tmp_path / "a.sol"
    src.write_text(_SOL_SRC)
    manifest = tmp_path / "m.json"
    manifest.write_text('{"schema_version": "mumei.other/v1"}')
    with pytest.raises(SystemExit) as exc:
        sol.main_accept(_sol_args(src, manifest, "f"))
    assert exc.value.code == 2
    out = json.loads(capsys.readouterr().out)
    assert out["error"]["reason"] == "manifest_malformed"


def test_accept_route_refuses_an_ambiguous_bare_name(tmp_path, capsys):
    two = (
        "contract A { function f(uint x) public returns (uint)"
        " { return x; } }"
        "contract B { function f(uint x) public returns (uint)"
        " { return x; } }"
    )
    src = tmp_path / "a.sol"
    src.write_text(two)
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(sol.summarize_solidity(two).to_dict())
    )
    with pytest.raises(SystemExit):
        sol.main_accept(_sol_args(src, manifest, "f"))
    out = json.loads(capsys.readouterr().out)
    assert out["accepted"] is False
    assert out["reason"] == "ambiguous_function"
    # The qualified name still resolves.
    with pytest.raises(SystemExit):
        sol.main_accept(_sol_args(src, manifest, "B.f"))
    out = json.loads(capsys.readouterr().out)
    assert out["accepted"] is True
    assert out["summary"]["name"] == "B.f"


# --- slice 18: sol-summaries-check / sol-summaries-reuse routes ---------------

def _sol_route_args(source, manifest, output=None):
    return type(
        "A",
        (),
        {
            "source": str(source),
            "manifest": str(manifest),
            "output": str(output) if output else None,
        },
    )()


_SOL_CHANGED = (
    "contract C { uint s;"
    " function f(uint x) public returns (uint) { return g(x); }"
    " function g(uint v) public returns (uint) { return 7; } }"
)


def test_check_route_partitions_names(tmp_path, capsys):
    src = tmp_path / "a.sol"
    src.write_text(_SOL_SRC)
    manifest = tmp_path / "m.json"
    old = sol.summarize_solidity(_SOL_SRC).to_dict()
    old["functions"].append(
        {
            "name": "C.gone",
            "contract": "C",
            "available": True,
            "parameters": [],
            "return_dependencies": [],
            "calls": [],
            "gaps": [],
            "effects": "none_in_supported_fragment",
        }
    )
    manifest.write_text(json.dumps(old))
    src.write_text(_SOL_CHANGED)
    sol.main_check(_sol_route_args(src, manifest))
    out = json.loads(capsys.readouterr().out)
    assert out["schema_version"] == "mumei.sol-summary-check/v1"
    assert out["context_match"] is False
    # g's deps flip {0}→{} and f inlines the callee result —
    # both records change.
    assert out["stale"] == ["C.f", "C.g"]
    assert out["missing"] == ["C.gone"]
    assert out["reusable"] == []


def test_check_route_reports_reusable_records(tmp_path, capsys):
    src = tmp_path / "a.sol"
    src.write_text(_SOL_SRC)
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(sol.summarize_solidity(_SOL_SRC).to_dict())
    )
    sol.main_check(_sol_route_args(src, manifest))
    out = json.loads(capsys.readouterr().out)
    assert out["context_match"] is True
    assert out["reusable"] == ["C.f", "C.g"]
    assert out["stale"] == []
    assert out["missing"] == []


def test_reuse_route_merges_and_rekeys(tmp_path, capsys):
    src = tmp_path / "a.sol"
    src.write_text(_SOL_CHANGED)
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(sol.summarize_solidity(_SOL_SRC).to_dict())
    )
    sol.main_reuse(_sol_route_args(src, manifest))
    out = json.loads(capsys.readouterr().out)
    assert out["schema_version"] == "mumei.sol-scalar-parameter-deps/v1"
    fresh = sol.summarize_solidity(_SOL_CHANGED)
    assert out["context_key"] == fresh.context_key
    by_name = {f["name"]: f for f in out["functions"]}
    assert by_name["C.g"]["return_dependencies"] == []
    assert "C.f" in by_name


def test_manifest_restoration_rejects_duplicate_function_names():
    s = sol.summarize_solidity(_SOL_OVERLOAD).to_dict()
    s["functions"].append(dict(s["functions"][0]))
    with pytest.raises(ValueError, match="malformed"):
        sol.SolSummarySet.from_dict(s)


def test_call_record_accepts_a_null_callee():
    call = sol.SolCall.from_dict(
        {"byte": 1, "callee": None, "arguments": [], "result": None}
    )
    assert call.callee is None
    # and a full manifest containing it round-trips
    s = sol.summarize_solidity(_SOL_OVERLOAD).to_dict()
    s["functions"][0]["calls"].append(
        {"byte": 1, "callee": None, "arguments": [], "result": None}
    )
    sol.SolSummarySet.from_dict(s)


_SOL_OVERLOAD = (
    "contract C {"
    " function g(uint x) public returns (uint) { return x; }"
    " function g(uint x, uint y) public returns (uint)"
    " { return x + y; } }"
)


def test_accept_route_bare_name_of_overloads_is_ambiguous(
    tmp_path, capsys
):
    src = tmp_path / "a.sol"
    src.write_text(_SOL_OVERLOAD)
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(sol.summarize_solidity(_SOL_OVERLOAD).to_dict())
    )
    args = type(
        "A",
        (),
        {
            "source": str(src),
            "manifest": str(manifest),
            "function": "g",
            "output": None,
        },
    )()
    with pytest.raises(SystemExit):
        sol.main_accept(args)
    out = json.loads(capsys.readouterr().out)
    assert out["accepted"] is False
    assert out["reason"] == "ambiguous_function"


def test_accept_route_qualified_name_picks_one_overload(
    tmp_path, capsys
):
    src = tmp_path / "a.sol"
    src.write_text(_SOL_OVERLOAD)
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(sol.summarize_solidity(_SOL_OVERLOAD).to_dict())
    )
    names = {
        f["name"] for f in sol.summarize_solidity(
            _SOL_OVERLOAD
        ).to_dict()["functions"]
    }
    assert "C.g#2" in names
    args = type(
        "A",
        (),
        {
            "source": str(src),
            "manifest": str(manifest),
            "function": "C.g#2",
            "output": None,
        },
    )()
    with pytest.raises(SystemExit):
        sol.main_accept(args)
    out = json.loads(capsys.readouterr().out)
    assert out["accepted"] is True
    assert out["summary"]["name"] == "C.g#2"


def _attempt_args(source, attempt_timeout=60000, output=None,
                  memory_bound_mb=None):
    return type(
        "A",
        (),
        {
            "source": str(source),
            "attempt_timeout": attempt_timeout,
            "memory_bound_mb": memory_bound_mb,
            "output": str(output) if output else None,
        },
    )()


def test_attempt_route_emits_lineage_and_candidate(tmp_path, capsys):
    src = tmp_path / "a.sol"
    src.write_text(_SOL_SRC)
    sol.main_attempt(_attempt_args(src))
    report = json.loads(capsys.readouterr().out)
    assert (
        report["schema_version"]
        == "mumei.sol-summaries-attempt-report/v1"
    )
    sequence = report["sequence"]
    assert (
        sequence["schema_version"] == "mumei.verifier-attempt-sequence/v1"
    )
    assert sequence["attempts"][0]["state"] == "exited"
    assert sequence["attempts"][0]["events"][-1]["kind"] == "exited"
    assert sequence["attempts"][0]["events"][-1]["exit_code"] == 0
    assert sequence["selected_result"]["attempt_number"] == 1
    normalized = report["normalized"]
    assert normalized["outcome"] == "exited"
    assert normalized["exit_code"] == 0
    candidate = report["candidate"]
    assert (
        candidate["schema_version"]
        == "mumei.verifier-evidence-candidate/v1"
    )
    assert (
        candidate["request_fingerprint"]
        == sequence["request_fingerprint"]
    )


def test_attempt_route_binds_source_bytes(tmp_path, capsys):
    src = tmp_path / "a.sol"
    src.write_text(_SOL_SRC)
    sol.main_attempt(_attempt_args(src))
    first = json.loads(capsys.readouterr().out)["sequence"][
        "request_fingerprint"
    ]
    src.write_text(_SOL_SRC + "//changed")
    sol.main_attempt(_attempt_args(src))
    second = json.loads(capsys.readouterr().out)["sequence"][
        "request_fingerprint"
    ]
    assert first != second


def test_attempt_route_rejects_output_overwriting_source(
    tmp_path, capsys
):
    src = tmp_path / "a.sol"
    src.write_text(_SOL_SRC)
    with pytest.raises(SystemExit) as exc:
        sol.main_attempt(_attempt_args(src, output=src))
    assert exc.value.code == 2
    out = json.loads(capsys.readouterr().out)
    assert out["error"]["reason"] == "output_overwrites_source"
    assert src.read_text() == _SOL_SRC


def test_attempt_route_output_file(tmp_path, capsys):
    src = tmp_path / "a.sol"
    src.write_text(_SOL_SRC)
    out_path = tmp_path / "report.json"
    sol.main_attempt(_attempt_args(src, output=out_path))
    capsys.readouterr()
    report = json.loads(out_path.read_text())
    assert (
        report["schema_version"]
        == "mumei.sol-summaries-attempt-report/v1"
    )


def test_attempt_route_rejects_output_hardlink_to_source(
    tmp_path, capsys
):
    src = tmp_path / "a.sol"
    src.write_text(_SOL_SRC)
    link = tmp_path / "linked.sol"
    os.link(src, link)
    with pytest.raises(SystemExit) as exc:
        sol.main_attempt(_attempt_args(src, output=link))
    assert exc.value.code == 2
    out = json.loads(capsys.readouterr().out)
    assert out["error"]["reason"] == "output_overwrites_source"
    assert src.read_text() == _SOL_SRC


def test_attempt_route_skips_candidate_when_inputs_change(
    tmp_path, capsys, monkeypatch
):
    src = tmp_path / "a.sol"
    src.write_text(_SOL_SRC)
    from agent import attempt_runner

    real_run = attempt_runner.AttemptRunner.run

    def run_then_modify(
        self, request, argv, memory_bound_mb=None, cancel_event=None,
        feed_bytes=None,
    ):
        src.write_text(_SOL_SRC + "//mutated mid-run")
        return real_run(
            self,
            request,
            argv,
            memory_bound_mb=memory_bound_mb,
            cancel_event=cancel_event,
            feed_bytes=feed_bytes,
        )

    monkeypatch.setattr(
        attempt_runner.AttemptRunner, "run", run_then_modify
    )
    sol.main_attempt(_attempt_args(src))
    report = json.loads(capsys.readouterr().out)
    assert report["sequence"].get("selected_result") is None
    assert "candidate" not in report


# --- Devin Review round on bf8c383b: regression tests ---


def test_review_comment_in_body_ok():
    src = """contract C {
  function f(uint256 a) public pure returns (uint256) {
    // take the param
    return a;
  }
}"""
    s = _fn(src, "f")
    assert s.available and s.return_dependencies == frozenset({0})


def test_review_named_args_map_by_param_name():
    src = """contract C {
  function g(uint256 a, uint256 b) public pure returns (uint256) {
    return b;
  }
  function f(uint256 x, uint256 y) public pure returns (uint256) {
    return g({a: x, b: y});
  }
}"""
    s = _fn(src, "f")
    assert s.available and s.return_dependencies == frozenset({1})


def test_review_arity_matched_unavailable_no_fallback():
    src = """contract C {
  function g(uint256 a) public pure returns (uint256) {
    return a;
  }
  function g(uint256 a, uint256 b) public pure returns (uint256) {
    assembly { let z := 0 }
    return a;
  }
  function f(uint256 x, uint256 y) public pure returns (uint256) {
    return g(x, y);
  }
}"""
    s = _fn(src, "f")
    assert not s.available


def test_review_state_deps_across_internal_call():
    src = """contract C {
  uint256 s;
  function setter(uint256 a) public {
    s = a;
  }
  function f(uint256 a) public returns (uint256) {
    setter(a);
    return s;
  }
}"""
    s = _fn(src, "f")
    assert s.return_dependencies == frozenset({0})


def test_review_modifier_state_sync():
    src = """contract C {
  uint256 s;
  modifier m(uint256 a) {
    s = a;
    _;
  }
  function f(uint256 a) public m(a) returns (uint256) {
    return s;
  }
}"""
    s = _fn(src, "f")
    assert s.return_dependencies == frozenset({0})


def test_review_modifier_param_not_shadowed_by_fn_param():
    src = """contract C {
  uint256 s;
  modifier m() {
    s = 1;
    _;
  }
  function f(uint256 s_) public m() returns (uint256) {
    return s_;
  }
}"""
    s = _fn(src, "f")
    assert s.effects == "state_writes"


def test_review_short_circuit_preserves_maybe_deps():
    src = """contract C {
  function f(uint256 a, bool b) public returns (uint256) {
    uint256 x = a;
    bool ok = b && ((x = 0) == 0);
    return x;
  }
}"""
    s = _fn(src, "f")
    assert s.return_dependencies == frozenset({0})


def test_review_ternary_preserves_maybe_deps():
    src = """contract C {
  function f(uint256 a, bool b) public returns (uint256) {
    uint256 x = a;
    bool ok = b ? ((x = 0) == 0) : false;
    return x;
  }
}"""
    s = _fn(src, "f")
    assert s.return_dependencies == frozenset({0})


def test_review_expr_update_marks_state_write():
    src = """contract C {
  uint256 s;
  function f(uint256 a) public returns (uint256) {
    return s++;
  }
}"""
    s = _fn(src, "f")
    assert s.effects == "state_writes"


def test_review_tuple_assignment_marks_state_write():
    src = """contract C {
  uint256 s;
  function g(uint256 a) public pure returns (uint256, uint256) {
    return (a, a);
  }
  function f(uint256 a) public returns (uint256) {
    (s, s) = g(a);
    return s;
  }
}"""
    s = _fn(src, "f")
    assert s.effects == "state_writes"


def test_review_failed_call_in_index_base_is_gap():
    src = """contract C {
  function g(uint256 a) public pure returns (uint256[] memory) {
    uint256[] memory r;
    assembly { mstore(r, 1) }
    return r;
  }
  function f(uint256 a) public returns (uint256) {
    return g(a)[0];
  }
}"""
    s = _fn(src, "f")
    assert not s.available


def test_review_virtual_override_union():
    src = """contract B {
  function inner(uint256 a) public virtual pure returns (uint256) {
    return 1;
  }
  function outer(uint256 a) public returns (uint256) {
    return inner(a);
  }
}
contract C is B {
  function inner(uint256 a) public override pure returns (uint256) {
    return a;
  }
}"""
    s = _fn(src, "outer")
    # C.outer inherits B.outer; its inner() call may dispatch to
    # C's override — the union carries the param dep.
    assert s.return_dependencies == frozenset({0})


def test_review_output_cannot_overwrite_source(tmp_path, capsys):
    src = tmp_path / "a.sol"
    src.write_text(_SOL_SRC)
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(sol.summarize_solidity(_SOL_SRC).to_dict())
    )
    with pytest.raises(SystemExit) as exc:
        sol.main_check(_sol_route_args(src, manifest, output=src))
    assert exc.value.code == 2
    out = json.loads(capsys.readouterr().out)
    assert out["error"]["reason"] == "output_overwrites_source"
    assert src.read_text() == _SOL_SRC


def test_review_output_cannot_overwrite_manifest(tmp_path, capsys):
    src = tmp_path / "a.sol"
    src.write_text(_SOL_SRC)
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(sol.summarize_solidity(_SOL_SRC).to_dict())
    )
    with pytest.raises(SystemExit) as exc:
        sol.main_reuse(_sol_route_args(src, manifest, output=manifest))
    assert exc.value.code == 2
    out = json.loads(capsys.readouterr().out)
    assert out["error"]["reason"] == "output_overwrites_source"


def test_review_accept_rejects_undeclared_function(tmp_path, capsys):
    src = tmp_path / "a.sol"
    src.write_text(_SOL_SRC)
    manifest = tmp_path / "m.json"
    doc = sol.summarize_solidity(_SOL_SRC).to_dict()
    doc["functions"] = [f for f in doc["functions"] if f["name"] != "C.g"]
    manifest.write_text(json.dumps(doc))
    with pytest.raises(SystemExit):
        sol.main_accept(_sol_args(src, manifest, "g"))
    out = json.loads(capsys.readouterr().out)
    assert out["accepted"] is False
    assert out["reason"] == "undeclared_function"


def test_review_unsupported_ctor_is_gap_not_crash():
    src = """contract D {
  constructor(uint256 a) {
    assembly { let z := a }
  }
}
contract C {
  function f(uint256 a) public returns (uint256) {
    D d = new D(a);
    return a;
  }
}"""
    s = _fn(src, "f")
    # The ctor is unsupported — a per-function gap, never a
    # whole-report crash.
    assert not s.available or s.gaps
    whole = sol.summarize_solidity(src)
    assert whole.functions



def test_review_base_failure_reasons_all_propagate_as_gap():
    src = """contract C {
  function g(uint256 a) public pure returns (uint256) {
    return a;
  }
  function f(uint256 a) public returns (uint256) {
    return g(undeclared)[0];
  }
}"""
    s = _fn(src, "f")
    # Only `call_unresolved` used to propagate — a binding
    # failure inside the index base was silently dep-free and
    # still marked available.
    assert not s.available
    assert any(g.reason == "binding_unavailable" for g in s.gaps)



def test_review_comment_before_short_circuit_operator():
    src = """contract C {
  uint256 public s;
  function f(uint256 a, uint256 x) public returns (uint256) {
    s = a;
    bool ok = a > 0 /* hit */ && (s = x) > 0;
    return s;
  }
}"""
    s = _fn(src, "f")
    # A comment ahead of `&&` made `children[1]` a comment, so
    # the RHS ran unconditionally and dropped `a`'s dep.
    assert s.return_dependencies == frozenset({0, 1})



def test_review_virtual_dispatch_keeps_overload_groups_clean():
    src = """contract B {
  function g(uint256 x) public virtual returns (uint256) {
    return x;
  }
  function f(uint256 x) public returns (uint256) {
    return g(x);
  }
}
contract D is B {
  function g(uint256 x) public virtual override returns (uint256) {
    return super.g(x);
  }
}"""
    b = sol._Builder(src.encode())
    b.build()
    # The descendant candidate list used to be appended into
    # the shared overload group — `B.g` would keep `D.g` as a
    # candidate for later lookups (including `super.g()`).
    assert b._overload_groups["B.g"] == ["B.g"]



def test_review_modifier_sync_skips_shadowed_state_name():
    src = """contract C {
  uint256 public s;
  modifier m() { s = 7; _; }
  function f(uint256 s) public m returns (uint256) {
    return s;
  }
}"""
    s = _fn(src, "f")
    # The param `s` shadows the state var — syncing the
    # modifier's `s = 7` slot back must not clobber the
    # parameter's deps.
    assert s.return_dependencies == frozenset({0})



def test_review_block_scoped_state_slot_propagates():
    src = """contract C {
  uint256[] public arr;
  function f(uint256 a) public returns (uint256) {
    { arr.push(a); }
    return arr[0];
  }
}"""
    s = _fn(src, "f")
    assert s.return_dependencies == frozenset({0})


def test_review_loop_scoped_state_slot_propagates():
    src = """contract C {
  uint256[] public arr;
  function f(uint256 a, uint256 n) public returns (uint256) {
    for (uint256 i = 0; i < n; i++) { arr.push(a); }
    return arr[0];
  }
}"""
    s = _fn(src, "f")
    assert s.return_dependencies == frozenset({0, 1})


def test_review_multiple_named_arg_groups_fall_back_to_arity():
    src = """contract C {
  function g(uint256 x, uint256 y) public pure returns (uint256) {
    return x;
  }
  function f(uint256 a, uint256 b) public returns (uint256) {
    return g({x: a}, {x: b});
  }
}"""
    s = _fn(src, "f")
    # Two braced groups share one `named_args` dict — `x` would
    # collide. With no single group recorded, arity matching
    # applies and `x`'s dep is the first arg.
    assert s.available
    assert s.return_dependencies == frozenset({0})


def test_review6_storage_reference_alias_marks_state_write():
    # `uint256[] storage xs = arr` binds a local name to the state
    # variable's slot — `xs[0] = a` writes `arr`, not a local.
    src = """contract C {
  uint256[] public arr;
  function f(uint256 a) public returns (uint256) {
    uint256[] storage xs = arr;
    xs[0] = a;
    return arr[0];
  }
}"""
    s = _fn(src, "f")
    assert s.available
    assert s.effects == "state_writes"
    assert 0 in s.return_dependencies


def test_review6_scalar_storage_alias_writes_state():
    # Same for a scalar `storage` slot.
    src = """contract C {
  uint256 s;
  function f(uint256 a) public returns (uint256) {
    uint256 storage y = s;
    y = a;
    return s;
  }
}"""
    s = _fn(src, "f")
    assert s.available
    assert s.effects == "state_writes"
    assert 0 in s.return_dependencies


def test_review6_modifier_local_block_does_not_suppress_sync():
    # The modifier's own block decl (`uint256 s`) must not count
    # as body shadowing at `_;` — the state write still syncs in.
    src = """contract C {
  uint256 s;
  modifier m(uint256 v) { s = v; { uint256 s; _; } }
  function f(uint256 a) public m(a) returns (uint256) {
    return s;
  }
}"""
    s = _fn(src, "f")
    assert s.available
    assert 0 in s.return_dependencies


def test_review7_shadowing_decl_evicts_storage_alias():
    # After the block ends, a fresh `uint256 xs` shadows the
    # storage reference — reads must no longer forward to `arr`.
    src = """contract C {
  uint256[] arr;
  function f(uint256 a, uint256 b) public returns (uint256) {
    { uint256[] storage xs = arr; xs[0] = a; }
    uint256 xs = b;
    return xs;
  }
}"""
    s = _fn(src, "f")
    assert s.available
    assert s.return_dependencies == frozenset({1})


def test_review7_conditional_retarget_keeps_all_targets():
    # `if (c) { xs = other; }` may not run — after it `xs` can
    # still point at `arr`, so the write-through and the read
    # both keep `a`'s dep.
    src = """contract C {
  uint256[] arr;
  uint256[] other;
  bool c;
  function f(uint256 a) public returns (uint256) {
    uint256[] storage xs = arr;
    if (c) { xs = other; }
    xs[0] = a;
    return arr[0];
  }
}"""
    s = _fn(src, "f")
    assert s.available
    assert s.effects == "state_writes"
    assert 0 in s.return_dependencies


def test_review7_inner_shadow_restores_outer_alias():
    # `{ uint256 xs = 0; }` shadows only inside its block — the
    # outer storage pointer survives the block end.
    src = """contract C {
  uint256[] arr;
  function f(uint256 a) public returns (uint256) {
    uint256[] storage xs = arr;
    { uint256 xs = 0; }
    xs[0] = a;
    return arr[0];
  }
}"""
    s = _fn(src, "f")
    assert s.available
    assert s.effects == "state_writes"
    assert 0 in s.return_dependencies


def test_review7_storage_rebind_retargets_pointer():
    # `xs = other` retargets the storage pointer — the indexed
    # write after it must land on `other`, not keep hitting `arr`.
    src = """contract C {
  uint256[] arr;
  uint256[] other;
  function f(uint256 a) public returns (uint256) {
    uint256[] storage xs = arr;
    xs[0] = a;
    xs = other;
    xs[1] = a;
    return other[1];
  }
}"""
    s = _fn(src, "f")
    assert s.available
    assert s.effects == "state_writes"
    assert 0 in s.return_dependencies


# -- cross-file import resolution (`--resolve-modules` contract) ---------

B_MOD = """library L {
  function dbl(uint256 a) internal returns (uint256) {
    return a + a;
  }
}
function helper(uint256 a) returns (uint256) {
  return a + dbl_local(a);
}
function dbl_local(uint256 a) returns (uint256) {
  return a + a;
}
contract Base {
  function bf(uint256 v) public returns (uint256) {
    return v;
  }
}
struct SB {
  uint256 v;
}"""

C_MOD = """function helper(uint256 a) returns (uint256) {
  return a + 2;
}"""


def _resolver(modules):
    def resolve(spec, importer_path=None):
        return modules.get(spec)

    return resolve


def _summarize_mods(root, modules, **kw):
    return sol.summarize_solidity(
        root, resolver=_resolver(modules), **kw
    )


def test_import_star_free_fn_and_library_and_ancestor():
    src = """import "./b.sol";
contract A is Base {
  function f(uint256 x) public returns (uint256) {
    return L.dbl(x) + helper(x) + bf(x);
  }
}"""
    s = _summarize_mods(src, {"./b.sol": B_MOD})
    f = next(fn for fn in s.functions if fn.name == "A.f")
    assert f.available
    assert f.return_dependencies == frozenset({0})
    assert f.gaps == []
    names = {fn.name for fn in s.functions}
    assert "b.helper" in names
    assert "b.B.bf" not in names  # Base, not B
    assert "b.Base.bf" in names


def test_import_named_binding_and_rename():
    src = """import {helper as hh} from "./b.sol";
function af(uint256 x) returns (uint256) {
  return hh(x);
}"""
    s = _summarize_mods(src, {"./b.sol": B_MOD})
    af = next(fn for fn in s.functions if fn.name == "af")
    assert af.available
    assert af.return_dependencies == frozenset({0})
    # Only the listed symbol is bound — `helper` itself is not.
    src2 = """import {helper as hh} from "./b.sol";
function af(uint256 x) returns (uint256) {
  return helper(x);
}"""
    s2 = _summarize_mods(src2, {"./b.sol": B_MOD})
    af2 = next(fn for fn in s2.functions if fn.name == "af")
    assert not af2.available
    assert af2.gaps


def test_import_alias_namespace_call():
    for form in (
        'import "./b.sol" as D;',
        'import * as D from "./b.sol";',
    ):
        src = form + """
function af(uint256 x) returns (uint256) {
  return D.helper(x);
}"""
        s = _summarize_mods(src, {"./b.sol": B_MOD})
        af = next(fn for fn in s.functions if fn.name == "af")
        assert af.available, form
        assert af.return_dependencies == frozenset({0})


def test_import_ambiguous_name_stays_unresolved():
    src = """import "./b.sol";
import "./c.sol";
function af(uint256 x) returns (uint256) {
  return helper(x);
}"""
    s = _summarize_mods(
        src, {"./b.sol": B_MOD, "./c.sol": C_MOD}
    )
    af = next(fn for fn in s.functions if fn.name == "af")
    assert not af.available
    assert af.gaps


def test_import_unresolved_stays_opaque():
    src = """import "./missing.sol";
function af(uint256 x) returns (uint256) {
  return helper(x);
}"""
    s = _summarize_mods(src, {})
    af = next(fn for fn in s.functions if fn.name == "af")
    assert not af.available
    assert af.gaps


def test_import_no_reexport():
    # The importer sees the module's own symbols only — c.sol's
    # names do not leak through b.sol.
    b_reexport = """import "./c.sol";
function bf(uint256 a) returns (uint256) {
  return helper(a);
}"""
    src = """import "./b.sol";
function af(uint256 x) returns (uint256) {
  return helper(x);
}"""
    s = _summarize_mods(
        src, {"./b.sol": b_reexport, "./c.sol": C_MOD}
    )
    # b's own `bf` still resolves `helper` through b's scope.
    bf = next(fn for fn in s.functions if fn.name == "b.bf")
    assert bf.available
    assert bf.return_dependencies == frozenset({0})
    # The root module does not see c's `helper`.
    af = next(fn for fn in s.functions if fn.name == "af")
    assert not af.available
    assert af.gaps


def test_import_new_contract_and_ctor():
    b_ctor = """contract P {
  uint256 public n;
  constructor(uint256 v) {
    n = v;
  }
}"""
    src = """import "./b.sol";
function af(uint256 x) returns (uint256) {
  return new P(x).n();
}"""
    s = _summarize_mods(src, {"./b.sol": b_ctor})
    af = next(fn for fn in s.functions if fn.name == "af")
    # The ctor runs inline — the deployment call is recorded, not
    # a gap.
    assert af.gaps == []


def test_import_using_for_across_files():
    src = """import "./b.sol";
contract A {
  using L for uint256;
  function f(uint256 x) public returns (uint256) {
    return x.dbl();
  }
}"""
    s = _summarize_mods(src, {"./b.sol": B_MOD})
    f = next(fn for fn in s.functions if fn.name == "A.f")
    assert f.available
    assert f.return_dependencies == frozenset({0})


def test_import_cycle_stays_opaque():
    a_src = """import "./b.sol";
function af(uint256 x) returns (uint256) {
  return bf(x);
}"""
    b_src = """import "./a.sol";
function bf(uint256 x) returns (uint256) {
  return af(x);
}"""
    s = _summarize_mods(
        a_src, {"./b.sol": b_src, "./a.sol": a_src}
    )
    # No crash; the cyclic edge simply does not register names.
    af = next(fn for fn in s.functions if fn.name == "af")
    assert af is not None


def test_import_context_key_covers_module_bytes():
    src = """import "./b.sol";
function af(uint256 x) returns (uint256) {
  return helper(x);
}"""
    v1 = _summarize_mods(src, {"./b.sol": B_MOD})
    v2 = _summarize_mods(src, {"./b.sol": C_MOD})
    assert v1.context_key != v2.context_key
    # A resolver-free derivation of the same root hashes exactly
    # as before (back-compat).
    plain = sol.summarize_solidity(src)
    assert plain.context_key != v1.context_key


def test_import_own_name_shadows_import():
    src = """import "./b.sol";
function helper(uint256 a) returns (uint256) {
  return a;
}
function af(uint256 x) returns (uint256) {
  return helper(x);
}"""
    s = _summarize_mods(src, {"./b.sol": B_MOD})
    af = next(fn for fn in s.functions if fn.name == "af")
    # `helper` is contributed by the import AND declared locally —
    # ambiguous, so it stays unresolved rather than wrong-picking.
    assert not af.available
    assert af.gaps


def test_import_fs_resolver(tmp_path):
    (tmp_path / "b.sol").write_text(B_MOD)
    (tmp_path / "a.sol").write_text(
        """import "./b.sol";
function af(uint256 x) returns (uint256) {
  return helper(x);
}"""
    )
    root = (tmp_path / "a.sol").resolve()
    s = sol.summarize_solidity(
        (tmp_path / "a.sol").read_text(),
        resolver=sol._fs_resolver,
        source_path=str(root),
    )
    af = next(fn for fn in s.functions if fn.name == "af")
    assert af.available
    assert af.return_dependencies == frozenset({0})


def test_import_fs_resolver_confined(tmp_path):
    outside = tmp_path.parent / "outside_mod.sol"
    outside.write_text(C_MOD)
    (tmp_path / "a.sol").write_text(
        """import "../outside_mod.sol";
function af(uint256 x) returns (uint256) {
  return helper(x);
}"""
    )
    try:
        s = sol.summarize_solidity(
            (tmp_path / "a.sol").read_text(),
            resolver=sol._fs_resolver,
            source_path=str((tmp_path / "a.sol").resolve()),
        )
        af = next(fn for fn in s.functions if fn.name == "af")
        # `../` escapes the importer's tree — stays opaque.
        assert not af.available
    finally:
        outside.unlink(missing_ok=True)


def test_import_cross_category_name_collision_is_ambiguous():
    # `contract X` from one import and `function X` from another
    # share one namespace — same-name different-kind must be
    # ambiguous, never a wrong pick on `X(...)`.
    b_mod = "contract X { function xf(uint256 v) public returns (uint256) { return v; } }"
    c_mod = "function X(uint256 a) returns (uint256) { return a; }"
    src = """import "./b.sol";
import "./c.sol";
function af(uint256 x) returns (uint256) {
  return X(x);
}"""
    s = _summarize_mods(
        src, {"./b.sol": b_mod, "./c.sol": c_mod}
    )
    af = next(fn for fn in s.functions if fn.name == "af")
    assert not af.available
    assert af.gaps


def test_import_alias_collision_with_own_contract_is_ambiguous():
    # `import "b.sol" as C` while the root module declares its own
    # contract C — the ambiguous `C` binds to neither: `C.helper(x)`
    # degrades to an opaque external member call (deps preserved,
    # effects unknown) rather than wrong-picking b.helper or C.cf.
    b_mod = "function helper(uint256 a) returns (uint256) { return a; }"
    src = """import "./b.sol" as C;
contract C {
  function cf(uint256 v) public returns (uint256) { return v; }
}
function af(uint256 x) returns (uint256) {
  return C.helper(x);
}"""
    s = _summarize_mods(src, {"./b.sol": b_mod})
    af = next(fn for fn in s.functions if fn.name == "af")
    assert af.available
    assert af.effects == "unknown"
    assert {c.callee for c in af.calls} == {"C.helper"}


def test_failed_resolution_does_not_break_resolved_paths_outparam():
    # An unresolvable import caches None in module_cache — the
    # resolved_paths out-param must not trip over it.
    resolved = set()
    src = """import "./missing.sol";
function af(uint256 a) returns (uint256) { return a; }"""
    s = sol.summarize_solidity(
        src,
        resolver=lambda spec, imp: None,
        source_path="/tmp/x.sol",
        resolved_paths=resolved,
    )
    assert resolved == set()
    assert s.functions[0].available


def test_import_cycle_via_filesystem_resolver_terminates(tmp_path):
    # a.sol <-> b.sol mutual imports: the cached resolution of a
    # module still on the scan stack must not re-enter its
    # `_scan_module` frame — before the mid-scan token guard this
    # ping-ponged into RecursionError.
    (tmp_path / "a.sol").write_text(
        'import "./b.sol";\n'
        "function fa(uint256 x) returns (uint256) { return fb(x); }\n"
    )
    (tmp_path / "b.sol").write_text(
        'import "./a.sol";\n'
        "function fb(uint256 x) returns (uint256) { return x; }\n"
    )
    src = (tmp_path / "a.sol").read_bytes()
    s = sol.summarize_solidity(
        src,
        resolver=sol._fs_resolver,
        source_path=str(tmp_path / "a.sol"),
    )
    names = {fn.name for fn in s.functions}
    assert "b.fb" in names
    fa = next(fn for fn in s.functions if fn.name == "fa")
    assert fa.available
    assert fa.return_dependencies == frozenset({0})


def test_import_same_file_two_specifiers_stays_resolvable():
    # `import "./b.sol"` and `import "b.sol"` naming the same bytes
    # must merge once — the second directive re-binding the same
    # internal names is idempotent, not an ambiguity.
    src = """import "./b.sol";
import "b.sol";
function use(uint256 x) returns (uint256) {
  return helper(x);
}"""
    s = _summarize_mods(src, {"./b.sol": B_MOD, "b.sol": B_MOD})
    use = next(fn for fn in s.functions if fn.name == "use")
    assert use.available
    assert use.return_dependencies == frozenset({0})
    assert {fn.name for fn in s.functions} >= {"b.helper"}


def test_import_named_then_star_overlap_stays_resolvable():
    src = """import {helper} from "./b.sol";
import "./b.sol";
function use(uint256 x) returns (uint256) {
  return helper(x);
}"""
    s = _summarize_mods(src, {"./b.sol": B_MOD})
    use = next(fn for fn in s.functions if fn.name == "use")
    assert use.available


def test_import_same_spec_different_content_keeps_both_modules():
    # A pathless resolver returning source text keys refs on the
    # specifier — two importers resolving the same spec to
    # different bytes must keep both modules instead of the second
    # riding the first's identity.
    b_one = "function fb(uint256 a) returns (uint256) { return a; }"
    b_two = "function fg(uint256 a) returns (uint256) { return a + 1; }"
    a_mod = """import "./b.sol";
function fa(uint256 x) returns (uint256) { return fb(x); }"""
    c_mod = """import "./b.sol";
function fc(uint256 x) returns (uint256) { return fg(x); }"""
    root = """import "./a.sol";
import "./c.sol";
function run(uint256 x) returns (uint256) { return fc(x); }"""

    def resolver(spec, importer_path=None):
        if spec == "./b.sol" and importer_path == "./c.sol":
            return b_two
        return {"./a.sol": a_mod, "./c.sol": c_mod, "./b.sol": b_one}.get(
            spec
        )

    s = sol.summarize_solidity(root, resolver=resolver)
    names = {fn.name for fn in s.functions}
    assert {"b.fb", "b#2.fg"} <= names
    fc = next(fn for fn in s.functions if fn.name == "c.fc")
    assert fc.available
    run = next(fn for fn in s.functions if fn.name == "run")
    assert run.available


def test_analysis_limit_still_reports_resolved_paths():
    # A resolved module pushing the unit over MAX_FUNCTIONS raises
    # `analysis_limit` before the manifest is built — the
    # `resolved_paths` out-param must already carry the module so
    # the route's `--output` overwrite guard still refuses to
    # clobber it.
    big = "\n".join(
        f"function m{i}(uint256 x) returns (uint256) {{ return x; }}"
        for i in range(sol.MAX_FUNCTIONS + 2)
    )
    resolved = set()
    src = 'import "./big.sol";\nfunction r(uint256 x) returns (uint256) { return x; }'
    s = sol.summarize_solidity(
        src,
        resolver=_resolver({"./big.sol": big}),
        resolved_paths=resolved,
    )
    assert resolved == {"./big.sol"}
    assert all(not fn.available for fn in s.functions)


def test_mcp_sol_summaries_accepts_cli_resolved_manifest(tmp_path):
    # A manifest produced by the CLI with `--resolve-modules` is
    # verifiable through the MCP tools when they resolve the same
    # modules — without `resolve_modules` the fresh context key
    # cannot match.
    from agent import mcp_server

    (tmp_path / "b.sol").write_text(
        "function helper(uint256 a) returns (uint256) { return a; }\n"
    )
    a = tmp_path / "a.sol"
    a.write_text(
        'import "./b.sol";\n'
        "function af(uint256 x) returns (uint256) { return helper(x); }\n"
    )
    produced = json.loads(
        mcp_server.sol_summaries(str(a), resolve_modules=True)
    )
    manifest = produced["manifest"]
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    check = json.loads(
        mcp_server.sol_summaries_check(
            str(a), str(manifest_path), resolve_modules=True
        )
    )
    assert check["check"]["context_match"] is True


def test_import_same_content_different_files_scan_per_location(tmp_path):
    # `a/b.sol` and `c/b.sol` carry identical bytes but are two
    # files — `./d.sol` inside each binds per location. Content-
    # keyed module identity would scan only the first and miss
    # `c/d.sol` entirely.
    (tmp_path / "a").mkdir()
    (tmp_path / "c").mkdir()
    shared = (
        'import "./d.sol";\n'
        "function fb(uint256 x) returns (uint256) { return fd(x); }\n"
    )
    (tmp_path / "a" / "b.sol").write_text(shared)
    (tmp_path / "c" / "b.sol").write_text(shared)
    (tmp_path / "a" / "d.sol").write_text(
        "function fd(uint256 x) returns (uint256) { return x; }\n"
    )
    (tmp_path / "c" / "d.sol").write_text(
        "function fd(uint256 x) returns (uint256) { return x + 1; }\n"
    )
    src = (
        'import {fb as f1} from "a/b.sol";\n'
        'import {fb as f2} from "c/b.sol";\n'
        "function run(uint256 x) returns (uint256) {\n"
        "  return f1(x) + f2(x);\n"
        "}\n"
    )
    resolved = set()
    s = sol.summarize_solidity(
        src,
        resolver=sol._fs_resolver,
        source_path=str(tmp_path / "main.sol"),
        resolved_paths=resolved,
    )
    names = {fn.name for fn in s.functions}
    assert {"b.fb", "b#2.fb", "d.fd", "d#2.fd"} <= names
    fb1 = next(fn for fn in s.functions if fn.name == "b.fb")
    fb2 = next(fn for fn in s.functions if fn.name == "b#2.fb")
    assert fb1.available and fb2.available
    # Both directories' `d.sol` were actually resolved — under
    # content-keyed identity `c/d.sol` was never scanned.
    assert resolved == {
        str(tmp_path / "a" / "b.sol"),
        str(tmp_path / "c" / "b.sol"),
        str(tmp_path / "a" / "d.sol"),
        str(tmp_path / "c" / "d.sol"),
    }


def test_import_nested_resolution_uses_unsuffixed_reference():
    # One specifier serving different bytes per importer gets a
    # display ref (`./b.sol#@<digest>`) — nested imports inside
    # that module must still query the resolver with the
    # reference it understands, or its dependencies never
    # resolve.
    b_one = "function fb(uint256 a) returns (uint256) { return a; }"
    d_mod = "function fd(uint256 a) returns (uint256) { return a + 1; }"
    b_two = (
        'import "./d.sol";\n'
        "function fg(uint256 a) returns (uint256) { return fd(a); }"
    )
    a_mod = (
        'import "./b.sol";\n'
        "function fa(uint256 x) returns (uint256) { return fb(x); }"
    )
    c_mod = (
        'import "./b.sol";\n'
        "function fc(uint256 x) returns (uint256) { return fg(x); }"
    )
    root = (
        'import "./a.sol";\n'
        'import "./c.sol";\n'
        "function run(uint256 x) returns (uint256) { return fc(x); }"
    )

    def resolver(spec, importer_path=None):
        if spec == "./d.sol" and importer_path == "./b.sol":
            return d_mod
        if spec == "./b.sol" and importer_path == "./c.sol":
            return b_two
        return {
            "./a.sol": a_mod,
            "./c.sol": c_mod,
            "./b.sol": b_one,
        }.get(spec)

    s = sol.summarize_solidity(root, resolver=resolver)
    names = {fn.name for fn in s.functions}
    assert {"b.fb", "b#2.fg", "d.fd"} <= names
    fg = next(fn for fn in s.functions if fn.name == "b#2.fg")
    assert fg.available
    assert fg.return_dependencies == frozenset({0})


def test_import_same_named_struct_different_decls_is_ambiguous():
    # `struct SB` from the import and a locally declared `struct
    # SB` are different declarations — the name collides rather
    # than re-binding, so using it stays unresolved.
    src = """import "./b.sol";
struct SB { uint256 w; }
function af(uint256 x) returns (uint256) {
  SB memory s = SB(x);
  return s.w;
}"""
    s = _summarize_mods(src, {"./b.sol": B_MOD})
    af = next(fn for fn in s.functions if fn.name == "af")
    assert not af.available
    assert af.gaps


def _reads(s: sol.SolFunctionSummary) -> dict:
    return {r.span: r.deps for r in s.statement_reads}


def test_statement_reads_attribute_per_statement():
    src = """contract C {
  function f(uint256 a, uint256 b) public pure returns (uint256) {
    uint256 x = a + 1;
    uint256 y = b;
    return x + y;
  }
}"""
    s = _fn(src, "f")
    assert s.available
    reads = _reads(s)
    decl_a = next(
        r for span, r in reads.items()
        if src.index("uint256 x") <= span[0] and span[1] <= src.index(";") + 1
    )
    assert decl_a == frozenset({0})
    ret_span = (
        src.index("return x + y"),
        src.index("return x + y") + len("return x + y"),
    )
    # The return statement's span includes its `;` — find it by
    # containment of the return keyword.
    ret = next(
        r for span, r in reads.items()
        if span[0] <= ret_span[0] < span[1]
    )
    assert ret == frozenset({0, 1})


def test_statement_reads_declaration_initializers():
    # A declarator's RHS records on the statement even though the
    # bound name's own read is deferred.
    src = """contract C {
  function f(uint256 a) public pure returns (uint256) {
    uint256 x = a;
    return 0;
  }
}"""
    s = _fn(src, "f")
    assert s.available
    assert frozenset({0}) in _reads(s).values()


def test_statement_reads_nested_attribution():
    # Reads inside an if-body attribute to the inner statement's
    # own span AND the enclosing if statement.
    src = """contract C {
  function f(uint256 a) public pure returns (uint256) {
    uint256 y = 0;
    if (a > 0) {
      y = a;
    }
    return y;
  }
}"""
    s = _fn(src, "f")
    assert s.available
    reads = _reads(s)
    assert list(reads.values()).count(frozenset({0})) >= 2


def test_statement_reads_modifier_body_attribution():
    # An inlined modifier's body statements record under the
    # modifier's own spans in the caller's summary.
    src = """contract C {
  modifier m(uint256 v) {
    uint256 t = v + 1;
    _;
  }
  function f(uint256 a) public m(a) returns (uint256) {
    return 0;
  }
}"""
    s = _fn(src, "f")
    assert s.available
    assert frozenset({0}) in _reads(s).values()


def test_statement_reads_call_actual_records():
    # A call to an opaque callee still reads its actual: `g(a)`
    # records {0} on the statement even though the result is
    # dropped.
    src = """contract C {
  function g(uint256 v) public pure returns (uint256) {
    return 0;
  }
  function f(uint256 a) public pure returns (uint256) {
    g(a);
    return 0;
  }
}"""
    s = _fn(src, "f")
    assert s.available
    assert frozenset({0}) in _reads(s).values()


def test_statement_reads_absent_when_gapped():
    # A gapped walk still attaches what was recorded before the
    # gap — but the summary stays unavailable.
    src = """contract C {
  function f(uint256 a) public pure returns (uint256) {
    uint256 x = a;
    return x + unknown_call();
  }
}"""
    s = _fn(src, "f")
    if not s.available:
        assert s.gaps


def test_statement_reads_roundtrip():
    src = """contract C {
  function f(uint256 a) public pure returns (uint256) {
    return a;
  }
}"""
    s = _summarize(src)
    restored = sol.SolSummarySet.from_dict(s.to_dict())
    fn = next(f for f in restored.functions if f.name.endswith(".f"))
    orig = next(f for f in s.functions if f.name.endswith(".f"))
    assert fn.statement_reads == orig.statement_reads


def test_statement_reads_manifest_optional():
    # Manifests predating the field restore without it.
    src = """contract C {
  function f(uint256 a) public pure returns (uint256) {
    return a;
  }
}"""
    s = _summarize(src).to_dict()
    for f in s["functions"]:
        f.pop("statement_reads", None)
    restored = sol.SolSummarySet.from_dict(s)
    assert all(fn.statement_reads == () for fn in restored.functions)


def test_statement_reads_augmented_and_update_operands():
    # `a += b` reads the old LHS value; `a++` reads `a` — both
    # were evaluated without _expr seeing the operand.
    src = """contract C {
  function f(uint256 a, uint256 b) public pure returns (uint256) {
    uint256 x = a;
    x++;
    x += b;
    return x;
  }
}"""
    s = _fn(src, "f")
    assert s.available
    reads = _reads(s)
    inc = next(
        r for span, r in reads.items()
        if span[0] <= src.index("x++") < span[1]
    )
    assert inc == frozenset({0})
    aug = next(
        r for span, r in reads.items()
        if span[0] <= src.index("x += b") < span[1]
    )
    assert aug == frozenset({0, 1})


def test_statement_reads_bare_return_named_result():
    # `return;` reads back the named result slot — dep {0}.
    src = """contract C {
  function f(uint256 a) public pure returns (uint256 r) {
    r = a;
    return;
  }
}"""
    s = _fn(src, "f")
    assert s.available
    idx = src.index("return;")
    ret = next(
        r for span, r in _reads(s).items()
        if span[0] <= idx < span[1]
    )
    assert ret == frozenset({0})


def test_statement_reads_imported_modifier_module_tag():
    # A modifier inlined from another module records under that
    # module's token; the function body reached via `_;` keeps
    # the importer's "".
    b_mod = """contract Base {
  modifier m(uint256 v) {
    uint256 t = v + 1;
    _;
  }
}"""
    src = """import "./b.sol";
contract A is Base {
  function f(uint256 a) public m(a) returns (uint256) {
    return a;
  }
}"""
    s = _summarize_mods(src, {"./b.sol": b_mod})
    fn = next(f for f in s.functions if f.name == "A.f")
    assert fn.available
    mods = {r.module for r in fn.statement_reads}
    assert "b" in mods
    assert "" in mods


def test_statement_reads_module_tag_roundtrip():
    # Imported-module statements carry the module token; the
    # importer's own statements carry "".
    src = """contract C {
  function f(uint256 a) public pure returns (uint256) {
    return a;
  }
}"""
    s = _summarize(src)
    fn = next(f for f in s.functions if f.name.endswith(".f"))
    assert all(r.module == "" for r in fn.statement_reads)
    restored = sol.SolSummarySet.from_dict(s.to_dict())
    rfn = next(f for f in restored.functions if f.name.endswith(".f"))
    assert rfn.statement_reads == fn.statement_reads


# --- slice: --summary-aware-calls fold (issue #900, Sol port) ----------------

def _callee_manifest(*functions) -> sol.SolSummarySet:
    return sol.SolSummarySet.from_dict(
        {
            "schema_version": sol.PROFILE,
            "context_key": "declared-context",
            "functions": list(functions),
        }
    )


def _decl_fn(name, params, deps, effects="none_in_supported_fragment", **over):
    d = {
        "name": name,
        "contract": "",
        "available": True,
        "parameters": list(params),
        "return_dependencies": None if deps is None else sorted(deps),
        "calls": [],
        "gaps": [],
        "effects": effects,
        "statement_reads": [],
    }
    if deps is None:
        d["available"] = False
        d["gaps"] = [{"reason": "binding_unavailable", "byte": 0}]
    d.update(over)
    return d


_CALLER = (
    "contract C {"
    " function f(uint256 a, uint256 b) public returns (uint256) {"
    "   return ext.g(a, b); } }"
)


def _aware(source, *functions) -> sol.SolSummarySet:
    return sol.summarize_solidity(
        source, declared=_callee_manifest(*functions)
    )


def _result(s: sol.SolSummarySet, name="C.f") -> sol.SolFunctionSummary:
    return next(f for f in s.functions if f.name == name)


def test_summary_aware_call_folds_declared_return_dependencies():
    s = _aware(_CALLER, _decl_fn("g", ("a", "b"), {0}))
    f = _result(s)
    # The opaque approximation unions both actuals; the declared
    # summary folds only `a` (= actual 0).
    assert f.available and f.return_dependencies == frozenset({0})
    (call,) = f.calls
    assert call.callee == "ext.g"
    assert call.result_dependencies == frozenset({0})
    # `effects` stays `unknown` — the manifest cannot bound writes
    # through argument objects.
    assert f.effects == "unknown"
    assert s.call_modeling == {
        "summary_modeled_calls": 1,
        "opaque_calls": 0,
        "summary_unmatched": 0,
    }


def test_summary_aware_call_module_token_prefix_matches():
    # `ext.Lib.g` — the base's last segment is a module token
    # prefix over the callee's standalone name `Lib.g`.
    src = (
        "contract C {"
        " function f(uint256 a, uint256 b) public returns (uint256) {"
        "   return ext.Lib.g(a, b); } }"
    )
    s = _aware(src, _decl_fn("Lib.g", ("a", "b"), {0}))
    f = _result(s)
    assert f.return_dependencies == frozenset({0})
    (call,) = f.calls
    assert call.result_dependencies == frozenset({0})


def test_summary_aware_call_deep_qualifier_never_folds():
    # `a.b.g` splits as token `a` + name `b.g` — a bare `g` entry
    # never folds: the qualifier is not a single module token.
    src = (
        "contract C {"
        " function f(uint256 a, uint256 b) public returns (uint256) {"
        "   return a.b.g(a, b); } }"
    )
    s = _aware(src, _decl_fn("g", ("a", "b"), {0}))
    f = _result(s)
    assert f.return_dependencies == frozenset({0, 1})
    assert s.call_modeling["summary_unmatched"] == 1


def test_summary_aware_call_unmatched_name_stays_opaque():
    s = _aware(_CALLER, _decl_fn("h", ("a", "b"), {0}))
    f = _result(s)
    assert f.return_dependencies == frozenset({0, 1})
    (call,) = f.calls
    assert call.result_dependencies == frozenset({0, 1})
    assert s.call_modeling == {
        "summary_modeled_calls": 0,
        "opaque_calls": 1,
        "summary_unmatched": 1,
    }


def test_summary_aware_call_gapped_entry_stays_opaque():
    s = _aware(_CALLER, _decl_fn("g", ("a", "b"), None))
    f = _result(s)
    (call,) = f.calls
    assert call.result_dependencies == frozenset({0, 1})
    # A name hit still counts as referenced, folded or not.
    assert s.call_modeling["summary_unmatched"] == 0


def test_summary_aware_call_arity_mismatch_stays_opaque():
    s = _aware(_CALLER, _decl_fn("g", ("a",), {0}))
    f = _result(s)
    (call,) = f.calls
    assert call.result_dependencies == frozenset({0, 1})


def test_summary_aware_call_out_of_range_dep_stays_opaque():
    # `from_dict` rejects the entry as malformed — the runtime gate
    # is exercised through a directly built set.
    bad = sol.SolFunctionSummary(
        name="g",
        contract="",
        params=("a", "b"),
        available=True,
        return_dependencies=frozenset({2}),
        calls=[],
        gaps=[],
    )
    s = sol.summarize_solidity(
        _CALLER,
        declared=sol.SolSummarySet("declared-context", [bad]),
    )
    f = _result(s)
    (call,) = f.calls
    assert call.result_dependencies == frozenset({0, 1})


def test_manifest_rejects_an_out_of_range_ordinal():
    s = sol.summarize_solidity(_SOL_SRC).to_dict()
    s["functions"][0]["return_dependencies"] = [1]
    with pytest.raises(ValueError, match="malformed"):
        sol.SolSummarySet.from_dict(s)


def test_summary_aware_call_options_are_not_parameters():
    # `ext.g{value: b}(a)` — the options group is appended as one
    # trailing actual entry, so a 2-param manifest must NOT match:
    # folding `deps={0}` would drop `b`'s deps.
    src = (
        "contract C {"
        " function f(uint256 a, uint256 b) public returns (uint256) {"
        "   return ext.g{value: b}(a); } }"
    )
    s = _aware(src, _decl_fn("g", ("x", "y"), {0}))
    f = _result(s)
    (call,) = f.calls
    assert call.result_dependencies == frozenset({0, 1})
    assert s.call_modeling["summary_modeled_calls"] == 0
    assert s.call_modeling["opaque_calls"] == 1


def test_summary_aware_call_options_fold_over_real_args():
    # With a manifest matching the real arity the call folds —
    # and the option value's deps ride the result like the
    # receiver's, since the manifest does not describe them.
    src = (
        "contract C {"
        " function f(uint256 a, uint256 b) public returns (uint256) {"
        "   return ext.g{value: b}(a); } }"
    )
    s = _aware(src, _decl_fn("g", ("x",), {0}))
    f = _result(s)
    (call,) = f.calls
    assert call.result_dependencies == frozenset({0, 1})
    assert s.call_modeling["summary_modeled_calls"] == 1


def test_summary_aware_empty_manifest_counts_opaque():
    s = _aware(_CALLER)
    assert s.call_modeling == {
        "summary_modeled_calls": 0,
        "opaque_calls": 1,
        "summary_unmatched": 0,
    }


def test_summary_aware_opaque_call_counted_once_per_call():
    # `caller` walks first and summarizes `helper` inline; the
    # top-level loop must not recount helper's opaque call.
    src = (
        "contract C {"
        " function caller(uint256 a) public returns (uint256) {"
        "   return helper(a); }"
        " function helper(uint256 x) internal returns (uint256) {"
        "   return ext.g(x); } }"
    )
    s = _aware(src)
    assert s.call_modeling["opaque_calls"] == 1


def test_summary_aware_call_named_arguments_stay_opaque():
    src = (
        "contract C {"
        " function f(uint256 a, uint256 b) public returns (uint256) {"
        "   return ext.g({a: a, b: b}); } }"
    )
    s = _aware(src, _decl_fn("g", ("a", "b"), {0}))
    f = _result(s)
    (call,) = f.calls
    # Declared ordinals are positional — named arguments rebind
    # them, so the call keeps the opaque union.
    assert call.result_dependencies == frozenset({0, 1})


def test_summary_aware_call_discarded_result_stays_opaque():
    src = (
        "contract C {"
        " function f(uint256 a, uint256 b) public returns (uint256) {"
        "   ext.g(a, b); return a; } }"
    )
    s = _aware(src, _decl_fn("g", ("a", "b"), {0}))
    f = _result(s)
    (call,) = f.calls
    assert call.result_dependencies is None
    assert s.call_modeling["summary_modeled_calls"] == 0


def test_summary_aware_calls_absent_manifest_has_no_modeling():
    s = sol.summarize_solidity(_CALLER)
    assert s.call_modeling is None
    assert "call_modeling" not in s.to_dict()


def test_summary_aware_calls_context_key_binds_manifest():
    a = _aware(_CALLER, _decl_fn("g", ("a", "b"), {0}))
    b = _aware(_CALLER, _decl_fn("g", ("a", "b"), {1}))
    assert a.context_key != b.context_key
    same = _aware(_CALLER, _decl_fn("g", ("a", "b"), {0}))
    assert a.context_key == same.context_key
    plain = sol.summarize_solidity(_CALLER)
    assert a.context_key != plain.context_key


def test_summary_aware_calls_manifest_roundtrips_modeling():
    s = _aware(_CALLER, _decl_fn("g", ("a", "b"), {0}))
    restored = sol.SolSummarySet.from_dict(s.to_dict())
    assert restored.call_modeling == s.call_modeling


def _sol_aware_args(source, manifest, callee, output=None):
    return type(
        "A",
        (),
        {
            "source": str(source),
            "manifest": str(manifest),
            "output": str(output) if output else None,
            "summary_aware_calls": str(callee),
        },
    )()


_LIB_SRC = (
    "contract Lib {"
    " function g(uint256 a, uint256 b) public returns (uint256) {"
    "   return a; } }"
)


def _produce(tmp_path, capsys, src_path):
    sol.main(_sol_args(src_path))
    manifest = tmp_path / (src_path.stem + "-manifest.json")
    manifest.write_text(capsys.readouterr().out)
    return manifest


def test_check_route_folded_manifest_stays_checkable(tmp_path, capsys):
    lib = tmp_path / "lib.sol"
    lib.write_text(_LIB_SRC)
    lib_manifest = _produce(tmp_path, capsys, lib)
    caller = tmp_path / "caller.sol"
    caller.write_text(
        "contract C {"
        " function f(uint256 a, uint256 b) public returns (uint256) {"
        "   return ext.Lib.g(a, b); } }"
    )
    caller_manifest = _produce(tmp_path, capsys, caller)
    # Re-derive with the flag and compare — folded records are
    # checkable like any other.
    out_manifest = tmp_path / "aware.json"
    sol.main(
        type(
            "A",
            (),
            {
                "source": str(caller),
                "resolve_modules": False,
                "summary_aware_calls": str(lib_manifest),
            },
        )()
    )
    out_manifest.write_text(capsys.readouterr().out)
    doc = json.loads(out_manifest.read_text())
    assert doc["call_modeling"]["summary_modeled_calls"] == 1
    sol.main_check(
        _sol_aware_args(caller, out_manifest, lib_manifest)
    )
    check = json.loads(capsys.readouterr().out)
    assert check["context_match"] is True
    assert check["reusable"] == ["C.f"]


def test_check_route_changed_callee_manifest_breaks_context(
    tmp_path, capsys
):
    lib = tmp_path / "lib.sol"
    lib.write_text(_LIB_SRC)
    lib_manifest = _produce(tmp_path, capsys, lib)
    caller = tmp_path / "caller.sol"
    caller.write_text(
        "contract C {"
        " function f(uint256 a, uint256 b) public returns (uint256) {"
        "   return ext.Lib.g(a, b); } }"
    )
    sol.main(
        type(
            "A",
            (),
            {
                "source": str(caller),
                "resolve_modules": False,
                "summary_aware_calls": str(lib_manifest),
            },
        )()
    )
    caller_manifest = tmp_path / "caller-manifest.json"
    caller_manifest.write_text(capsys.readouterr().out)
    # Flip a declared dep ordinal — same sources, changed manifest.
    doc = json.loads(lib_manifest.read_text())
    doc["functions"][0]["return_dependencies"] = [1]
    lib_manifest.write_text(json.dumps(doc))
    sol.main_check(
        _sol_aware_args(caller, caller_manifest, lib_manifest)
    )
    check = json.loads(capsys.readouterr().out)
    assert check["context_match"] is False


def test_reuse_route_keeps_call_modeling(tmp_path, capsys):
    lib = tmp_path / "lib.sol"
    lib.write_text(_LIB_SRC)
    lib_manifest = _produce(tmp_path, capsys, lib)
    caller = tmp_path / "caller.sol"
    caller.write_text(
        "contract C {"
        " function f(uint256 a, uint256 b) public returns (uint256) {"
        "   return ext.Lib.g(a, b); } }"
    )
    sol.main(
        type(
            "A",
            (),
            {
                "source": str(caller),
                "resolve_modules": False,
                "summary_aware_calls": str(lib_manifest),
            },
        )()
    )
    caller_manifest = tmp_path / "caller-manifest.json"
    caller_manifest.write_text(capsys.readouterr().out)
    sol.main_reuse(
        _sol_aware_args(caller, caller_manifest, lib_manifest)
    )
    merged = json.loads(capsys.readouterr().out)
    assert merged["call_modeling"]["summary_modeled_calls"] == 1


def test_output_may_not_overwrite_callee_manifest(tmp_path, capsys):
    lib = tmp_path / "lib.sol"
    lib.write_text(_LIB_SRC)
    lib_manifest = _produce(tmp_path, capsys, lib)
    caller = tmp_path / "caller.sol"
    caller.write_text(_CALLER)
    with pytest.raises(SystemExit) as exc:
        sol.main_check(
            _sol_aware_args(
                caller,
                caller_manifest_or_stub(tmp_path, caller),
                lib_manifest,
                output=lib_manifest,
            )
        )
    assert exc.value.code == 2
    out = json.loads(capsys.readouterr().out)
    assert out["error"]["reason"] == "output_overwrites_source"


def caller_manifest_or_stub(tmp_path, caller):
    m = tmp_path / "m.json"
    if not m.exists():
        m.write_text(
            json.dumps(sol.summarize_solidity(_CALLER).to_dict())
        )
    return m


def test_attempt_fingerprint_binds_callee_manifest(tmp_path):
    src = tmp_path / "a.sol"
    src.write_text(_CALLER)
    raw = src.read_bytes()
    lib = tmp_path / "lib.json"
    lib.write_text(json.dumps({"x": 1}))
    fp1 = sol._attempt_fingerprint(str(src), raw)
    fp2 = sol._attempt_fingerprint(str(src), raw, str(lib))
    assert fp1 != fp2
    lib.write_text(json.dumps({"x": 2}))
    fp3 = sol._attempt_fingerprint(str(src), raw, str(lib))
    assert fp3 != fp2
    with pytest.raises(ValueError):
        sol._attempt_fingerprint(
            str(src), raw, str(tmp_path / "absent.json")
        )


def test_attempt_fingerprint_bounds_manifest_read(
    tmp_path, monkeypatch
):
    src = tmp_path / "a.sol"
    src.write_text(_CALLER)
    lib = tmp_path / "big.json"
    lib.write_bytes(b"x" * 64)
    monkeypatch.setattr(sol, "MAX_MANIFEST_BYTES", 8)
    with pytest.raises(ValueError, match="too large"):
        sol._attempt_fingerprint(
            str(src), src.read_bytes(), str(lib)
        )


def test_attempt_route_forwards_summary_aware_calls(tmp_path, capsys):
    caller = tmp_path / "caller.sol"
    caller.write_text(_CALLER)
    args = _attempt_args(caller)
    sol.main_attempt(args)
    base = json.loads(capsys.readouterr().out)
    fp = base["sequence"]["request_fingerprint"]
    lib = tmp_path / "lib.sol"
    lib.write_text(_LIB_SRC)
    lib_manifest = _produce(tmp_path, capsys, lib)
    args = _attempt_args(caller)
    args.summary_aware_calls = str(lib_manifest)
    sol.main_attempt(args)
    report = json.loads(capsys.readouterr().out)
    assert report["sequence"]["request_fingerprint"] != fp
    # The flag reached the child: a malformed manifest fails its
    # produce run (a forwarded declared input), where the same
    # source without the flag exits 0.
    bad = tmp_path / "bad.json"
    bad.write_text("{")
    args = _attempt_args(caller)
    args.summary_aware_calls = str(bad)
    sol.main_attempt(args)
    norm = json.loads(capsys.readouterr().out)["normalized"]
    assert norm["outcome"] == "exited" and norm["exit_code"] != 0


def test_inline_depth_cut_rederives_at_top_level():
    # A callee whose first inline walk stops at the depth limit is
    # cached unavailable — the top-level pass must re-derive it
    # rather than publish the depth-limited record.
    chain = sol.MAX_INLINE_DEPTH + 6
    src = "\n".join(
        (
            f"function f{i}(uint256 x) returns (uint256) "
            f"{{ return f{i + 1}(x); }}"
            if i < chain
            else f"function f{i}(uint256 x) returns (uint256) "
            "{ return x + 1; }"
        )
        for i in range(chain + 1)
    )
    s = sol.summarize_solidity(src)
    fns = {fn.name: fn for fn in s.functions}
    tail = fns[f"f{chain}"]
    assert tail.available
    assert tail.return_dependencies == frozenset({0})
    # The function whose callee walk hit the limit still
    # re-derives — its own call chain fully resolves at
    # depth zero.
    mid = fns[f"f{chain - 2}"]
    assert mid.available
    assert mid.return_dependencies == frozenset({0})


def test_inline_depth_cut_rederived_calls_still_count():
    # A call the first inline walk never reached (depth cut) is
    # first walked during the top-level re-derivation — it must
    # still be counted and mark its declared callee seen.
    chain = sol.MAX_INLINE_DEPTH + 6
    src = "\n".join(
        (
            f"function f{i}(uint256 x) returns (uint256) "
            f"{{ return f{i + 1}(x); }}"
            if i < chain
            else f"function f{i}(uint256 x) returns (uint256) "
            "{ return ext.g(x); }"
        )
        for i in range(chain + 1)
    )
    s = sol.summarize_solidity(
        src, declared=_callee_manifest(_decl_fn("g", ("x",), {0}))
    )
    fns = {fn.name: fn for fn in s.functions}
    tail = fns[f"f{chain}"]
    assert tail.available
    assert tail.return_dependencies == frozenset({0})
    assert s.call_modeling["summary_modeled_calls"] == 1
    assert s.call_modeling["summary_unmatched"] == 0
