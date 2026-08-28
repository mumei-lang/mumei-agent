"""Scale composability reporting uses the fixed audit keys only."""
import json

from agent.scale_report import FIXED_KEYS, build_report, render

COMPOSABILITY = {
    "schema": "mumei.composability/v1",
    "budget_policy_fingerprint": "sha256:scale-default",
    "cases": [
        {
            "case": "rtgs_settlement_scale",
            "source": "rtgs_settlement_scale/correct_code.mm",
            "atom_count": 30,
            "max_dependency_depth": 5,
            "top_level_atoms": ["two_settlement_cycles"],
            "whole_system_invariants_closed": 1,
            "atom_local_obligations": 12,
            "composition_breaks": 2,
            "atom_local_closure_ratio": 0.857,
            "breaks": [
                {
                    "atom": "min_amount",
                    "clause_kind": "ensures",
                    "clause_line": 49,
                    "clause_text": "ensures: result <= left;",
                    "affected_atoms": ["settleable_amount"],
                    "pattern": "neighbor_ensures_strengthening",
                    "diagnostic": "postcondition not provable",
                },
                {
                    "atom": "stage_reserve",
                    "clause_kind": "effect_post",
                    "clause_line": 260,
                    "clause_text": "effect_post: Settlement::Reserved;",
                    "affected_atoms": ["phase_reserve_and_net"],
                    "pattern": "effect_state_obligation",
                    "diagnostic": "InvalidPreState",
                },
            ],
        }
    ],
    "modular_verification_inputs": {
        "neighbor_ensures_strengthening": {
            "compiler_surface": "value contracts (`ensures`) of called atoms",
            "count": 1,
            "examples": ["rtgs_settlement_scale:min_amount:ensures@49"],
        },
        "effect_state_obligation": {
            "compiler_surface": "`effect_pre` / `effect_post` state chaining (Plan 24)",
            "count": 1,
            "examples": ["rtgs_settlement_scale:stage_reserve:effect_post@260"],
        },
    },
}

TRUST_SURFACE = {
    "schema": "mumei.scale_trust_surface/v1",
    "budget_policy_fingerprint": "sha256:scale-default",
    "std_trust_surface": {"std_atoms": 344, "std_trusted_atoms": 0},
    "cases": [
        {
            "case": "rtgs_settlement_scale",
            "atom_count": 30,
            "certified_atoms": 30,
            "all_atoms_certified": True,
            "verify_cert_strict": True,
            "verify_cert_strict_exit_code": 0,
            "trust_surface": {
                "application_trusted_atoms": 0,
                "ffi_boundary_declarations": 0,
                "z3_unknown_to_lean_escalation_atoms": 0,
            },
        }
    ],
}


def test_report_exposes_only_fixed_keys():
    report = build_report(COMPOSABILITY, TRUST_SURFACE)
    for key in FIXED_KEYS:
        assert key in report
    forbidden = {
        "recommendations",
        "actions",
        "audit_issues",
        "verification_gaps",
        "repair_hints",
        "review_actions",
        "human_review",
    }
    assert forbidden.isdisjoint(report)


def test_composition_breaks_reach_verification_violations():
    report = build_report(COMPOSABILITY, TRUST_SURFACE)
    assert report["verification_status"] == "verified"
    assert len(report["verification_violations"]) == 2
    assert any("min_amount" in item for item in report["verification_violations"])
    assert any("effect_state_obligation" in item for item in report["verification_violations"])
    assert report["budget_policy_fingerprint"] == "sha256:scale-default"


def test_break_patterns_become_next_steps():
    report = build_report(COMPOSABILITY, TRUST_SURFACE)
    actions = [step["action"] for step in report["next_steps"]]
    assert any("effect_pre" in action for action in actions)
    assert all(step["priority"] in {"high", "medium", "low"} for step in report["next_steps"])


def test_strict_certificate_failure_is_refuted():
    trust = json.loads(json.dumps(TRUST_SURFACE))
    trust["cases"][0]["verify_cert_strict"] = False
    trust["cases"][0]["verify_cert_strict_exit_code"] = 1
    report = build_report(COMPOSABILITY, trust)
    assert report["verification_status"] == "refuted"
    assert report["success"] is False
    assert any("verify-cert --strict" in item for item in report["verification_violations"])


def test_std_trusted_atom_regression_is_refuted():
    trust = json.loads(json.dumps(TRUST_SURFACE))
    trust["std_trust_surface"]["std_trusted_atoms"] = 3
    report = build_report(COMPOSABILITY, trust)
    assert report["verification_status"] == "refuted"
    assert any("std/" in item for item in report["verification_violations"])


def test_missing_cases_is_unverifiable():
    report = build_report({"cases": [], "modular_verification_inputs": {}}, None)
    assert report["verification_status"] == "unverifiable"


def test_human_render_lists_fixed_key_sections():
    text = render(build_report(COMPOSABILITY, TRUST_SURFACE), "human")
    assert "verification_status:" in text
    assert "verification_violations" in text
    assert "next_steps" in text
