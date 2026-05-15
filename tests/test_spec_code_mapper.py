"""Tests for spec-code mapper."""

from agent.spec_code_mapper import SpecCodeMapper, SpecCodeMapping


def test_build_mapping_simple():
    """Test building mapping for a simple spec."""
    mapper = SpecCodeMapper()

    spec = {
        "atoms": [
            {
                "name": "safe_add",
                "description": "Safe addition with overflow check",
                "requires": "a + b >= a && a + b >= b",
                "ensures": "result == a + b",
                "inputs": [
                    {"name": "a", "type": "i64"},
                    {"name": "b", "type": "i64"},
                ],
            }
        ]
    }

    code = """
atom safe_add(a: i64, b: i64) -> i64
    requires: a + b >= a && a + b >= b;
    ensures: result == a + b;
    body: a + b
"""

    mappings = mapper.build_mapping(spec, code)

    assert len(mappings) == 1
    assert mappings[0].spec_item_id == "safe_add"
    assert mappings[0].code_location["line"] > 0
    assert mappings[0].confidence > 0.5


def test_build_mapping_single_atom_spec():
    mapper = SpecCodeMapper()
    spec = {
        "name": "safe_div",
        "description": "Safe division",
        "params": [
            {"name": "a", "type": "i64"},
            {"name": "b", "type": "i64"},
        ],
        "requires": "b != 0",
        "ensures": "result == a / b",
    }
    code = """
atom safe_div(a: i64, b: i64) -> i64
    requires: b != 0;
    ensures: result == a / b;
    body: a / b
"""

    mappings = mapper.build_mapping(spec, code, {"verified_atoms": ["safe_div"]})

    assert len(mappings) == 1
    assert mappings[0].verification_status == "passed"


def test_build_mapping_missing_atom_has_zero_confidence():
    mapper = SpecCodeMapper()
    spec = {"atoms": [{"name": "missing_atom"}]}

    mappings = mapper.build_mapping(spec, "atom other() -> i64")

    assert mappings[0].code_location == {"line": 0, "col": 0}
    assert mappings[0].confidence == 0.0


def test_failed_atom_status_from_report():
    mapper = SpecCodeMapper()
    spec = {"atoms": [{"name": "safe_add"}]}
    code = "atom safe_add() -> i64"

    mappings = mapper.build_mapping(spec, code, {"failed_atoms": ["safe_add"]})

    assert mappings[0].verification_status == "failed"


def test_to_json():
    """Test JSON serialization."""
    mapper = SpecCodeMapper()

    mapping = SpecCodeMapping(
        spec_description="Test",
        spec_item_id="test_atom",
        requires_clause="true",
        ensures_clause="true",
        code_location={"line": 1, "col": 1},
        verification_status="passed",
        confidence=0.9,
    )

    json_data = mapper.to_json([mapping])

    assert len(json_data) == 1
    assert json_data[0]["spec_description"] == "Test"
    assert json_data[0]["confidence"] == 0.9
