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
    forged["functions"][0]["return_dependencies"] = [1, 2, 3]
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
        self, request, argv, memory_bound_mb=None, cancel_event=None
    ):
        src.write_text(_SOL_SRC + "//mutated mid-run")
        return real_run(
            self,
            request,
            argv,
            memory_bound_mb=memory_bound_mb,
            cancel_event=cancel_event,
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
