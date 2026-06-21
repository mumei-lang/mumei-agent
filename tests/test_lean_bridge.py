"""Unit tests for ``agent.lean_bridge`` — Task 2-C mumei-lean fallback."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from agent import lean_bridge


# ---------------------------------------------------------------------------
# extract_unknown_atoms
# ---------------------------------------------------------------------------


class TestExtractUnknownAtoms:
    def test_returns_unknown_atoms_from_flat_certificate(self) -> None:
        cert = {
            "atoms": [
                {"name": "a1", "z3_check_result": "unsat"},
                {"name": "a2", "z3_check_result": "unknown"},
                {"name": "a3", "z3_check_result": "unknown"},
                {"name": "a4", "z3_check_result": "sat"},
            ]
        }
        result = lean_bridge.extract_unknown_atoms(cert)
        assert [a["name"] for a in result] == ["a2", "a3"]

    def test_handles_wrapper_under_certificate_key(self) -> None:
        wrapper = {
            "certificate": {
                "atoms": [
                    {"name": "wrapped_unknown", "z3_check_result": "unknown"},
                ]
            }
        }
        result = lean_bridge.extract_unknown_atoms(wrapper)
        assert len(result) == 1
        assert result[0]["name"] == "wrapped_unknown"

    def test_handles_bundle_modules_recursively(self) -> None:
        bundle = {
            "modules": {
                "std/foo.mm": {
                    "atoms": [
                        {"name": "foo_ok", "z3_check_result": "unsat"},
                        {"name": "foo_pending", "z3_check_result": "unknown"},
                    ]
                },
                "std/bar.mm": {
                    "atoms": [
                        {"name": "bar_pending", "z3_check_result": "unknown"},
                    ]
                },
            }
        }
        result = lean_bridge.extract_unknown_atoms(bundle)
        assert sorted(a["name"] for a in result) == [
            "bar_pending",
            "foo_pending",
        ]

    def test_returns_empty_list_for_non_dict(self) -> None:
        assert lean_bridge.extract_unknown_atoms(None) == []  # type: ignore[arg-type]
        assert lean_bridge.extract_unknown_atoms([]) == []  # type: ignore[arg-type]

    def test_returns_empty_list_when_no_unknowns(self) -> None:
        cert = {
            "atoms": [
                {"name": "a", "z3_check_result": "unsat"},
                {"name": "b", "z3_check_result": "sat"},
            ]
        }
        assert lean_bridge.extract_unknown_atoms(cert) == []

    def test_counts_promoted_unknowns_recursively(self) -> None:
        original = {
            "modules": {
                "std/foo": {
                    "atoms": [
                        {"name": "foo", "z3_check_result": "unknown"},
                        {"name": "bar", "z3_check_result": "unknown"},
                    ]
                }
            }
        }
        upgraded = {
            "modules": {
                "std/foo": {
                    "atoms": [
                        {"name": "foo", "z3_check_result": "lean_verified"},
                        {"name": "bar", "z3_check_result": "unknown"},
                    ]
                }
            }
        }

        assert lean_bridge.count_lean_verified_unknowns(original, upgraded) == 1


# ---------------------------------------------------------------------------
# run_lean_bridge (subprocess invocation)
# ---------------------------------------------------------------------------


class TestRunLeanBridgeSubprocess:
    def test_missing_repo_returns_failure(self, tmp_path: Path) -> None:
        result = lean_bridge.run_lean_bridge(
            cert_path=tmp_path / "in.json",
            lean_cert_out=tmp_path / "out.json",
            mumei_lean_repo=tmp_path / "does-not-exist",
        )
        assert result["success"] is False
        assert result["returncode"] == -1
        assert result["error_code"] == "repo_missing"
        assert "does not exist" in result["stderr"]

    def test_missing_bridge_script_returns_failure(self, tmp_path: Path) -> None:
        repo = tmp_path / "fake-mumei-lean"
        repo.mkdir()
        result = lean_bridge.run_lean_bridge(
            cert_path=tmp_path / "in.json",
            lean_cert_out=tmp_path / "out.json",
            mumei_lean_repo=repo,
        )
        assert result["success"] is False
        assert result["error_code"] == "bridge_missing"
        assert "bridge.py not found" in result["stderr"]

    def test_subprocess_invoked_and_cert_loaded(self, tmp_path: Path) -> None:
        # Arrange: scaffold a fake mumei-lean checkout.
        repo = tmp_path / "mumei-lean"
        (repo / "scripts").mkdir(parents=True)
        (repo / "scripts" / "bridge.py").write_text(
            "# stub\n", encoding="utf-8"
        )
        cert_path = tmp_path / "in.proof-cert.json"
        cert_path.write_text(
            json.dumps({"atoms": []}), encoding="utf-8"
        )
        lean_cert_out = tmp_path / "out.lean-cert.json"
        # Pre-write the file the subprocess would have produced so the
        # mocked subprocess can be a no-op while still exercising the
        # JSON-load path inside run_lean_bridge.
        lean_cert_out.write_text(
            json.dumps(
                {
                    "atoms": [
                        {
                            "name": "stubbed",
                            "z3_check_result": "lean_verified",
                        }
                    ],
                    "lean_version": "4.7.0",
                }
            ),
            encoding="utf-8",
        )

        # Act
        with patch("agent.lean_bridge.subprocess.run") as run_mock:
            run_mock.return_value = MagicMock(
                returncode=0, stdout="ok\n", stderr=""
            )
            result = lean_bridge.run_lean_bridge(
                cert_path=cert_path,
                lean_cert_out=lean_cert_out,
                mumei_lean_repo=repo,
                no_build=True,
            )

        # Assert: subprocess invoked with the expected --no-build flag
        # and the lean cert was parsed back.
        run_mock.assert_called_once()
        cmd = run_mock.call_args.args[0]
        assert "--no-build" in cmd
        assert "--cert" in cmd
        assert "--lean-cert-out" in cmd
        assert result["success"] is True
        assert result["returncode"] == 0
        assert result["lean_cert"] is not None
        assert result["lean_cert"]["lean_version"] == "4.7.0"

    def test_subprocess_invoked_with_escalation_bundle(
        self, tmp_path: Path
    ) -> None:
        repo = tmp_path / "mumei-lean"
        (repo / "scripts").mkdir(parents=True)
        (repo / "scripts" / "bridge.py").write_text(
            "# stub\n", encoding="utf-8"
        )
        bundle_path = tmp_path / "std-abs.escalation-bundle.json"
        bundle_path.write_text(
            json.dumps({"candidates": [{"name": "abs_saturating"}]}),
            encoding="utf-8",
        )
        lean_cert_out = tmp_path / "std-abs.lean-cert.json"
        lean_cert_out.write_text(
            json.dumps(
                {
                    "candidates": [
                        {
                            "name": "abs_saturating",
                            "z3_check_result": "lean_verified",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        with patch("agent.lean_bridge.subprocess.run") as run_mock:
            run_mock.return_value = MagicMock(
                returncode=0, stdout="ok\n", stderr=""
            )
            result = lean_bridge.run_lean_bridge(
                cert_path=None,
                lean_cert_out=lean_cert_out,
                mumei_lean_repo=repo,
                no_build=True,
                escalation_bundle_path=bundle_path,
            )

        run_mock.assert_called_once()
        cmd = run_mock.call_args.args[0]
        assert "--escalation-bundle" in cmd
        assert str(bundle_path) in cmd
        assert "--cert" not in cmd
        assert "--lean-cert-out" in cmd
        assert str(lean_cert_out) in cmd
        assert result["success"] is True
        assert result["lean_cert"]["candidates"][0]["name"] == "abs_saturating"

    def test_escalation_bundle_defaults_lean_cert_out(
        self, tmp_path: Path
    ) -> None:
        repo = tmp_path / "mumei-lean"
        (repo / "scripts").mkdir(parents=True)
        (repo / "scripts" / "bridge.py").write_text(
            "# stub\n", encoding="utf-8"
        )
        bundle_path = tmp_path / "std-abs.escalation-bundle.json"
        bundle_path.write_text(
            json.dumps({"candidates": [{"name": "abs_saturating"}]}),
            encoding="utf-8",
        )
        default_out = tmp_path / "std-abs.lean-cert.json"
        default_out.write_text(
            json.dumps({"candidates": [{"name": "abs_saturating"}]}),
            encoding="utf-8",
        )

        with patch("agent.lean_bridge.subprocess.run") as run_mock:
            run_mock.return_value = MagicMock(
                returncode=0, stdout="ok\n", stderr=""
            )
            result = lean_bridge.run_lean_bridge(
                cert_path=None,
                lean_cert_out=None,
                mumei_lean_repo=repo,
                no_build=True,
                escalation_bundle_path=bundle_path,
            )

        cmd = run_mock.call_args.args[0]
        assert str(default_out) in cmd
        assert result["lean_cert_path"] == str(default_out)

    def test_subprocess_failure_propagates_returncode(
        self, tmp_path: Path
    ) -> None:
        repo = tmp_path / "mumei-lean"
        (repo / "scripts").mkdir(parents=True)
        (repo / "scripts" / "bridge.py").write_text("# stub\n")
        cert_path = tmp_path / "in.json"
        cert_path.write_text(json.dumps({"atoms": []}))
        lean_cert_out = tmp_path / "missing.json"
        with patch("agent.lean_bridge.subprocess.run") as run_mock:
            run_mock.return_value = MagicMock(
                returncode=1, stdout="", stderr="lake build failed"
            )
            result = lean_bridge.run_lean_bridge(
                cert_path=cert_path,
                lean_cert_out=lean_cert_out,
                mumei_lean_repo=repo,
            )
        assert result["success"] is False
        assert result["returncode"] == 1
        assert result["lean_cert"] is None
        assert result["error_code"] == "bridge_failed"
        assert result["diagnostics"]

    def test_lake_missing_returns_diagnostic(self, tmp_path: Path) -> None:
        repo = tmp_path / "mumei-lean"
        (repo / "scripts").mkdir(parents=True)
        (repo / "scripts" / "bridge.py").write_text("# stub\n")
        (repo / "lakefile.lean").write_text("-- lake project\n")

        with patch("agent.lean_bridge.shutil.which", return_value=None):
            result = lean_bridge.run_lean_bridge(
                cert_path=tmp_path / "in.json",
                lean_cert_out=tmp_path / "out.json",
                mumei_lean_repo=repo,
            )

        assert result["success"] is False
        assert result["error_code"] == "lake_missing"
        assert "lake" in result["stderr"]

    def test_partial_translation_failure_is_classified(
        self, tmp_path: Path
    ) -> None:
        repo = tmp_path / "mumei-lean"
        (repo / "scripts").mkdir(parents=True)
        (repo / "scripts" / "bridge.py").write_text("# stub\n")
        cert_path = tmp_path / "in.json"
        cert_path.write_text(json.dumps({"atoms": []}))

        with patch("agent.lean_bridge.subprocess.run") as run_mock:
            run_mock.return_value = MagicMock(
                returncode=1,
                stdout="partial_translation: unsupported expression",
                stderr="manual_review",
            )
            result = lean_bridge.run_lean_bridge(
                cert_path=cert_path,
                lean_cert_out=tmp_path / "out.json",
                mumei_lean_repo=repo,
            )

        assert result["success"] is False
        assert result["error_code"] == "partial_translation"
        assert result["retryable"] is False

    def test_failure_taxonomy_classifies_lean_errors(
        self, tmp_path: Path
    ) -> None:
        repo = tmp_path / "mumei-lean"
        (repo / "scripts").mkdir(parents=True)
        (repo / "scripts" / "bridge.py").write_text("# stub\n")
        cert_path = tmp_path / "in.json"
        cert_path.write_text(json.dumps({"atoms": []}))

        cases = [
            ("error: unknown constant foo_correct", "theorem_not_found", False),
            ("error: unsolved goals\n⊢ 0 ≤ result", "tactic_failed", False),
            ("invalid 'import' command: could not find module", "import_error", True),
        ]
        for stderr, expected_code, expected_retryable in cases:
            with patch("agent.lean_bridge.subprocess.run") as run_mock:
                run_mock.return_value = MagicMock(
                    returncode=1, stdout="", stderr=stderr
                )
                result = lean_bridge.run_lean_bridge(
                    cert_path=cert_path,
                    lean_cert_out=tmp_path / f"{expected_code}.json",
                    mumei_lean_repo=repo,
                )
            assert result["success"] is False
            assert result["error_code"] == expected_code
            assert result["retryable"] is expected_retryable

    def test_known_witness_fallback_upgrades_std_atoms(
        self, tmp_path: Path
    ) -> None:
        repo = tmp_path / "mumei-lean"
        (repo / "scripts").mkdir(parents=True)
        (repo / "scripts" / "bridge.py").write_text("# stub\n")
        (repo / "MumeiLean").mkdir()
        (repo / "MumeiLean" / "StdMathAbs.lean").write_text(
            "theorem abs_saturating_correct : True := by trivial\n"
            "theorem list_length_correct : True := by trivial\n",
            encoding="utf-8",
        )
        cert_path = tmp_path / "in.json"
        cert_path.write_text(
            json.dumps(
                {
                    "all_verified": False,
                    "atoms": [
                        {"name": "abs_saturating", "z3_check_result": "unknown"},
                        {"name": "list_length", "z3_check_result": "unknown"},
                    ],
                }
            )
        )

        with patch("agent.lean_bridge.subprocess.run") as run_mock, patch(
            "agent.lean_bridge.shutil.which", return_value="/usr/bin/lake"
        ):
            run_mock.side_effect = [
                MagicMock(
                    returncode=1,
                    stdout="",
                    stderr="error: unsolved goals\n⊢ 0 ≤ result",
                ),
                MagicMock(returncode=0, stdout="built StdMathAbs", stderr=""),
            ]
            result = lean_bridge.run_lean_bridge(
                cert_path=cert_path,
                lean_cert_out=tmp_path / "out.json",
                mumei_lean_repo=repo,
            )

        assert result["success"] is True
        assert result["error_code"] is None
        assert result["primary_error_code"] == "tactic_failed"
        assert result["fallback_strategy"] == "known_witness_module"
        atoms = result["lean_cert"]["atoms"]
        assert [a["z3_check_result"] for a in atoms] == [
            "lean_verified",
            "lean_verified",
        ]

    def test_known_witness_fallback_upgrades_domain_atoms(
        self, tmp_path: Path
    ) -> None:
        repo = tmp_path / "mumei-lean"
        (repo / "MumeiLean").mkdir(parents=True)
        witnesses = [
            ("balance_conservation", "std/finance/settlement", "MumeiLean.Settlement"),
            (
                "trace_balance_conservation",
                "std/finance/settlement",
                "MumeiLean.Settlement",
            ),
            (
                "no_settlement_without_validate",
                "std/finance/settlement",
                "MumeiLean.Settlement",
            ),
            (
                "no_reentrancy_after_withdraw",
                "std/contract/vault",
                "MumeiLean.SmartContract",
            ),
            (
                "withdraw_preserves_other_balance",
                "std/contract/vault",
                "MumeiLean.SmartContract",
            ),
            (
                "withdraw_amount_nonnegative_bound",
                "std/contract/vault",
                "MumeiLean.SmartContract",
            ),
            (
                "nlae_vault_withdraw_amount_nonnegative_bound",
                "examples/nlae_integration_demo",
                "MumeiLean.SmartContract",
            ),
            (
                "nlae_vault_no_negative_withdraw",
                "examples/nlae_integration_demo",
                "MumeiLean.SmartContract",
            ),
            ("add_bounded", "std/math/patterns", "MumeiLean.Patterns"),
            ("transfer_preserves_sum", "std/math/patterns", "MumeiLean.Patterns"),
        ]
        for module in {module for _, _, module in witnesses}:
            source = repo / Path(*module.split(".")).with_suffix(".lean")
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(
                "".join(
                    f"theorem {name} : True := by trivial\n"
                    for name, _, witness_module in witnesses
                    if witness_module == module
                ),
                encoding="utf-8",
            )
        cert_path = tmp_path / "in.json"
        cert_path.write_text(
            json.dumps(
                {
                    "all_verified": False,
                    "atoms": [
                        {
                            "name": name,
                            "module_key": module_key,
                            "z3_check_result": "unknown",
                        }
                        for name, module_key, _ in witnesses
                    ],
                }
            )
        )

        with patch("agent.lean_bridge.subprocess.run") as run_mock, patch(
            "agent.lean_bridge.shutil.which", return_value="/usr/bin/lake"
        ):
            run_mock.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = lean_bridge._verify_known_witnesses(
                cert_path=cert_path,
                mumei_lean_repo=repo,
                timeout=600.0,
            )

        assert result is not None
        assert result["success"] is True
        assert result["known_witness_verified"] == len(witnesses)
        assert [
            call.args[0] for call in run_mock.call_args_list
        ] == [
            ["lake", "build", "MumeiLean.Patterns"],
            ["lake", "build", "MumeiLean.Settlement"],
            ["lake", "build", "MumeiLean.SmartContract"],
        ]
        assert {
            atom["name"]
            for atom in result["lean_cert"]["atoms"]
            if atom["z3_check_result"] == "lean_verified"
        } == {name for name, _, _ in witnesses}

    def test_known_witness_fallback_requires_matching_module_key(
        self, tmp_path: Path
    ) -> None:
        repo = tmp_path / "mumei-lean"
        (repo / "MumeiLean").mkdir(parents=True)
        (repo / "MumeiLean" / "Settlement.lean").write_text(
            "theorem balance_conservation : True := by trivial\n",
            encoding="utf-8",
        )
        cert_path = tmp_path / "in.json"
        cert_path.write_text(
            json.dumps(
                {
                    "all_verified": False,
                    "atoms": [
                        {
                            "name": "balance_conservation",
                            "module_key": "custom/settlement",
                            "z3_check_result": "unknown",
                        }
                    ],
                }
            )
        )

        with patch("agent.lean_bridge.subprocess.run") as run_mock:
            result = lean_bridge._verify_known_witnesses(
                cert_path=cert_path,
                mumei_lean_repo=repo,
                timeout=600.0,
            )

        assert result is None
        run_mock.assert_not_called()

    def test_known_witness_fallback_preserves_primary_partial_cert(
        self, tmp_path: Path
    ) -> None:
        repo = tmp_path / "mumei-lean"
        (repo / "scripts").mkdir(parents=True)
        (repo / "scripts" / "bridge.py").write_text("# stub\n")
        (repo / "MumeiLean").mkdir()
        (repo / "MumeiLean" / "StdMathAbs.lean").write_text(
            "theorem abs_saturating_correct : True := by trivial\n",
            encoding="utf-8",
        )
        cert_path = tmp_path / "in.json"
        cert_path.write_text(
            json.dumps(
                {
                    "all_verified": False,
                    "atoms": [
                        {"name": "generated_ok", "z3_check_result": "unknown"},
                        {"name": "abs_saturating", "z3_check_result": "unknown"},
                    ],
                }
            )
        )
        lean_cert_out = tmp_path / "out.json"
        lean_cert_out.write_text(
            json.dumps(
                {
                    "all_verified": False,
                    "atoms": [
                        {
                            "name": "generated_ok",
                            "z3_check_result": "lean_verified",
                        },
                        {"name": "abs_saturating", "z3_check_result": "unknown"},
                    ],
                }
            )
        )

        with patch("agent.lean_bridge.subprocess.run") as run_mock, patch(
            "agent.lean_bridge.shutil.which", return_value="/usr/bin/lake"
        ):
            run_mock.side_effect = [
                MagicMock(
                    returncode=1,
                    stdout="",
                    stderr="error: unsolved goals\n⊢ 0 ≤ result",
                ),
                MagicMock(returncode=0, stdout="built StdMathAbs", stderr=""),
            ]
            result = lean_bridge.run_lean_bridge(
                cert_path=cert_path,
                lean_cert_out=lean_cert_out,
                mumei_lean_repo=repo,
            )

        assert result["success"] is True
        atoms = {a["name"]: a for a in result["lean_cert"]["atoms"]}
        assert atoms["generated_ok"]["z3_check_result"] == "lean_verified"
        assert atoms["abs_saturating"]["z3_check_result"] == "lean_verified"
        assert result["lean_cert"]["all_verified"] is True

    def test_timeout_returns_diagnostic(self, tmp_path: Path) -> None:
        repo = tmp_path / "mumei-lean"
        (repo / "scripts").mkdir(parents=True)
        (repo / "scripts" / "bridge.py").write_text("# stub\n")
        cert_path = tmp_path / "in.json"
        cert_path.write_text(json.dumps({"atoms": []}))

        with patch("agent.lean_bridge.subprocess.run") as run_mock:
            run_mock.side_effect = lean_bridge.subprocess.TimeoutExpired(
                cmd=["bridge.py"],
                timeout=1,
                output="partial stdout",
                stderr="partial stderr",
            )
            result = lean_bridge.run_lean_bridge(
                cert_path=cert_path,
                lean_cert_out=tmp_path / "out.json",
                mumei_lean_repo=repo,
                timeout=1,
            )

        assert result["success"] is False
        assert result["error_code"] == "timeout"
        assert "timed out" in result["stderr"]


# ---------------------------------------------------------------------------
# merge_lean_cert_into_proof_cert
# ---------------------------------------------------------------------------


class TestMergeLeanCert:
    def test_marks_proven_atom_as_lean_verified(self) -> None:
        original = {
            "atoms": [
                {"name": "alpha", "z3_check_result": "unknown", "status": "unknown"},
                {"name": "beta", "z3_check_result": "unsat", "status": "verified"},
            ],
            "all_verified": False,
        }
        lean = {
            "atoms": [
                {
                    "name": "alpha",
                    "z3_check_result": "lean_verified",
                    "status": "verified",
                }
            ],
            "lean_version": "4.7.0",
            "lean_cert_schema_version": "1.0-lean",
        }
        upgraded = lean_bridge.merge_lean_cert_into_proof_cert(original, lean)

        # Core invariant: alpha is now lean_verified, beta stays unsat,
        # original is not mutated, and the bundle-level metadata flips
        # to all_verified=True.
        alpha = next(a for a in upgraded["atoms"] if a["name"] == "alpha")
        beta = next(a for a in upgraded["atoms"] if a["name"] == "beta")
        assert alpha["z3_check_result"] == "lean_verified"
        assert alpha["status"] == "verified"
        assert beta["z3_check_result"] == "unsat"
        assert upgraded["all_verified"] is True
        assert upgraded["lean_version"] == "4.7.0"
        assert upgraded["lean_cert_schema_version"] == "1.0-lean"
        # Original untouched.
        original_alpha = next(a for a in original["atoms"] if a["name"] == "alpha")
        assert original_alpha["z3_check_result"] == "unknown"

    def test_unknown_remains_when_lean_did_not_prove_it(self) -> None:
        original = {
            "atoms": [
                {"name": "alpha", "z3_check_result": "unknown"},
                {"name": "beta", "z3_check_result": "unknown"},
            ]
        }
        lean = {
            "atoms": [
                {"name": "alpha", "z3_check_result": "unknown"},
                {"name": "beta", "z3_check_result": "lean_verified"},
            ]
        }
        upgraded = lean_bridge.merge_lean_cert_into_proof_cert(original, lean)
        alpha = next(a for a in upgraded["atoms"] if a["name"] == "alpha")
        beta = next(a for a in upgraded["atoms"] if a["name"] == "beta")
        assert alpha["z3_check_result"] == "unknown"
        assert beta["z3_check_result"] == "lean_verified"
        # Mixed state -> all_verified=False.
        assert upgraded["all_verified"] is False

    def test_empty_lean_cert_is_noop(self) -> None:
        original = {
            "atoms": [{"name": "a", "z3_check_result": "unknown"}]
        }
        upgraded = lean_bridge.merge_lean_cert_into_proof_cert(original, {})
        assert upgraded["atoms"][0]["z3_check_result"] == "unknown"

    def test_bundle_modules_are_upgraded_recursively(self) -> None:
        original = {
            "modules": {
                "std/foo.mm": {
                    "atoms": [
                        {"name": "nested", "z3_check_result": "unknown"}
                    ],
                    "all_verified": False,
                }
            }
        }
        lean = {"atoms": [{"name": "nested", "z3_check_result": "lean_verified"}]}

        upgraded = lean_bridge.merge_lean_cert_into_proof_cert(original, lean)

        module = upgraded["modules"]["std/foo.mm"]
        assert module["atoms"][0]["z3_check_result"] == "lean_verified"
        assert module["all_verified"] is True

    def test_escalation_bundle_candidates_are_upgraded(self) -> None:
        original = {
            "candidates": [
                {"name": "candidate", "z3_check_result": "unknown"},
            ],
        }
        lean = {
            "candidates": [
                {"name": "candidate", "z3_check_result": "lean_verified"},
            ],
        }

        upgraded = lean_bridge.merge_lean_cert_into_proof_cert(original, lean)

        assert upgraded["candidates"][0]["z3_check_result"] == "lean_verified"
        assert upgraded["candidates"][0]["status"] == "verified"


# ---------------------------------------------------------------------------
# lean_fallback_available helper
# ---------------------------------------------------------------------------


class TestLeanFallbackAvailable:
    def test_none_repo_returns_false(self) -> None:
        assert lean_bridge.lean_fallback_available(None) is False

    def test_missing_repo_returns_false(self, tmp_path: Path) -> None:
        assert (
            lean_bridge.lean_fallback_available(tmp_path / "missing")
            is False
        )

    def test_repo_without_bridge_returns_false(self, tmp_path: Path) -> None:
        repo = tmp_path / "mumei-lean"
        repo.mkdir()
        assert lean_bridge.lean_fallback_available(repo) is False

    def test_repo_with_bridge_returns_true(self, tmp_path: Path) -> None:
        repo = tmp_path / "mumei-lean"
        (repo / "scripts").mkdir(parents=True)
        (repo / "scripts" / "bridge.py").write_text("# stub\n")
        assert lean_bridge.lean_fallback_available(repo) is True
