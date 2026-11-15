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


def test_break_in_loop_closes():
    src = """contract C {
  function f(uint256 x) public pure returns (uint256) {
    uint256 s = x;
    for (uint256 i = 0; i < x; i++) { if (i > 2) { break; } s += i; }
    return s;
  }
}"""
    s = _fn(src, "f")
    assert not s.available


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
    assert s1.profile == "mumei.sol-interprocedural/v1"


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
