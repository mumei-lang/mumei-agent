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


def test_non_scalar_state_var_still_closes():
    src = """contract C {
  uint256[] xs;
  function f(uint256 x) public view returns (uint256) {
    return xs[0];
  }
}"""
    s = _fn(src, "f")
    assert not s.available


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
