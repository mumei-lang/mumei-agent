"""Unit tests for the cross-language type/constant semantic model."""
from __future__ import annotations

from agent import semantic_safety


def test_collect_declared_constants_solidity() -> None:
    source = (
        "uint256 internal constant N =\n"
        "    0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551;\n"
        "uint256 internal constant EVM_TREE_RADIX = 16;\n"
        "uint256 private constant DERIVED = EVM_TREE_RADIX + 1;\n"
    )
    constants = semantic_safety.collect_declared_constants(source, "solidity")
    assert constants["N"] != 0
    assert constants["EVM_TREE_RADIX"] == 16
    assert "DERIVED" not in constants  # non-literal initializer skipped


def test_collect_declared_constants_rust() -> None:
    source = (
        "const N: u64 = 7;\n"
        "const HEX: i64 = 0x10;\n"
        "const SUFFIXED: u32 = 42u32;\n"
        "const DERIVED: i64 = N + 1;\n"
    )
    constants = semantic_safety.collect_declared_constants(source, "rust")
    assert constants["N"] == 7
    assert constants["HEX"] == 16
    assert constants["SUFFIXED"] == 42
    assert "DERIVED" not in constants


def test_collect_declared_constants_typescript() -> None:
    source = (
        "const K = 5;\n"
        "const HEX = 0xff;\n"
        "const NAME = 'foo';\n"
        "const OBJ = { a: 1 } as const;\n"
    )
    constants = semantic_safety.collect_declared_constants(source, "typescript")
    assert constants["K"] == 5
    assert constants["HEX"] == 255
    assert "NAME" not in constants  # string literal, not an integer
    assert "OBJ" not in constants


def test_divisor_and_index_helpers() -> None:
    consts = {"N": 7, "NEG": -1, "ZERO": 0}
    assert semantic_safety.divisor_provably_nonzero("N", consts) is True
    assert semantic_safety.divisor_provably_nonzero("ZERO", consts) is False
    assert semantic_safety.divisor_provably_nonzero("unknown", consts) is False
    assert semantic_safety.known_nonnegative_index("N", consts) == 7
    assert semantic_safety.known_nonnegative_index("NEG", consts) is None
    assert semantic_safety.known_nonnegative_index("unknown", consts) is None


def test_is_nullable_type_cross_language() -> None:
    # Go: pointer/slice/map/chan/error/any/func are nillable; value types are not.
    for nillable in ("*Stream", "[]byte", "map[string]int", "chan int", "error", "any"):
        assert semantic_safety.is_nullable_type(nillable, "go"), nillable
    for value_type in ("reflect.Value", "time.Time", "int", "uint64", "MyStruct"):
        assert not semantic_safety.is_nullable_type(value_type, "go"), value_type

    # Solidity value types and Rust references are never null.
    assert not semantic_safety.is_nullable_type("bytes", "solidity")
    assert not semantic_safety.is_nullable_type("uint256", "solidity")
    assert not semantic_safety.is_nullable_type("&str", "rust")

    # TypeScript objects/strings are nullable; primitives are not.
    assert semantic_safety.is_nullable_type("string", "typescript")
    assert semantic_safety.is_nullable_type("Foo[]", "typescript")
    assert not semantic_safety.is_nullable_type("number", "typescript")
    assert not semantic_safety.is_nullable_type("boolean", "typescript")


def test_should_flag_null_deref_defaults() -> None:
    # Unknown type falls back to the language default (TS nullable, others not).
    assert semantic_safety.should_flag_null_deref("x", None, "typescript") is True
    assert semantic_safety.should_flag_null_deref("x", None, "solidity") is False
    assert semantic_safety.should_flag_null_deref("x", None, "rust") is False
    # A known value type is never flagged even in a nullable language.
    assert (
        semantic_safety.should_flag_null_deref("x", {"x": "number"}, "typescript")
        is False
    )
