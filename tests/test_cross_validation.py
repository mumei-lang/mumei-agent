"""Tests for P14 cross-validation flows."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent.config import AgentConfig
from agent.cross_validation import (
    CrossValidationIssue,
    _with_spec_code_source_lines,
    build_validate_code_to_spec_parser,
    build_validate_code_parser,
    build_validate_spec_to_code_parser,
    build_validate_spec_parser,
    main_validate_spec,
    main_validate_spec_to_code,
    validate_code_to_spec,
    main_validate_code,
    validate_foreign_code,
    validate_nl_spec,
    validate_spec_to_code,
)
from agent.conformance_verifier import verify_conformance
from agent.report_formatter import format_cross_validation_report
from agent.verify_conformance import (
    _emit as emit_conformance_report,
    build_parser as build_verify_conformance_parser,
)
from agent.prompts.conformance_verification import build_conformance_verification_prompt
from agent.prompts.cross_validation_code import build_code_cross_validation_prompt
from agent.prompts.cross_validation_nl import build_nl_cross_validation_prompt


FIXTURES = Path(__file__).parent / "fixtures"


def test_validate_nl_spec_detects_contradiction_ambiguity_and_unsat_contract() -> None:
    spec = (
        "常に残高を更新する、かつ決して残高を更新する。"
        "入力は適切に検証する。"
        "requires: x > 0 && x < 0;\n"
        "ensures: result == x;"
    )

    result = validate_nl_spec(
        spec,
        config=AgentConfig(api_key=""),
        use_llm=False,
        run_mumei=False,
    )

    assert result.success is False
    assert result.contradictions
    assert result.ambiguities
    assert result.satisfiable is False
    assert any(issue.kind == "overconstraint" for issue in result.overconstraints)
    issues = [*result.contradictions, *result.ambiguities, *result.overconstraints]
    assert issues
    assert all(issue.fix_suggestion for issue in issues)


def test_validate_foreign_code_infers_python_contract_and_runs_mumei() -> None:
    code = "def add(a: int, b: int) -> int:\n    return a + b\n"
    mumei = MagicMock()
    mumei.verify.return_value = {
        "success": True,
        "report": {"status": "ok"},
        "stdout": "{}",
        "stderr": "",
    }

    with patch("agent.cross_validation.create_mumei_client", return_value=mumei):
        result = validate_foreign_code(
            code,
            "python",
            config=AgentConfig(api_key=""),
            use_llm=False,
            run_mumei=True,
        )

    assert result.success is True
    assert result.verdict == "verified"
    assert result.language == "python"
    assert result.inferred_atoms[0].name == "add"
    assert result.inferred_atoms[0].ensures == "result == a + b"
    assert "trusted atom add" in result.mumei_source
    mumei.verify.assert_called_once()


def test_validate_foreign_code_adds_division_safety_precondition() -> None:
    code = "def divide(a: int, b: int) -> int:\n    return a // b\n"
    mumei = MagicMock()
    mumei.verify.return_value = {
        "success": True,
        "report": {"status": "ok"},
        "stdout": "{}",
        "stderr": "",
    }

    with patch("agent.cross_validation.create_mumei_client", return_value=mumei):
        result = validate_foreign_code(
            code,
            "python",
            config=AgentConfig(api_key=""),
            use_llm=False,
            run_mumei=True,
        )

    assert result.success is True
    assert result.verdict == "verified"
    assert result.inferred_atoms[0].requires == "b != 0"


def test_validate_foreign_code_infers_multilanguage_safety_contracts() -> None:
    fixtures = [
        (
            "rust",
            "pub fn add(a: i64, b: i64) -> i64 { a + b }\n",
            "a + b <= 9223372036854775807",
        ),
        (
            "typescript",
            "export function len(name?: string): number { return name!.length; }\n",
            "name != null",
        ),
        (
            "go",
            "package lists\nfunc nth(values []int, idx int) int { return values[idx] }\n",
            "idx < len_values",
        ),
        (
            "go",
            "package calc\nfunc add(a int, b int) int { return a + b }\n",
            "a + b <= 9223372036854775807",
        ),
        (
            "go",
            "package users\nfunc age(user *User) int { return user.Age }\n",
            "user != nil",
        ),
        (
            "solidity",
            "function add(uint256 a, uint256 b) public pure returns (uint256) "
            "{ return a + b; }\n",
            "a + b <= 115792089237316195423570985008687907853269984665640564039457584007913129639935",
        ),
    ]
    mumei = MagicMock()
    mumei.verify.return_value = {
        "success": True,
        "report": {"status": "ok"},
        "stdout": "{}",
        "stderr": "",
    }

    for language, code, expected_requires in fixtures:
        with patch("agent.cross_validation.create_mumei_client", return_value=mumei):
            result = validate_foreign_code(
                code,
                language,
                config=AgentConfig(api_key=""),
                use_llm=False,
                run_mumei=True,
            )

        assert result.success is True
        assert result.verdict == "verified"
        assert result.language == language
        assert result.inferred_atoms
        assert expected_requires in result.inferred_atoms[0].requires


def test_validate_foreign_code_reports_solidity_reentrancy_and_access_control() -> None:
    source = (FIXTURES / "sample_solidity_vulnerable.sol").read_text(encoding="utf-8")
    mumei = MagicMock()
    mumei.verify.return_value = {
        "success": True,
        "report": {"status": "ok"},
        "stdout": "{}",
        "stderr": "",
    }

    with patch("agent.cross_validation.create_mumei_client", return_value=mumei):
        result = validate_foreign_code(
            source,
            "solidity",
            config=AgentConfig(api_key=""),
            use_llm=False,
            run_mumei=True,
        )

    messages = [issue.message for issue in result.issues]

    assert result.success is False
    assert result.verdict == "refuted"
    assert any("may be vulnerable to reentrancy" in message for message in messages)
    assert any("Checks-Effects-Interactions" in message for message in messages)
    assert any("no access-control guard" in message for message in messages)
    assert any("withdraw" in message and "reentrancy" in message for message in messages)
    assert any("setOwner" in message and "access-control guard" in message for message in messages)
    assert all("withdrawAll" not in message for message in messages)
    assert all("getBalance" not in message for message in messages)


def test_validate_foreign_code_preserves_typescript_signature_types() -> None:
    mumei = MagicMock()
    mumei.verify.return_value = {
        "success": True,
        "report": {"status": "ok"},
        "stdout": "{}",
        "stderr": "",
    }
    with patch("agent.cross_validation.create_mumei_client", return_value=mumei):
        result = validate_foreign_code(
            "export function isEmpty(name?: string): boolean { return name!.length == 0; }\n",
            "typescript",
            config=AgentConfig(api_key=""),
            use_llm=False,
            run_mumei=True,
        )

    assert result.success is True
    assert result.inferred_atoms[0].params[0].type == "string"
    assert result.inferred_atoms[0].return_type == "bool"


def test_validate_foreign_code_typescript_const_with_type_annotation() -> None:
    mumei = MagicMock()
    mumei.verify.return_value = {
        "success": True,
        "report": {"status": "ok"},
        "stdout": "{}",
        "stderr": "",
    }
    source = "type Auth = (req: Request) => { username: string; password: string } | undefined\nexport const auth: Auth = (req: Request) => {\n  return { username: 'a', password: 'b' }\n}\n"
    with patch("agent.cross_validation.create_mumei_client", return_value=mumei):
        result = validate_foreign_code(
            source,
            "typescript",
            config=AgentConfig(api_key=""),
            use_llm=False,
            run_mumei=True,
        )

    assert result.success is True
    assert result.inferred_atoms[0].name == "auth"
    assert result.inferred_atoms[0].params[0].type == "i64"
    assert result.inferred_atoms[0].return_type == "i64"


def test_validate_foreign_code_go_ignores_package_selector_for_nil_contract() -> None:
    mumei = MagicMock()
    mumei.verify.return_value = {
        "success": True,
        "report": {"status": "ok"},
        "stdout": "{}",
        "stderr": "",
    }
    with patch("agent.cross_validation.create_mumei_client", return_value=mumei):
        result = validate_foreign_code(
            'package demo\nimport "math"\nfunc abs(x int) int { return math.Abs(x) }\n',
            "go",
            config=AgentConfig(api_key=""),
            use_llm=False,
            run_mumei=True,
        )

    assert result.success is True
    assert result.inferred_atoms[0].requires == "true"
    assert "math != nil" not in result.mumei_source


def test_validate_foreign_code_go_extracts_method_receiver() -> None:
    mumei = MagicMock()
    mumei.verify.return_value = {
        "success": True,
        "report": {"status": "ok"},
        "stdout": "{}",
        "stderr": "",
    }
    with patch("agent.cross_validation.create_mumei_client", return_value=mumei):
        result = validate_foreign_code(
            "package users\nfunc (u *User) Age() int { return u.Age }\n",
            "go",
            config=AgentConfig(api_key=""),
            use_llm=False,
            run_mumei=True,
        )

    assert result.success is True
    assert result.inferred_atoms[0].name == "Age"
    assert result.inferred_atoms[0].params[0].name == "u"
    assert result.inferred_atoms[0].requires == "u != nil"


def test_validate_foreign_code_without_mumei_stays_verified(tmp_path: Path) -> None:
    source = tmp_path / "add.py"
    source.write_text("def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")

    result = validate_foreign_code(
        source.read_text(encoding="utf-8"),
        "python",
        config=AgentConfig(api_key=""),
        use_llm=False,
        run_mumei=False,
    )

    args = build_validate_code_parser().parse_args(
        ["--input", str(source), "--no-llm", "--no-mumei"]
    )

    cli_result = main_validate_code(args)

    assert result.success is True
    assert result.verdict == "verified"
    assert cli_result.success is True
    assert cli_result.verdict == "verified"


def test_validate_foreign_code_non_skip_z3_warning_keeps_plain_verification_message(tmp_path: Path) -> None:
    source = tmp_path / "unknown.go"
    source.write_text(
        "package demo\nfunc size(input []byte) int { return len(input) + 1 }\n",
        encoding="utf-8",
    )
    mumei = MagicMock()
    mumei.verify.return_value = {
        "success": False,
        "report": {"status": "failed"},
        "stdout": "",
        "stderr": "verification failed",
    }

    with patch("agent.cross_validation._check_atoms_with_z3") as z3_mock, patch(
        "agent.cross_validation.create_mumei_client",
        return_value=mumei,
    ):
        z3_mock.return_value = (
            True,
            [],
            ["Z3 returned unknown for expression: len(input) > 1"],
        )
        result = validate_foreign_code(
            source.read_text(encoding="utf-8"),
            "go",
            config=AgentConfig(api_key=""),
            use_llm=False,
            run_mumei=True,
        )

    assert result.success is False
    assert result.verdict == "refuted"
    assert any(
        "mumei verify reported an unsatisfied or inconsistent inferred contract." in issue.message
        for issue in result.issues
    )
    assert all("unsupported Z3 clauses were skipped" not in issue.message for issue in result.issues)


def test_validate_foreign_code_genuine_go_failure_is_refuted_despite_skips(tmp_path: Path) -> None:
    """A genuine mumei refutation (status "failed") stays a real failure even when
    the agent skipped some clauses: skipped clauses are removed from the module, so
    any mumei failure refutes the clauses that *were* checked (#304)."""
    source = tmp_path / "inconclusive.go"
    source.write_text(
        "package demo\nfunc size(input []byte) int { return len(input) + 1 }\n",
        encoding="utf-8",
    )
    mumei = MagicMock()
    mumei.verify.return_value = {
        "success": False,
        "report": {"status": "failed"},
        "stdout": "",
        "stderr": "verification failed",
    }

    with patch("agent.cross_validation.create_mumei_client", return_value=mumei):
        result = validate_foreign_code(
            source.read_text(encoding="utf-8"),
            "go",
            config=AgentConfig(api_key=""),
            use_llm=False,
            run_mumei=True,
        )

    assert result.success is False
    assert result.verdict == "refuted"
    assert any("Skipped unsupported Z3 clause" in warning for warning in result.warnings)
    assert any(
        "unsatisfied or inconsistent" in issue.message for issue in result.issues
    )
    assert all("inconclusive" not in issue.message for issue in result.issues)

    args = build_validate_code_parser().parse_args(
        [
            "--input",
            str(source),
            "--language",
            "go",
            "--no-llm",
        ]
    )

    with patch("agent.cross_validation.create_mumei_client", return_value=mumei):
        with pytest.raises(SystemExit) as exc:
            main_validate_code(args)

    assert exc.value.code == 1


def test_clause_split_is_paren_aware_and_balanced() -> None:
    """Top-level && split must not shred parenthesized/|| clauses (#420)."""
    from agent.cross_validation_z3 import _clause_to_z3, _split_top_level_conjuncts

    compound = (
        "(b == nil && result == nil) || "
        "(b != nil && len(result) == len(b) && forall(i, 0, len(b), result[i] == b[i]))"
    )
    # A top-level || clause has no top-level &&: it stays whole.
    assert _split_top_level_conjuncts(compound) == [compound]

    conjunction = "len(result) == l && forall(i, 0, len(slice), result[i] == slice[i])"
    assert _split_top_level_conjuncts(conjunction) == [
        "len(result) == l ",
        " forall(i, 0, len(slice), result[i] == slice[i])",
    ]

    # Any residual skip warnings must reference balanced fragments.
    _, warnings = _clause_to_z3(compound, {})
    for warning in warnings:
        fragment = warning.removeprefix("Skipped unsupported Z3 clause: ")
        assert fragment.count("(") == fragment.count(")"), warning


def test_clause_split_is_string_literal_aware() -> None:
    """Top-level &&/|| split must not shred operators inside string literals."""
    from agent.cross_validation_z3 import (
        _clause_to_z3,
        _has_top_level_disjunction,
        _split_top_level_conjuncts,
    )

    # ' && ' inside a string must not be treated as a conjunction.
    clause_with_and = (
        "result == ' && '.join(_dedupe_strings(requirements)) if requirements else 'true'"
    )
    assert _split_top_level_conjuncts(clause_with_and) == [clause_with_and]

    # ' || ' inside a string must not be treated as a disjunction.
    clause_with_or = "result == ' || '.join(parts)"
    assert _has_top_level_disjunction(clause_with_or) is False
    assert _split_top_level_conjuncts(clause_with_or) == [clause_with_or]

    # Real top-level conjunctions mixed with a string containing && stay split.
    mixed = "result == ' && ' && x > 0"
    assert _split_top_level_conjuncts(mixed) == ["result == ' && ' ", " x > 0"]

    # A clause that was previously split into unbalanced fragments is now skipped
    # as a single unsupported clause.
    exprs, warnings = _clause_to_z3(clause_with_and, {})
    assert exprs == []
    assert len(warnings) == 1
    assert "Skipped unsupported Z3 clause: " in warnings[0]


def test_clause_disjunction_is_lowered_not_skipped() -> None:
    """`||` clauses must lower to z3.Or instead of being silently skipped (#303)."""
    import z3

    from agent.cross_validation_z3 import _clause_to_z3

    syms: dict[str, object] = {
        "result": z3.Int("result"),
        "v": z3.Int("v"),
        "s": z3.Int("s"),
    }
    exprs, warnings = _clause_to_z3("result == v || s == 0", syms)
    assert warnings == []
    assert len(exprs) == 1
    # `&&` remains supported (regression guard on the symmetric path).
    exprs2, warnings2 = _clause_to_z3("result >= 0 && result <= v", syms)
    assert warnings2 == []
    assert len(exprs2) == 2
    # Strict-equality spellings normalize too.
    exprs3, warnings3 = _clause_to_z3("result !== s", syms)
    assert warnings3 == []
    assert len(exprs3) == 1


def test_clause_mixed_and_or_preserves_precedence() -> None:
    """`a && b || c` must lower as `(a && b) || c`, not `a && (b || c)` (#303)."""
    import z3

    from agent.cross_validation_z3 import _clause_to_z3

    syms: dict[str, object] = {
        "x": z3.Int("x"),
        "y": z3.Int("y"),
        "z": z3.Int("z"),
    }
    exprs, warnings = _clause_to_z3("x > 0 && y > 0 || z > 0", syms)
    assert warnings == []
    # A top-level disjunction is lowered whole, not split into conjuncts.
    assert len(exprs) == 1

    # (x=-1, y=-1, z=1) satisfies `(x>0 && y>0) || z>0` but not `x>0 && (y>0 || z>0)`.
    solver = z3.Solver()
    solver.add(exprs[0])
    solver.add(syms["x"] == -1, syms["y"] == -1, syms["z"] == 1)
    assert solver.check() == z3.sat


def test_mumei_safe_clause_normalizes_strict_equality() -> None:
    """TypeScript/JS-style strict equality (``===``/``!==``) must be rewritten to
    the operators mumei parses, while unsupported conjuncts are still dropped."""
    from agent.cross_validation_z3 import _mumei_safe_clause

    assert _mumei_safe_clause("result !== false", {"result"}) == "result != false"
    assert _mumei_safe_clause("result === headers", {"result", "headers"}) == "result == headers"
    assert (
        _mumei_safe_clause(
            "(result => [object Object]) && result !== headers",
            {"result", "headers"},
        )
        == "result != headers"
    )
    assert (
        _mumei_safe_clause(
            "result !== false && x === y",
            {"result", "x", "y"},
        )
        == "result != false && x == y"
    )


def test_benign_llm_advisory_does_not_flip_verdict_to_refuted() -> None:
    """A generic ``llm`` advisory must not refute code that Z3 finds satisfiable and
    mumei verifies (#309)."""
    from agent.cross_validation import _validate_foreign_code_verdict
    from agent.cross_validation_models import (
        ContractParam,
        CrossValidationIssue,
        MumeiContractAtom,
    )

    atoms = [
        MumeiContractAtom(
            name="f",
            params=[ContractParam(name="x", type="i64")],
            return_type="i64",
            requires="true",
            ensures="result == x",
        )
    ]
    verification = {"success": True, "report": {"status": "trusted", "failed": 0}}
    advisory = CrossValidationIssue(
        kind="llm",
        message="No externally visible functions with safety preconditions found.",
        severity="error",
    )

    # A lone benign llm advisory must not drive `refuted` when sat + verified.
    assert (
        _validate_foreign_code_verdict(
            atoms=atoms,
            errors=[],
            issues=[advisory],
            satisfiable=True,
            verification=verification,
            warnings=[],
        )
        == "verified"
    )

    # A substantive issue still refutes.
    substantive = CrossValidationIssue(kind="verification", message="verification failed")
    assert (
        _validate_foreign_code_verdict(
            atoms=atoms,
            errors=[],
            issues=[substantive],
            satisfiable=True,
            verification=verification,
            warnings=[],
        )
        == "refuted"
    )

    # An unsatisfiable contract still refutes even if the only issue is an advisory.
    assert (
        _validate_foreign_code_verdict(
            atoms=atoms,
            errors=[],
            issues=[advisory],
            satisfiable=False,
            verification=verification,
            warnings=[],
        )
        == "refuted"
    )

    # Non-genuine verify failure + skipped clauses + only a benign llm advisory must
    # stay `unverifiable`, not fall through to `refuted` (the advisory must not block
    # the inconclusive guard, mirroring the refutation-check exclusion above) (#309).
    assert (
        _validate_foreign_code_verdict(
            atoms=atoms,
            errors=[],
            issues=[advisory],
            satisfiable=True,
            verification={"success": False, "report": {"status": "trusted", "failed": 0}},
            warnings=["Skipped unsupported Z3 clause: result == foo(x)"],
        )
        == "unverifiable"
    )


def test_validate_code_filters_llm_issues_for_dropped_hallucinated_atoms() -> None:
    """Issues tied to LLM-invented atoms must be discarded when those atoms are dropped."""
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = json.dumps(
        {
            "atoms": [
                {
                    "name": "AlgorithmTypes",
                    "params": [],
                    "return_type": "i64",
                    "requires": "result > x && result < x",
                    "ensures": "result == x",
                }
            ],
            "issues": [
                {
                    "kind": "overconstraint",
                    "message": "The inferred contract for AlgorithmTypes is unsatisfiable.",
                    "evidence": "result > x && result < x",
                    "severity": "error",
                }
            ],
        }
    )
    client = MagicMock()
    client.chat.completions.create.return_value = response
    config = AgentConfig(api_key="test", model="test-model")
    config.create_client = MagicMock(return_value=client)

    result = validate_foreign_code(
        "export const AlgorithmTypes = { RSA: 'RSA' } as const\n",
        "typescript",
        config=config,
        use_llm=True,
        run_mumei=False,
    )

    assert result.verdict == "unverifiable"
    assert not any("AlgorithmTypes" in issue.message for issue in result.issues)


def test_unsubstantiated_unsat_claim_does_not_refute_verified_code() -> None:
    """LLM unsat claims need formal corroboration before refuting (#312)."""
    from agent.cross_validation import _validate_foreign_code_verdict
    from agent.cross_validation_models import ContractParam, MumeiContractAtom

    atoms = [
        MumeiContractAtom(
            name="panic",
            params=[ContractParam(name="code", type="i64")],
            return_type="str",
            requires="true",
            ensures="result == 'x'",
        )
    ]
    issue = CrossValidationIssue(
        kind="overconstraint",
        message="The inferred contract is unsatisfiable.",
    )
    verification = {"success": True, "report": {"status": "trusted", "failed": 0}}
    warnings = ["Skipped unsupported Z3 clause: result == ..."]

    assert (
        _validate_foreign_code_verdict(
            atoms=atoms,
            errors=[],
            issues=[issue],
            satisfiable=None,
            verification=verification,
            warnings=warnings,
        )
        == "verified"
    )

    assert (
        _validate_foreign_code_verdict(
            atoms=atoms,
            errors=[],
            issues=[issue],
            satisfiable=False,
            verification=verification,
            warnings=warnings,
        )
        == "refuted"
    )

    assert (
        _validate_foreign_code_verdict(
            atoms=atoms,
            errors=[],
            issues=[issue],
            satisfiable=None,
            verification={"success": False, "report": {"status": "failed", "failed": 3}},
            warnings=warnings,
        )
        == "refuted"
    )

    satisfiability_issue = CrossValidationIssue(
        kind="satisfiability",
        message="The inferred contract is unsatisfiable.",
    )
    assert (
        _validate_foreign_code_verdict(
            atoms=atoms,
            errors=[],
            issues=[satisfiability_issue],
            satisfiable=None,
            verification=verification,
            warnings=warnings,
        )
        == "verified"
    )


def test_unsubstantiated_unsat_claim_does_not_block_inconclusive_guard() -> None:
    """Skipped Z3 clauses keep unsupported LLM unsat claims inconclusive (#312)."""
    from agent.cross_validation import _validate_foreign_code_verdict
    from agent.cross_validation_models import ContractParam, MumeiContractAtom

    atoms = [
        MumeiContractAtom(
            name="panic",
            params=[ContractParam(name="code", type="i64")],
            return_type="str",
            requires="true",
            ensures="result == 'x'",
        )
    ]
    issue = CrossValidationIssue(
        kind="overconstraint",
        message="The inferred contract is unsatisfiable.",
    )
    warnings = ["Skipped unsupported Z3 clause: result == ..."]

    assert (
        _validate_foreign_code_verdict(
            atoms=atoms,
            errors=[],
            issues=[issue],
            satisfiable=None,
            verification={"success": False, "report": {"status": "trusted", "failed": 0}},
            warnings=warnings,
        )
        == "unverifiable"
    )

    assert (
        _validate_foreign_code_verdict(
            atoms=atoms,
            errors=[],
            issues=[issue],
            satisfiable=None,
            verification={"success": False, "report": {"status": "failed", "failed": 3}},
            warnings=warnings,
        )
        == "refuted"
    )


def test_genuine_mumei_failure_not_mislabeled_inconclusive() -> None:
    """A real mumei refutation stays a failure even with agent-side skips (#304)."""
    from agent.cross_validation import _verify_atoms_with_mumei
    from agent.cross_validation_models import ContractParam, MumeiContractAtom

    atoms = [
        MumeiContractAtom(
            name="f",
            params=[ContractParam(name="x", type="i64")],
            return_type="i64",
            requires="true",
            ensures="result == x",
        )
    ]
    skips = ["Skipped unsupported Z3 clause: result == x > y || result == false"]

    # mumei genuinely failed (failed=4, skipped=0): must NOT be called inconclusive.
    failing = MagicMock()
    failing.verify.return_value = {
        "success": False,
        "report": {"status": "failed", "failed": 4, "skipped": 0},
        "stdout": "",
        "stderr": "",
    }
    with patch("agent.cross_validation.create_mumei_client", return_value=failing):
        _, issues, _ = _verify_atoms_with_mumei(
            atoms, AgentConfig(api_key=""), skipped_clause_warnings=skips
        )
    assert len(issues) == 1
    assert "inconclusive" not in issues[0].message
    assert "unsatisfied or inconsistent" in issues[0].message

    # No genuine failure recorded: skips make the result truly inconclusive.
    skipped_only = MagicMock()
    skipped_only.verify.return_value = {
        "success": False,
        "report": {"status": "verified", "failed": 0, "skipped": 0},
        "stdout": "",
        "stderr": "",
    }
    with patch("agent.cross_validation.create_mumei_client", return_value=skipped_only):
        _, issues2, _ = _verify_atoms_with_mumei(
            atoms, AgentConfig(api_key=""), skipped_clause_warnings=skips
        )
    assert len(issues2) == 1
    assert "inconclusive" in issues2[0].message


@pytest.mark.parametrize(
    ("language", "filename", "source"),
    [
        ("rust", "impl.rs", "pub fn identity(x: i64) -> i64 { x }\n"),
        (
            "typescript",
            "impl.ts",
            "export function identity(x: number): number { return x; }\n",
        ),
        ("go", "impl.go", "package demo\nfunc identity(x int) int { return x }\n"),
        (
            "solidity",
            "impl.sol",
            "function identity(int256 x) public pure returns (int256) { return x; }\n",
        ),
    ],
)
def test_validate_spec_to_code_detects_multilanguage_missing_requires(
    tmp_path: Path,
    language: str,
    filename: str,
    source: str,
) -> None:
    code_path = tmp_path / filename
    code_path.write_text(source, encoding="utf-8")

    result = validate_spec_to_code(
        "requires: x > 0;\nensures: result == x;",
        str(code_path),
        config=AgentConfig(api_key=""),
        language=language,
        use_llm=False,
        run_mumei=False,
    )

    assert result.success is False
    assert result.language == language
    assert "x > 0" in result.missing_constraints


def test_validate_nl_spec_keeps_llm_non_category_issues() -> None:
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = json.dumps(
        {
            "atoms": [],
            "issues": [
                {
                    "kind": "verification",
                    "message": "The inferred contract needs verifier attention.",
                    "evidence": "unverified temporal claim",
                }
            ],
        }
    )
    client = MagicMock()
    client.chat.completions.create.return_value = response
    config = AgentConfig(api_key="test", model="test-model")
    config.create_client = MagicMock(return_value=client)

    result = validate_nl_spec(
        "The function updates state safely.",
        config=config,
        use_llm=True,
        run_mumei=False,
    )

    assert result.success is False
    assert result.overconstraints[0].kind == "verification"


def test_validate_nl_spec_reports_unsupported_mixed_z3_clauses() -> None:
    result = validate_nl_spec(
        "requires: x > 0;\nensures: result == max(x, 0);",
        config=AgentConfig(api_key=""),
        use_llm=False,
        run_mumei=False,
    )

    assert result.satisfiable is True
    assert any("Skipped unsupported Z3 clause" in warning for warning in result.warnings)


def test_validate_code_cli_writes_json_report(tmp_path: Path) -> None:
    source = tmp_path / "code.py"
    output = tmp_path / "report.json"
    source.write_text("def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")
    mumei = MagicMock()
    mumei.verify.return_value = {
        "success": True,
        "report": {"status": "ok"},
        "stdout": "{}",
        "stderr": "",
    }
    args = build_validate_code_parser().parse_args(
        [
            "--input",
            str(source),
            "--language",
            "python",
            "--output",
            str(output),
            "--no-llm",
        ]
    )

    with patch("agent.cross_validation.create_mumei_client", return_value=mumei):
        result = main_validate_code(args)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert result.success is True
    assert result.verdict == "verified"
    assert payload["success"] is True
    assert payload["verdict"] == "verified"
    assert payload["inferred_atoms"][0]["name"] == "add"


@pytest.mark.parametrize(
    ("filename", "expected_language", "code"),
    [
        ("impl.py", "python", "def add(a: int, b: int) -> int:\n    return a + b\n"),
        ("lib.rs", "rust", "pub fn add(a: i64, b: i64) -> i64 { a + b }\n"),
        ("app.ts", "typescript", "export function add(a: number, b: number): number { return a + b; }\n"),
        ("app.tsx", "typescript", "export function add(a: number, b: number): number { return a + b; }\n"),
        ("app.js", "typescript", "function add(a, b) { return a + b; }\n"),
        ("app.jsx", "typescript", "function add(a, b) { return a + b; }\n"),
        ("main.go", "go", "package demo\nfunc add(a int, b int) int { return a + b }\n"),
    ],
)
def test_validate_code_cli_infers_language_from_extension(
    tmp_path: Path,
    filename: str,
    expected_language: str,
    code: str,
) -> None:
    """--language omitted: language is inferred from the file extension."""
    source = tmp_path / filename
    output = tmp_path / "report.json"
    source.write_text(code, encoding="utf-8")
    mumei = MagicMock()
    mumei.verify.return_value = {
        "success": True,
        "report": {"status": "ok"},
        "stdout": "{}",
        "stderr": "",
    }
    args = build_validate_code_parser().parse_args(
        ["--input", str(source), "--output", str(output), "--no-llm"]
    )

    with patch("agent.cross_validation.create_mumei_client", return_value=mumei):
        result = main_validate_code(args)

    assert result.language == expected_language
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["language"] == expected_language


def test_validate_code_cli_unsupported_extension_exits(tmp_path: Path) -> None:
    """Unsupported extension without --language exits with a clear error."""
    source = tmp_path / "data.csv"
    source.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
    args = build_validate_code_parser().parse_args(
        ["--input", str(source), "--no-llm", "--no-mumei"]
    )

    with pytest.raises(SystemExit) as exc:
        main_validate_code(args)

    assert exc.value.code == 1


def test_validate_code_cli_explicit_language_overrides_extension(tmp_path: Path) -> None:
    """Explicit --language takes precedence over the file extension."""
    source = tmp_path / "code.py"
    output = tmp_path / "report.json"
    source.write_text("pub fn add(a: i64, b: i64) -> i64 { a + b }\n", encoding="utf-8")
    mumei = MagicMock()
    mumei.verify.return_value = {
        "success": True,
        "report": {"status": "ok"},
        "stdout": "{}",
        "stderr": "",
    }
    args = build_validate_code_parser().parse_args(
        ["--input", str(source), "--language", "rust", "--output", str(output), "--no-llm"]
    )

    with patch("agent.cross_validation.create_mumei_client", return_value=mumei):
        result = main_validate_code(args)

    assert result.language == "rust"


def test_validate_spec_and_code_parsers_accept_required_flags() -> None:
    spec_args = build_validate_spec_parser().parse_args(
        ["--input", "spec.txt", "--format", "nl", "--no-llm"]
    )
    code_args = build_validate_code_parser().parse_args(
        ["--input", "code.py", "--language", "python", "--no-mumei"]
    )

    assert spec_args.input == "spec.txt"
    assert spec_args.format == "nl"
    assert code_args.language == "python"


def test_validate_spec_cli_markdown_outputs_fix_suggestion_table(
    tmp_path: Path,
    capsys,
) -> None:
    spec = tmp_path / "spec.txt"
    spec.write_text("requires: x > 0 && x < 0;\nensures: result == x;", encoding="utf-8")
    args = build_validate_spec_parser().parse_args(
        [
            "--input",
            str(spec),
            "--format",
            "markdown",
            "--no-llm",
            "--no-mumei",
        ]
    )

    with pytest.raises(SystemExit) as exc:
        main_validate_spec(args)

    captured = capsys.readouterr()
    assert exc.value.code == 1
    assert "| kind | severity | location | message | evidence | fix_suggestion |" in captured.out
    assert "Weaken the `requires` clause" in captured.out


def test_validate_spec_to_code_detects_missing_requires(tmp_path: Path) -> None:
    code_path = tmp_path / "impl.py"
    code_path.write_text("def identity(x: int) -> int:\n    return x\n", encoding="utf-8")

    result = validate_spec_to_code(
        "requires: x > 0;\nensures: result == x;",
        str(code_path),
        config=AgentConfig(api_key=""),
        use_llm=False,
        run_mumei=False,
    )

    assert result.success is False
    assert result.missing_constraints
    assert result.missing_constraints[0] == "x > 0"
    assert result.missing_constraint_issues[0].kind == "missing_implementation"
    assert "x > 0" in result.missing_constraint_issues[0].evidence
    assert result.constraint_violations[0]["spec_constraint"] == "x > 0"
    assert result.constraint_violations[0]["code_line"] == 1
    assert "def identity" in str(result.constraint_violations[0]["code_snippet"])


def test_validate_spec_to_code_surfaces_spec_validation_issues(tmp_path: Path) -> None:
    code_path = tmp_path / "impl.py"
    code_path.write_text("def identity(x: int) -> int:\n    return x\n", encoding="utf-8")

    result = validate_spec_to_code(
        "常に残高を更新する、かつ決して残高を更新する。requires: true;\nensures: result == x;",
        str(code_path),
        config=AgentConfig(api_key=""),
        use_llm=False,
        run_mumei=False,
    )

    assert result.success is False
    assert any(issue.message.startswith("Spec validation issue") for issue in result.divergences)
    assert result.constraint_violations == []


def test_validate_code_to_spec_detects_postcondition_drift(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.txt"
    code_path = tmp_path / "impl.py"
    spec_path.write_text("requires: true;\nensures: result == x + 1;", encoding="utf-8")
    code_path.write_text("def inc(x: int) -> int:\n    return x + 2\n", encoding="utf-8")

    result = validate_code_to_spec(
        str(code_path),
        str(spec_path),
        config=AgentConfig(api_key=""),
        use_llm=False,
        run_mumei=False,
    )

    assert result.success is False
    assert result.drift_issues
    assert result.drift_issues[0].kind == "drift"


def test_validate_code_to_spec_detects_go_postcondition_drift(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.txt"
    code_path = tmp_path / "impl.go"
    spec_path.write_text("requires: true;\nensures: result == x + 1;", encoding="utf-8")
    code_path.write_text(
        "package demo\nfunc inc(x int) int { return x + 2 }\n",
        encoding="utf-8",
    )

    result = validate_code_to_spec(
        str(code_path),
        str(spec_path),
        config=AgentConfig(api_key=""),
        language="go",
        use_llm=False,
        run_mumei=False,
    )

    assert result.success is False
    assert result.language == "go"
    assert result.drift_issues
    assert result.drift_issues[0].kind == "drift"


def test_validate_code_to_spec_detects_undocumented_code_precondition(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.txt"
    code_path = tmp_path / "impl.py"
    spec_path.write_text("requires: true;\nensures: result == a // b;", encoding="utf-8")
    code_path.write_text("def div(a: int, b: int) -> int:\n    return a // b\n", encoding="utf-8")

    result = validate_code_to_spec(
        str(code_path),
        str(spec_path),
        config=AgentConfig(api_key=""),
        use_llm=False,
        run_mumei=False,
    )

    assert result.success is False
    assert any("not documented" in issue.message for issue in result.drift_issues)


def test_validate_spec_to_code_cli_emits_japanese_report(tmp_path: Path, capsys) -> None:
    spec_path = tmp_path / "spec.txt"
    code_path = tmp_path / "impl.py"
    report_path = tmp_path / "report.md"
    spec_path.write_text("requires: true;\nensures: result == a + b;", encoding="utf-8")
    code_path.write_text("def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")
    args = build_validate_spec_to_code_parser().parse_args(
        [
            "--spec",
            str(spec_path),
            "--code",
            str(code_path),
            "--lang",
            "ja",
            "--output",
            str(report_path),
            "--no-llm",
            "--no-mumei",
        ]
    )

    result = main_validate_spec_to_code(args)
    captured = capsys.readouterr()

    assert result.success is True
    assert "仕様→コード適合レポート" in captured.out
    assert "次の手順 (V1-E-1)" in report_path.read_text(encoding="utf-8")


def test_new_cross_validation_parsers_accept_lang_and_paths() -> None:
    spec_to_code_args = build_validate_spec_to_code_parser().parse_args(
        ["--spec", "spec.txt", "--code", "code.py", "--lang", "ja", "--format", "human", "--no-mumei"]
    )
    code_to_spec_args = build_validate_code_to_spec_parser().parse_args(
        ["--code", "code.py", "--spec", "spec.txt", "--lang", "en", "--format", "json", "--no-llm"]
    )

    assert spec_to_code_args.lang == "ja"
    assert spec_to_code_args.format == "human"
    assert spec_to_code_args.code == "code.py"
    assert code_to_spec_args.spec == "spec.txt"
    assert code_to_spec_args.format == "json"


def test_cross_validation_formatter_highlights_human_review() -> None:
    result = {
        "success": False,
        "code_path": "impl.py",
        "language": "python",
        "spec_atoms": [],
        "code_atoms": [],
        "drift_issues": [
            {
                "kind": "drift",
                "message": "Spec postcondition is stale.",
                "evidence": "result == x + 1",
                "location": "inc",
            }
        ],
        "changed_hunks": ["@@ -1 +1 @@\n-return x + 1\n+return x + 2"],
        "warnings": [],
        "errors": [],
    }

    report = format_cross_validation_report(result, lang="ja")

    assert "コード→仕様ドリフトレポート" in report
    assert "次の手順 (V1-E-1)" in report
    assert "Human-in-the-Loop" not in report


def test_cross_validation_prompts_include_json_schema() -> None:
    nl_prompt = build_nl_cross_validation_prompt("常Xか決て")
    code_prompt = build_code_cross_validation_prompt("def add(a, b): return a + b", "python")
    conformance_prompt = build_conformance_verification_prompt(
        "requires: true; ensures: result == a + b",
        "def add(a, b): return a + b",
        "python",
    )

    assert "requires" in nl_prompt
    assert "ensures" in nl_prompt
    assert "```json" in code_prompt
    assert "traceability_matrix" in conformance_prompt
    assert "next_steps" in conformance_prompt
    assert "def add" in code_prompt
    assert "source_line" not in code_prompt


def test_spec_to_code_line_mapping_ignores_llm_source_line() -> None:
    issue = CrossValidationIssue(
        kind="alignment",
        message="Code behavior for `identity` does not imply the spec postcondition.",
        evidence="spec ensures: result == x + 1; code ensures: result == x",
        location="identity",
        source_line=99,
    )

    [mapped] = _with_spec_code_source_lines(
        [issue],
        source_line_map={"identity": 2},
        constraint_to_line={"result == x + 1": 3},
    )

    assert mapped.source_line == 3


def test_validate_nl_spec_sets_spec_internal_contradiction_type() -> None:
    """Spec-internal contradictions set contradiction_type == 'spec_internal'."""
    spec = (
        "常に残高を更新する、かつ決して残高を更新する。"
        "requires: x > 0 && x < 0;\n"
        "ensures: result == x;"
    )

    result = validate_nl_spec(
        spec,
        config=AgentConfig(api_key=""),
        use_llm=False,
        run_mumei=False,
    )

    assert result.success is False
    assert result.contradictions
    assert result.contradiction_type == "spec_internal"


def test_validate_nl_spec_sets_overconstraint_contradiction_type() -> None:
    result = validate_nl_spec(
        "requires: x > 0 && x < 0;\nensures: result == x;",
        config=AgentConfig(api_key=""),
        use_llm=False,
        run_mumei=False,
    )

    assert result.contradiction_type == "spec_overconstraint"


def test_validate_nl_spec_sets_vacuity_contradiction_type() -> None:
    result = validate_nl_spec(
        "requires: true;\nensures: true;",
        config=AgentConfig(api_key=""),
        use_llm=False,
        run_mumei=False,
    )

    assert result.contradiction_type == "spec_vacuity"


def test_validate_spec_to_code_sets_spec_vs_code_contradiction_type(tmp_path: Path) -> None:
    """Code comparison divergence sets contradiction_type to a spec_vs_code variant."""
    code_path = tmp_path / "impl.py"
    code_path.write_text("def identity(x: int) -> int:\n    return x\n", encoding="utf-8")

    result = validate_spec_to_code(
        "requires: x > 0;\nensures: result == x;",
        str(code_path),
        config=AgentConfig(api_key=""),
        use_llm=False,
        run_mumei=False,
    )

    assert result.success is False
    assert result.contradiction_type == "spec_vs_code"
    assert result.constraint_violations
    assert result.constraint_violations[0]["contradiction_type"] == "spec_stronger"


def test_validate_code_to_spec_sets_spec_vs_code_contradiction_type(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.txt"
    code_path = tmp_path / "impl.py"
    spec_path.write_text("requires: true;\nensures: result == x + 1;", encoding="utf-8")
    code_path.write_text("def inc(x: int) -> int:\n    return x + 2\n", encoding="utf-8")

    result = validate_code_to_spec(
        str(code_path),
        str(spec_path),
        config=AgentConfig(api_key=""),
        use_llm=False,
        run_mumei=False,
    )

    assert result.contradiction_type == "spec_vs_code"


def test_no_mm_audit_terms_do_not_alias_cross_validation_keys() -> None:
    from agent.audit import AUDIT_SCHEMA_KEYS

    assert "cross_validation_gaps" in AUDIT_SCHEMA_KEYS
    assert "next_steps" in AUDIT_SCHEMA_KEYS
    assert "missing_constraints" not in AUDIT_SCHEMA_KEYS
    assert "divergences" not in AUDIT_SCHEMA_KEYS
    assert "repair_hints" not in AUDIT_SCHEMA_KEYS


def test_verify_conformance_returns_structured_json_keys(tmp_path: Path) -> None:
    code = tmp_path / "impl.py"
    code.write_text("def identity(x: int) -> int:\n    return x\n", encoding="utf-8")

    result = verify_conformance(
        "requires: x >= 0;\nensures: result == x + 1;",
        str(code),
        config=AgentConfig(api_key=""),
        language="python",
        use_llm=False,
        run_mumei=False,
    )
    payload = result.__dict__

    assert result.success is False
    assert result.unimplemented_conditions
    assert result.verification_violations
    assert result.cross_validation_gaps
    assert result.next_steps
    assert result.traceability_matrix
    assert "human_review" not in payload
    assert "recommendations" not in payload


def test_verify_conformance_detects_hidden_specifications(tmp_path: Path) -> None:
    code = tmp_path / "impl.py"
    code.write_text("def divide(a: int, b: int) -> int:\n    return a // b\n", encoding="utf-8")

    result = verify_conformance(
        "requires: true;\nensures: result == a / b;",
        str(code),
        config=AgentConfig(api_key=""),
        language="python",
        use_llm=False,
        run_mumei=False,
    )

    assert result.hidden_specifications
    assert result.hidden_specifications[0].condition == "b != 0"
    assert result.cross_validation_gaps
    assert result.next_steps


def test_validate_code_to_spec_reports_spec_gaps_and_next_steps(tmp_path: Path) -> None:
    code = tmp_path / "impl.py"
    spec = tmp_path / "spec.txt"
    code.write_text("def identity(x: int) -> int:\n    return x\n", encoding="utf-8")
    spec.write_text("requires: true;\nensures: result == x + 1;", encoding="utf-8")

    result = validate_code_to_spec(
        str(code),
        str(spec),
        config=AgentConfig(api_key=""),
        language="python",
        use_llm=False,
        run_mumei=False,
    )
    payload = result.__dict__

    assert result.extracted_spec
    assert result.spec_gaps
    assert result.cross_validation_gaps
    assert result.next_steps == [
        {
            "priority": "high",
            "action": "Update the natural-language spec or justify the extra implementation.",
            "command": f"mumei-agent validate-code-to-spec --code {code} --spec {spec} --format human",
        }
    ]
    assert "human_review" not in payload
    assert "review_actions" not in payload

def test_verify_conformance_human_report_keeps_next_steps_first_and_review_keys(
    tmp_path: Path,
) -> None:
    code = tmp_path / "impl.py"
    code.write_text("def identity(x: int) -> int:\n    return x\n", encoding="utf-8")

    result = verify_conformance(
        "requires: x >= 0;\nensures: result == x + 1;",
        str(code),
        config=AgentConfig(api_key=""),
        language="python",
        use_llm=False,
        run_mumei=False,
    )

    assert result.next_steps
    assert result.cross_validation_gaps
    assert result.report.index("### next_steps (V1-E-1)") < result.report.index(
        "### Human review entrypoints"
    )
    assert "`cross_validation_gaps`" in result.report
    assert "```bash" in result.report


def test_verify_conformance_cli_formats_keep_next_steps_and_fixed_keys(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = tmp_path / "impl.py"
    json_output = tmp_path / "conformance.json"
    code.write_text("def identity(x: int) -> int:\n    return x\n", encoding="utf-8")
    args = build_verify_conformance_parser().parse_args(
        [
            "--spec",
            "spec.txt",
            "--code",
            str(code),
            "--format",
            "markdown",
            "--lang",
            "en",
            "--no-mumei",
        ]
    )

    result = verify_conformance(
        "requires: x >= 0;\nensures: result == x + 1;",
        str(code),
        config=AgentConfig(api_key=""),
        language="python",
        use_llm=False,
        run_mumei=False,
    )

    assert args.format == "markdown"
    assert args.lang == "en"
    for output_format in ("human", "markdown"):
        emit_conformance_report(result, None, output_format, "en")
        report = capsys.readouterr().out
        assert report.index("### next_steps (V1-E-1)") < report.index(
            "### Human review entrypoints"
        )
        assert "`cross_validation_gaps`" in report
        assert "recommendations" not in report
        assert "review_actions" not in report
        assert "human_review" not in report

    emit_conformance_report(result, str(json_output), "json", "en")
    payload = json.loads(json_output.read_text(encoding="utf-8"))
    assert payload["next_steps"] == result.next_steps
    assert payload["verification_violations"] == result.verification_violations
    assert payload["cross_validation_gaps"] == result.cross_validation_gaps
    assert "recommendations" not in payload
    assert "review_actions" not in payload
    assert "human_review" not in payload


def test_validate_code_to_spec_human_report_preserves_drift_review_entrypoint(
    tmp_path: Path,
) -> None:
    code = tmp_path / "impl.py"
    spec = tmp_path / "spec.txt"
    code.write_text("def inc(x: int) -> int:\n    return x + 2\n", encoding="utf-8")
    spec.write_text("requires: true;\nensures: result == x + 1;", encoding="utf-8")

    result = validate_code_to_spec(
        str(code),
        str(spec),
        config=AgentConfig(api_key=""),
        language="python",
        use_llm=False,
        run_mumei=False,
    )

    assert result.next_steps
    assert result.drift_issues
    assert result.cross_validation_gaps
    assert result.report.index("### next_steps (V1-E-1)") < result.report.index(
        "### Human review entrypoints"
    )
    assert "`drift_issues`" in result.report
    assert "```bash" in result.report


def test_verify_conformance_accepts_typescript_language(tmp_path: Path) -> None:
    code = tmp_path / "impl.ts"
    code.write_text(
        "export function identity(x: number): number { return x; }\n",
        encoding="utf-8",
    )

    result = verify_conformance(
        "requires: x > 0;\nensures: result == x;",
        str(code),
        config=AgentConfig(api_key=""),
        language="typescript",
        use_llm=False,
        run_mumei=False,
    )

    assert result.language == "typescript"
    assert result.traceability_matrix


def test_verify_conformance_typescript_source_line_map(tmp_path: Path) -> None:
    ts_code = "export function add(a: number, b: number): number {\n  return a + b;\n}\n"
    code = tmp_path / "math.ts"
    code.write_text(ts_code, encoding="utf-8")

    result = verify_conformance(
        "requires: true;\nensures: result == a + b;",
        str(code),
        config=AgentConfig(api_key=""),
        language="typescript",
        use_llm=False,
        run_mumei=False,
    )

    assert result.language == "typescript"
    matrix_lines = [row.code_line for row in result.traceability_matrix if row.code_line > 0]
    assert matrix_lines, "traceability_matrix should have non-zero code_line entries for TypeScript"


def test_verify_conformance_typescript_next_steps_before_findings(tmp_path: Path) -> None:
    code = tmp_path / "impl.ts"
    code.write_text(
        "export function identity(x: number): number { return x; }\n",
        encoding="utf-8",
    )

    result = verify_conformance(
        "requires: x > 0;\nensures: result == x;",
        str(code),
        config=AgentConfig(api_key=""),
        language="typescript",
        use_llm=False,
        run_mumei=False,
    )

    assert result.next_steps
    assert result.report.index("### next_steps (V1-E-1)") < result.report.index(
        "### Human review entrypoints"
    )


def test_json_from_text_tolerates_trailing_prose() -> None:
    from agent.cross_validation_payload import _json_from_text

    # JSON, then a trailing sentence (the common local/OSS-model shape).
    assert _json_from_text('{"atoms": []}\n\nThis contract has no preconditions.') == {
        "atoms": []
    }
    # Leading prose, then JSON (previously the only tolerated shape).
    assert _json_from_text("Here is the JSON:\n{\"atoms\": []}") == {"atoms": []}
    # A fenced object with nested braces must survive intact.
    assert _json_from_text(
        '```json\n{"atoms": [{"name": "f", "params": []}]}\n```'
    ) == {"atoms": [{"name": "f", "params": []}]}
    # A non-object first value is still rejected.
    with pytest.raises(json.JSONDecodeError):
        _json_from_text("[1, 2, 3]")
