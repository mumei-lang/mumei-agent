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


def test_state_var_read_closes():
    src = """contract C {
  uint256 public count;
  function f(uint256 x) public pure returns (uint256) {
    return count + x;
  }
}"""
    s = _fn(src, "f")
    assert not s.available
    assert s.return_dependencies is None
    assert s.gaps and s.gaps[0].reason == "binding_unavailable"


def test_member_call_closes():
    src = """contract C {
  function f(uint256 x) public pure returns (uint256) {
    return this.g(x);
  }
}"""
    s = _fn(src, "f")
    assert not s.available


def test_loop_closes():
    src = """contract C {
  function f(uint256 x) public pure returns (uint256) {
    for (uint256 i = 0; i < x; i++) { }
    return x;
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
  uint256 public count;
  function bad(uint256 a) public pure returns (uint256) {
    return count + a;
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
