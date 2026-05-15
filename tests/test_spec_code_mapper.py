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
                "effects": [],
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

    result = mapper.build_mapping(spec, code)
    mappings = result.mappings

    assert result.success is True
    assert len(mappings) == 2
    assert mappings[0].spec_item_id == "safe_add"
    assert mappings[0].spec_type == "requires"
    assert mappings[1].spec_type == "ensures"
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

    result = mapper.build_mapping(spec, code, {"verified_atoms": ["safe_div"]})
    mappings = result.mappings

    assert len(mappings) == 2
    assert mappings[0].verification_status == "passed"


def test_build_mapping_missing_atom_has_zero_confidence():
    mapper = SpecCodeMapper()
    spec = {"atoms": [{"name": "missing_atom"}]}

    mappings = mapper.build_mapping(spec, "atom other() -> i64").mappings

    assert mappings[0].code_location == {"line": 0, "col": 0}
    assert mappings[0].confidence == 0.0


def test_unmapped_clause_is_reported_as_warning():
    mapper = SpecCodeMapper()
    spec = {"atoms": [{"name": "missing_atom", "requires": "x > 0"}]}

    result = mapper.build_mapping(spec, "")

    assert result.mappings == []
    assert result.warnings == ["No code location found for requires clause: x > 0"]


def test_failed_atom_status_from_report():
    mapper = SpecCodeMapper()
    spec = {"atoms": [{"name": "safe_add"}]}
    code = "atom safe_add() -> i64"

    mappings = mapper.build_mapping(spec, code, {"failed_atoms": ["safe_add"]}).mappings

    assert mappings[0].verification_status == "failed"


def test_report_dict_values_are_checked_for_atom_status():
    mapper = SpecCodeMapper()
    spec = {"atoms": [{"name": "safe_add"}]}
    code = "atom safe_add() -> i64"

    mappings = mapper.build_mapping(
        spec,
        code,
        {"failed_atoms": {"safe_add": {"name": "safe_add"}}, "success": True},
    ).mappings

    assert mappings[0].verification_status == "failed"


def test_requires_and_ensures_public_helpers():
    mapper = SpecCodeMapper()
    code = """
atom safe_div(a: i64, b: i64) -> i64
    requires: b != 0;
    ensures: result == a / b;
    body: a / b
"""

    requires = mapper.map_requires_to_code("b != 0", code, {"status": "ok"})
    ensures = mapper.map_ensures_to_code("result == a / b", code, {"status": "ok"})

    assert requires is not None
    assert requires.spec_type == "requires"
    assert requires.spec_clause == "b != 0"
    assert requires.code_location["line"] == 3
    assert ensures is not None
    assert ensures.spec_type == "ensures"
    assert ensures.code_location["line"] == 4


def test_effect_mapping():
    mapper = SpecCodeMapper()
    spec = {
        "atoms": [
            {
                "name": "write_log",
                "effects": ["Log"],
            }
        ]
    }
    code = """
atom write_log(msg: Nat)
    effects: [Log];
    body: msg
"""

    mappings = mapper.build_mapping(spec, code, {"status": "ok"}).mappings

    assert len(mappings) == 1
    assert mappings[0].spec_type == "effect"
    assert mappings[0].spec_clause == "Log"
    assert mappings[0].code_location["line"] == 3


def test_violated_constraint_marks_clause_failed():
    mapper = SpecCodeMapper()
    spec = {"atoms": [{"name": "safe_div", "requires": "b != 0"}]}
    code = "atom safe_div(a: i64, b: i64) -> i64\n    requires: b != 0;"
    report = {
        "semantic_feedback": {
            "violated_constraints": [{"constraint": "requires b != 0"}],
        },
    }

    mappings = mapper.build_mapping(spec, code, report).mappings

    assert mappings[0].verification_status == "failed"


def test_to_json_includes_visualization_fields():
    mapper = SpecCodeMapper()
    mapping = mapper.map_ensures_to_code(
        "result == a + b",
        "atom add(a: i64, b: i64) -> i64\n    ensures: result == a + b;",
        atom_name="add",
    )

    assert mapping is not None
    payload = mapper.to_json([mapping])

    assert payload[0]["spec_type"] == "ensures"
    assert payload[0]["spec_clause"] == "result == a + b"


def test_first_line_atom_location_uses_one_indexed_column():
    mapper = SpecCodeMapper()

    location = mapper._find_atom_location("atom safe_add() -> i64", "safe_add")

    assert location == {"line": 1, "col": 1}


def test_to_json():
    """Test JSON serialization."""
    mapper = SpecCodeMapper()

    mapping = SpecCodeMapping(
        spec_description="Test",
        spec_type="requires",
        spec_clause="true",
        code_location={"line": 1, "col": 1},
        verification_status="passed",
        confidence=0.9,
        spec_item_id="test_atom",
        requires_clause="true",
        ensures_clause=None,
    )

    json_data = mapper.to_json([mapping])

    assert len(json_data) == 1
    assert json_data[0]["spec_description"] == "Test"
    assert json_data[0]["confidence"] == 0.9
