"""Enhanced latent-space debugging feature tests."""
from __future__ import annotations

import numpy as np

from agent.latent_decoder import LatentDecoder
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

    assert len(latent) == 35
    assert encoder._extract_effect_features(source).tolist() == [
        0.0,
        1.0,
        0.0,
        0.0,
        2.0,
        1.0,
        3.0,
        3.0,
    ]
    assert encoder._extract_dependency_features(source).tolist() == [1.0, 1.0, 0.0]
    contract_features = encoder._extract_contract_complexity_features(source)
    assert contract_features[0] >= 1.0
    assert contract_features[3] == 1.0
    assert encoder._extract_scope_features(source).tolist() == [4.0, 1.0, 3.0, 2.0]


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
    assert invariant_direction[6] > 0
    assert invariant_direction[12] < 0


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
        {"violation_type": "effect_mismatch"},
        LatentEncoder(),
        LatentDecoder(),
    )

    assert fixed is not None
    assert "effects: [Write];" in fixed
