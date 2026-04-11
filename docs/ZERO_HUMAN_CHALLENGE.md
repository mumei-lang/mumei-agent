# SI-1: Zero-Human Challenge

> mumei-agent に難易度の高い課題を与え、人間が一切介入せずに検証をパスするまでのログを公開する。

## 目的と思想

Zero-Human Challenge は、mumei の根幹思想 **「AI 生成コード → 検証済み資産への変換」** の直接的な証明である。

従来の AI コード生成は「生成したコードが正しいかどうか」を人間がレビューする必要があった。mumei + mumei-agent の組み合わせは、この構造を根本的に変える:

1. **仕様記述** (spec JSON) — 人間が「何を作るか」を宣言的に定義
2. **AI 生成** (mumei-agent) — LLM が仕様から mumei コードを生成
3. **形式検証** (mumei verify) — Z3 SMT ソルバーが数学的に正しさを証明
4. **自己修復** (self-healing loop) — 検証失敗時に AI が自動修正し再検証

このチャレンジでは、ステップ 2〜4 を **完全に自律的に** 実行し、人間の介入なしに検証済みコードを生成できることを実証する。

---

## Overview

Each challenge provides a JSON specification defining one or more atoms with their `requires`/`ensures` contracts. The agent must generate Mumei code that satisfies all contracts, as proven by the Z3 SMT solver.

The pipeline for each challenge is:

```
spec JSON → generate_code() → self-healing loop → mumei verify → verified .mm output
```

## Challenges

### 1. Safe Queue (`safe_queue_spec.json`)

A multi-atom module implementing 100% safe queue operations with overflow/underflow prevention. References `std/container/bounded_array.mm` patterns (`bounded_push`/`bounded_pop`).

| Atom | Description | Key Contract |
|------|-------------|-------------|
| `enqueue` | Add element (overflow prevention) | `requires: len >= 0 && cap > 0 && len < cap` → `ensures: result == len + 1 && result <= cap` |
| `dequeue` | Remove element (underflow prevention) | `requires: len > 0` → `ensures: result == len - 1 && result >= 0` |
| `is_empty` | Check if queue is empty | `ensures: (len == 0 => result == 1) && (len > 0 => result == 0)` |
| `is_full` | Check if queue is at capacity | `ensures: (len == cap => result == 1) && (len < cap => result == 0)` |

**Difficulty**: Medium-High — 4 atoms with consistent bounds, conditional logic with implication contracts.

**検証項目**:
- Z3 が overflow 不可能性を証明: `enqueue` は `len < cap` を要求し `result <= cap` を保証
- Z3 が underflow 不可能性を証明: `dequeue` は `len > 0` を要求し `result >= 0` を保証
- Boolean 不変量: `is_empty`/`is_full` は常に 0 または 1 を返す
- 含意の正しさ: `len == 0 => is_empty == 1`, `len == cap => is_full == 1`

### 2. Verified JSON Validator (`verified_json_validator_spec.json`)

A single-atom challenge with capability security via the effect system. Uses `SafeFileRead(path)` effect to enforce file access restrictions.

| Atom | Description | Key Contract |
|------|-------------|-------------|
| `validate_json_file` | Validate a JSON file with path security | `effects: [SafeFileRead(path)]`, `requires: starts_with(path, "/tmp/") && not_contains(path, "..")` → `ensures: result >= 0 && result <= 1` |

**Difficulty**: High — combines effect system (`SafeFileRead`) with path traversal prevention. References `std/effects.mm`.

**AI 生成の難しさ**:
- `SafeFileRead` エフェクトの正しい宣言と使用が必要
- FFI 境界の理解（mumei と外部 JSON パーサーの間）
- capability 制約と機能的事後条件の同時満足
- エフェクトミスマッチが最も一般的な失敗モード

### 3. Deadlock-free Producer-Consumer (`deadlock_free_producer_consumer_spec.json`)

A multi-atom module implementing deadlock-free producer-consumer with resource hierarchy. Uses `resources: [buffer, mutex]` with priority ordering.

| Atom | Description | Key Contract |
|------|-------------|-------------|
| `produce` | Produce item into buffer | `requires: buf_len < buf_cap && mutex_held == 0` → `ensures: result == buf_len + 1` |
| `consume` | Consume item from buffer | `requires: buf_len > 0 && mutex_held == 0` → `ensures: result == buf_len - 1` |
| `buffer_available` | Check if space available | `ensures: (buf_len < buf_cap => result == 1) && (buf_len == buf_cap => result == 0)` |
| `buffer_has_items` | Check if buffer has items | `ensures: (buf_len > 0 => result == 1) && (buf_len == 0 => result == 0)` |

**Difficulty**: High — resource hierarchy for deadlock prevention, 4 atoms with mutex/buffer coordination.

**検証項目**:
- バッファ overflow 不可能性: `produce` は `buf_len < buf_cap` を要求
- バッファ underflow 不可能性: `consume` は `buf_len > 0` を要求
- Mutex 前提条件: `produce`/`consume` は `mutex_held == 0` を要求
- リソース順序: mutex → buffer の順序取得により循環待ちを防止（デッドロックフリー）

### 4. Bounded Queue (`bounded_queue_spec.json`)

A multi-atom module implementing safe queue operations with overflow/underflow prevention:

| Atom | Description | Key Contract |
|------|-------------|-------------|
| `enqueue` | Add element to queue | `requires: len < cap` → `ensures: result == len + 1` |
| `dequeue` | Remove element from queue | `requires: len > 0` → `ensures: result == len - 1` |
| `is_full` | Check if queue is at capacity | `ensures: result ∈ {0, 1}` |

**Difficulty**: Medium — requires consistent bounds across multiple atoms.

### 5. Safe Arithmetic (`safe_arithmetic_spec.json`)

A multi-atom module with overflow/underflow-safe arithmetic operations:

| Atom | Description | Key Contract |
|------|-------------|-------------|
| `safe_add` | Bounded addition | `requires: a + b <= 1000000` → `ensures: result == a + b` |
| `safe_sub` | Safe subtraction | `requires: a >= b` → `ensures: result == a - b` |
| `safe_mul` | Bounded multiplication | `requires: a <= 1000 && b <= 1000` → `ensures: result == a * b` |

**Difficulty**: Medium — straightforward arithmetic with explicit bounds.

### 6. Payment (`payment_spec.json`)

A multi-atom module for verified payment calculations:

| Atom | Description | Key Contract |
|------|-------------|-------------|
| `calc_subtotal` | Price * quantity | `ensures: result == price * quantity` |
| `calc_tax` | Tax calculation | `ensures: result == amount * tax_rate_pct / 100` |
| `calc_total` | Total with tax | `ensures: result >= 0` |

**Difficulty**: Medium — cross-atom composition with overflow prevention.

### 7. Verified Clamp (`verified_clamp_spec.json`)

A single-atom challenge with a rich postcondition:

| Atom | Description | Key Contract |
|------|-------------|-------------|
| `clamp` | Clamp value to [min, max] | `ensures: result ∈ [min_val, max_val] ∧ (value ∈ range → result == value)` |

**Difficulty**: Medium-High — requires conditional logic in the body that satisfies a compound postcondition including an implication.

## Running the Challenges

```bash
# Validate all specs (no LLM or mumei required)
python -m examples.challenges.run_challenge --all --dry-run

# Run a single challenge
python -m examples.challenges.run_challenge examples/challenges/safe_queue_spec.json

# Run all challenges
python -m examples.challenges.run_challenge --all

# Run with custom log directory
python -m examples.challenges.run_challenge --all --log-dir /tmp/challenge_results
```

Results are saved per challenge to `examples/challenges/results/<challenge_name>/`:
- `log.jsonl` — full step log (JSON Lines)
- `output.mm` — final generated Mumei code
- `metrics.json` — `Metrics.to_dict()` output
- `summary.md` — human-readable Markdown summary

> **Note**: 現在、結果テンプレートは代表的な 3 課題（`safe_queue`, `validate_json_file`, `deadlock_free_pc`）のみ配置済み。残り 4 課題のディレクトリは `workflow_dispatch` によるフル実行時に自動生成される。

## 結果サマリ

### Dry-run 検証結果

| 課題 | Spec バリデーション | タイプ | Atoms 数 | 難易度 |
|------|-------------------|--------|---------|--------|
| safe_queue | OK | Multi-atom | 4 (enqueue, dequeue, is_empty, is_full) | 中〜高 |
| verified_json_validator | OK | Single-atom + effects | 1 (validate_json_file) | 高 |
| deadlock_free_producer_consumer | OK | Multi-atom + resources | 4 (produce, consume, buffer_available, buffer_has_items) | 高 |
| bounded_queue | OK | Multi-atom | 3 (enqueue, dequeue, is_full) | 中 |
| safe_arithmetic | OK | Multi-atom | 3 (safe_add, safe_sub, safe_mul) | 低 |
| payment | OK | Multi-atom | 3 (calc_subtotal, calc_tax, calc_total) | 中 |
| verified_clamp | OK | Single-atom | 1 (clamp) | 中〜高 |

**全 7 spec のバリデーション: 7/7 OK**

### フル実行結果

> フル実行は `workflow_dispatch` で `challenge.yml` を実行した後にこのセクションが更新される。

| Challenge | Status | Attempts | Elapsed | Success Rate | Notes |
|-----------|--------|----------|---------|--------------|-------|
| safe_queue | PENDING | — | — | — | dry-run validated, awaiting execution |
| verified_json_validator | PENDING | — | — | — | dry-run validated, awaiting execution |
| deadlock_free_pc | PENDING | — | — | — | dry-run validated, awaiting execution |
| bounded_queue | PENDING | — | — | — | dry-run validated, awaiting execution |
| safe_arithmetic | PENDING | — | — | — | dry-run validated, awaiting execution |
| payment | PENDING | — | — | — | dry-run validated, awaiting execution |
| verified_clamp | PENDING | — | — | — | dry-run validated, awaiting execution |

## Methodology

1. **Spec Design**: Each challenge spec is designed to be verifiable by Z3, with realistic `requires`/`ensures` constraints. Challenges range from pure arithmetic to effect-system integration and resource hierarchy enforcement.
2. **Zero Human Intervention**: The agent runs `generate_code()` / `generate_multi_atom()` which:
   - Uses an LLM to generate initial `.mm` code from the spec
   - Runs `mumei check` for parse validation
   - Runs `mumei verify --json` for formal verification
   - On failure, enters the self-healing loop (up to 5 retries)
   - For multi-atom specs, identifies failing atoms and generates targeted fixes
3. **Logging**: Every generation attempt, verification result, and metric is recorded in JSON Lines format.
4. **Evaluation**: Success = all atoms in the module pass `mumei verify` (Z3 proves all contracts).

## 分析

### 期待される成功/失敗パターン

- **成功しやすい**: 純粋算術（safe_arithmetic, bounded_queue）— 事前・事後条件が単純な算術式
- **中程度**: キュー操作（safe_queue）— 含意条件付きの Boolean 返却が LLM にとって難しい場合がある
- **失敗しやすい**: エフェクト付き（verified_json_validator）— effect mismatch が最も一般的な失敗モード、FFI 境界の理解が必要
- **失敗しやすい**: リソース階層（deadlock_free_pc）— 非自明な事後条件（`result < buf_cap`）の導出

### Self-healing の有効性（期待値）

| 修正手段 | 適用条件 | 期待効果 |
|---------|---------|----------|
| Rule-based fix | `postcondition_violated`: 算術的なオフバイワンエラー | 高 — 正規表現ベースの修正が有効 |
| Rule-based fix | `invariant_violated`, `linearity_violated` | 中 — パターンが限定的 |
| Pattern Library | 過去に同じ violation_type で成功した修正パターン | 高 — 再利用可能なパターンが蓄積済み |
| LLM fix | 構造化フィードバック（unsat core + counterexample） | 中〜高 — 具体的なフィードバックが有効 |

### Expected Verification Items

| Challenge | Verification Items |
|-----------|-------------------|
| safe_queue | Overflow prevention, underflow prevention, boolean return bounds, implication contracts |
| verified_json_validator | Effect capability (`SafeFileRead`), path traversal prevention, boolean result |
| deadlock_free_pc | Resource hierarchy (priority ordering), buffer bounds, mutex state tracking |
| bounded_queue | Overflow/underflow prevention, boolean return bounds |
| safe_arithmetic | Integer overflow bounds, underflow prevention, non-negative results |
| payment | Cross-atom composition, overflow-safe multiplication, percentage calculation |
| verified_clamp | Compound postcondition with implication, range clamping |

## 結論

### mumei + mumei-agent の自律性の証明

Zero-Human Challenge は以下を実証する:

1. **仕様駆動の完全自律生成**: spec JSON さえあれば、人間の介入なしにコード生成・検証・修正が可能
2. **形式検証による品質保証**: Z3 が数学的に正しさを証明するため、生成コードの品質は「人間のレビュー」ではなく「数学的証明」で担保される
3. **自己修復能力**: 生成失敗時に rule-based fix → pattern library → LLM fix の多段階修正が自律的に動作する
4. **再現性**: `workflow_dispatch` で誰でも同じチャレンジを再実行可能
5. **スケーラビリティ**: 新しい課題 spec を追加するだけでチャレンジを拡張可能

### 今後の展望

- フル実行結果の公開（`workflow_dispatch` による challenge.yml 実行後）
- 課題の追加（より複雑な multi-file 生成、temporal effect を含む課題等）
- ベンチマーク結果の定期的な更新（新しい LLM モデル・エージェント戦略での再実行）
- 他の形式検証ツール（Dafny, F* 等）との比較ベンチマーク

## Benchmark

After running challenges, use the benchmark summary generator to aggregate results into a Markdown table:

```bash
# Generate summary from default results directory
python -m examples.challenges.benchmark

# Specify a custom results directory
python -m examples.challenges.benchmark --results-dir /path/to/results

# Write output to a file instead of stdout
python -m examples.challenges.benchmark --output benchmark_summary.md
```

The generator scans `examples/challenges/results/*/metrics.json` for completed challenge results and produces a summary table with:
- Challenge name
- Status (PASSED / FAILED)
- Total attempts
- Elapsed time
- Success rate

The output can be pasted directly into the [Results](#results) section above.

## 関連ドキュメント

- [mumei-lang/mumei `docs/ZERO_HUMAN_CHALLENGE.md`](https://github.com/mumei-lang/mumei/blob/develop/docs/ZERO_HUMAN_CHALLENGE.md) — コンパイラ側のチャレンジドキュメント
- [mumei-lang/mumei `docs/CROSS_PROJECT_ROADMAP.md`](https://github.com/mumei-lang/mumei/blob/develop/docs/CROSS_PROJECT_ROADMAP.md) — クロスプロジェクトロードマップ
- [mumei-agent `docs/ROADMAP.md`](ROADMAP.md) — エージェントロードマップ
- [`examples/challenges/`](../examples/challenges/) — チャレンジ spec + 結果ディレクトリ
- [`examples/run_e2e_demo.py`](../examples/run_e2e_demo.py) — E2E demo pipeline (reference implementation)
