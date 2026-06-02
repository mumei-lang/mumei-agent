"""Enhanced latent-space debugging feature tests."""
from __future__ import annotations

import numpy as np

from agent.latent_decoder import (
    ASSERTION_ADD_INDEX,
    LOOP_INVARIANT_INDEX,
    VARIABLE_REFACTOR_INDEX,
    LatentDecoder,
)
from agent.latent_encoder import LatentEncoder
from agent.strategies.latent_debug_strategy import LatentDebugStrategy


def test_encoder_extracts_effect_contract_dependency_and_scope_features() -> None:
    encoder = LatentEncoder()
    source = """
atom debit(account: i64, amount: i64)
    requires: amount > 0 && (account >= 0);
    ensures: result >= 0;
    effects: [Write balances, Settlement];
    body: { amount };

atom settle(account: i64, amount: i64)
    requires: forall(i, 0, amount, i >= 0);
    ensures: result >= amount;
    effects: [TemporalSettlement];
    body: {
        let old_balance = debit(account, amount);
        old_balance
    };
"""
    latent = encoder.encode_to_latent(
        source,
        {"violation_type": "effect_mismatch", "counterexample": {"amount": 1}},
    )

    assert len(latent) == 72
    assert encoder._extract_effect_features(source).tolist() == [
        0.0,
        1.0,
        0.0,
        0.0,
        2.0,
        1.0,
        3.0,
        3.0,
        0.0,
        0.0,
    ]
    assert encoder._extract_dependency_features(source).tolist() == [1.0, 1.0, 0.0, 0.0, 2.0]
    contract_features = encoder._extract_contract_complexity_features(source)
    assert contract_features[0] >= 1.0
    assert contract_features[3] == 1.0
    assert encoder._extract_scope_features(source).tolist()[:4] == [4.0, 1.0, 3.0, 2.0]
    assert encoder._extract_control_flow_graph_features(source).tolist() == [
        12.0,
        10.0,
        0.0,
        0.0,
        0.0,
        2.0,
    ]
    assert encoder._extract_data_flow_features(source).tolist() == [
        4.0,
        1.0,
        5.0,
        2.0,
        1.0,
        7.0,
    ]
    assert encoder._extract_cyclomatic_complexity(source).tolist() == [2.0, 1.0, 0.0]
    assert encoder._extract_abstract_interpretation_hints(source).tolist() == [
        4.0,
        0.0,
        0.0,
        0.0,
        1.0,
    ]


def test_decoder_applies_new_repair_strategies() -> None:
    decoder = LatentDecoder()
    source = (
        "atom transfer(flag: i64)\n"
        "    requires: true;\n"
        "    ensures: (result >= 0 && flag >= 0) && result <= 1;\n"
        "    effects: [Read balances, Write balances];\n"
        "    body: { let flag = true; 1 };\n"
    )

    weaken = np.zeros(13, dtype=np.float32)
    weaken[6] = 0.75
    weakened = decoder.decode_to_source(weaken, source)
    assert "(result >= 0 && flag >= 0)" in weakened
    assert "result <= 1" not in weakened

    add_effect = np.zeros(13, dtype=np.float32)
    add_effect[10] = 0.75
    assert "Write balances" in decoder.decode_to_source(add_effect, source)

    remove_effect = np.zeros(13, dtype=np.float32)
    remove_effect[11] = 0.75
    removed = decoder.decode_to_source(remove_effect, source)
    assert "Read balances" not in removed
    assert "Write balances" in removed

    refine = np.zeros(13, dtype=np.float32)
    refine[12] = 0.75
    assert "let flag: bool = true" in decoder.decode_to_source(refine, source)

    loop_source = (
        "atom bounded_sum(n: i64) -> i64\n"
        "    requires: n >= 0;\n"
        "    ensures: result >= 0;\n"
        "    body: {\n"
        "        let i = 0;\n"
        "        while i < n {\n"
        "            i = i + 1;\n"
        "        }\n"
        "        i\n"
        "    };\n"
    )
    invariant = np.zeros(16, dtype=np.float32)
    invariant[LOOP_INVARIANT_INDEX] = 0.75
    invariant_code = decoder.decode_to_source(
        invariant,
        loop_source,
        {"loop_invariant": "i >= 0"},
    )
    assert "invariant: i >= 0;" in invariant_code

    assertion = np.zeros(16, dtype=np.float32)
    assertion[ASSERTION_ADD_INDEX] = 0.75
    assertion_code = decoder.decode_to_source(
        assertion,
        loop_source,
        {"assertion": "n >= 0"},
    )
    assert "assert n >= 0;" in assertion_code

    rename = np.zeros(16, dtype=np.float32)
    rename[VARIABLE_REFACTOR_INDEX] = 0.75
    renamed_code = decoder.decode_to_source(
        rename,
        loop_source,
        {"rename_map": {"i": "idx"}},
    )
    assert "let idx = 0;" in renamed_code
    assert "while idx < n" in renamed_code

    param_renamed = decoder.decode_to_source(
        rename,
        loop_source,
        {"atom": "bounded_sum", "rename_map": {"n": "limit"}},
    )
    assert "atom bounded_sum(limit: i64) -> i64" in param_renamed
    assert "requires: limit >= 0;" in param_renamed
    assert "while i < limit" in param_renamed


def test_bug_direction_targets_enhanced_violation_types() -> None:
    strategy = LatentDebugStrategy()
    vector = np.zeros(30, dtype=np.float32)

    effect_direction = strategy._compute_bug_direction(
        vector,
        {"violation_type": "effect_mismatch"},
    )
    assert effect_direction[10] < 0

    temporal_direction = strategy._compute_bug_direction(
        vector,
        {"violation_type": "temporal_effect_violated"},
    )
    assert temporal_direction[11] < 0

    invariant_direction = strategy._compute_bug_direction(
        vector,
        {"failure_type": "invariant_violated"},
    )
    assert invariant_direction[LOOP_INVARIANT_INDEX] < 0
    assert invariant_direction[ASSERTION_ADD_INDEX] < 0
    assert invariant_direction[12] < 0

    rename_direction = strategy._compute_bug_direction(
        vector,
        {"violation_type": "variable_shadowing"},
    )
    assert rename_direction[VARIABLE_REFACTOR_INDEX] < 0


def test_latent_debug_produces_effect_candidate() -> None:
    strategy = LatentDebugStrategy()
    source = (
        "atom save(x: i64)\n"
        "    requires: true;\n"
        "    ensures: result == x;\n"
        "    body: { x };\n"
    )

    fixed = strategy.get_fix_with_latent_debug(
        source,
        {
            "violation_type": "effect_mismatch",
            "atom": "save",
            "effect_violation": {"required_effect": "FileWrite"},
        },
        LatentEncoder(),
        LatentDecoder(),
    )

    assert fixed is not None
    assert "effects: [FileWrite];" in fixed


def test_latent_debug_uses_adaptive_loop_invariant_context() -> None:
    strategy = LatentDebugStrategy()
    source = (
        "atom bounded_sum(n: i64) -> i64\n"
        "    requires: n >= 0;\n"
        "    ensures: result >= 0;\n"
        "    body: {\n"
        "        let i = 0;\n"
        "        while i < n {\n"
        "            i = i + 1;\n"
        "        }\n"
        "        i\n"
        "    };\n"
    )

    fixed = strategy.get_fix_with_latent_debug(
        source,
        {
            "violation_type": "loop_invariant_failed",
            "atom": "bounded_sum",
            "semantic_feedback": {"expected_invariant": "i >= 0"},
            "historical_patterns": [
                {
                    "violation_type": "loop_invariant_failed",
                    "edit": "loop_invariant",
                    "confidence": 0.91,
                    "success_rate": 0.46,
                },
            ],
        },
        LatentEncoder(),
        LatentDecoder(),
    )

    assert fixed is not None
    assert "invariant: i >= 0;" in fixed
