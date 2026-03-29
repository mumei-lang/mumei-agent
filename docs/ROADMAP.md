# mumei-agent Roadmap (2026-03 〜)

> mumei-agent の次期ロードマップ。mumei の思想（proof-first / AI生成コード → 検証済み資産への変換）に沿って優先度を設定。
>
> 全体のクロスプロジェクトロードマップは [mumei-lang/mumei の docs/CROSS_PROJECT_ROADMAP.md](https://github.com/mumei-lang/mumei/blob/develop/docs/CROSS_PROJECT_ROADMAP.md) を参照。

## 現状

- mumeiリポジトリから分離直後（[mumei-lang/mumei#90](https://github.com/mumei-lang/mumei/pull/90)）
- single/multi-stage strategy、retry history、generate mode、metricsが実装済み
- 対応する violation type: `division_by_zero`, `linearity_violated`, `invariant_violated`, `postcondition_violated`, `temporal_effect_violated`

---

## P1-A: Generate Mode の強化 (最高優先度) ✅ Complete

- ✅ 仕様からの atom 生成: spec JSON → generate_code() → mumei verify → self-healing loop
- ✅ `mumei infer-contracts`/`mumei infer-effects` 統合済み
- ✅ テンプレートベースの生成: skeleton + fill-in-the-blanks 形式
- ✅ Common mistakes checklist injected into all generation prompts
- ✅ Pre-generation checklist extracted from spec constraints

---

## P1-B: structured_unsat_core の活用 (最高優先度) ✅ Complete

- ✅ `structured_unsat_core` parsed and formatted in `report_formatter.py`
- ✅ All prompt templates (`precondition`, `postcondition`, `invariant`, `division_by_zero`) include structured unsat core
- ✅ `format_actionable_fix_hint()` translates failures into concrete instructions
- ✅ `format_for_initial_generate()` extracts spec constraints as pre-warnings
- ✅ `_build_retry_prompt()` combines actionable hints + unsat core + data flow + error diff

---

## P1-C: E2E テスト・CI の整備 (高優先度) ✅ Complete

- ✅ GitHub Actions で `pytest` を実行するCI（`.github/workflows/ci.yml`）
- ✅ `pyproject.toml` に `[tool.pytest.ini_options]` と `integration` マーカー定義
- ✅ CI では `-m "not integration"` で integration テストを除外
- ✅ `format_error_diff` のユニットテスト追加（UNCHANGED / CHANGED / RESOLVED）
- ✅ カバレッジレポート出力（`--cov=agent`, XML artifact アップロード）
- ✅ mumei 実バイナリを使ったインテグレーションテスト (`tests/test_binary_integration.py`)
  - 各 violation fixture (`tests/fixtures/*.mm`) に対して `mumei verify --json` を実行し `violation_type` を検証
  - `valid.mm` の検証成功テスト
  - Self-healing ループ統合テスト（LLM は Mock、mumei バイナリは実物）
  - `mumei check` パーステスト
- ✅ mumei バイナリのモック or 実バイナリを使ったインテグレーションテスト (`tests/test_integration_e2e.py`)
  - `tests/fixtures/mock_mumei.py` — mumei CLI のモックスクリプト（`verify --json` / `check` 対応）
  - `tests/fixtures/reports/*.json` — 各 violation type のレポート JSON
  - 各 violation type に対する verify → fix → re-verify ループの E2E テスト
  - `@pytest.mark.integration` マーカーで CI から除外可能
- ✅ 各 violation type に対する修正成功率の回帰テスト (`tests/test_regression.py`)
  - `Metrics.success_rate()` / `Metrics.overall_success_rate` メソッド追加
  - `TestRegressionSuccessRate`: 各 violation type で N=5 回の fix pipeline 実行、成功率 ≥ 80% を検証
  - `TestMetricsSuccessRate`: success_rate / overall_success_rate のユニットテスト

### 対象ファイル
- `.github/workflows/ci.yml` — CI ワークフロー
- `tests/test_prompts.py` — `format_error_diff` テスト追加
- `tests/test_binary_integration.py` — mumei バイナリ統合テスト
- `tests/test_integration_e2e.py` — モック mumei バイナリ E2E 統合テスト
- `tests/conftest.py` — `real_mumei_client` / `fixtures_dir` / `mumei_mock_bin` / `mumei_mock_e2e_client` fixture 追加
- `tests/fixtures/mock_mumei.py` — mumei CLI モックスクリプト
- `tests/fixtures/reports/*.json` — 各 violation type のレポート JSON
- `tests/fixtures/*.mm` — 各 violation type のサンプルファイル
- `agent/metrics.py` — `success_rate()` / `overall_success_rate` メソッド追加
- `pyproject.toml` — pytest 設定・テスト依存

---

## P3-B: 「仕様 → 検証済みAPIクライアント」E2Eデモ (中優先度) ✅ Complete

mumeiの思想の究極的な体現:

1. 自然言語で「GitHub API からユーザー情報を取得し、名前を返す」と指示
2. mumei-agent が `atom` を生成（`effects: [SecureHttpGet]`, `requires`/`ensures` 付き）
3. `mumei verify` で検証
4. 失敗時は self-healing ループで自動修正
5. 検証通過後、Rust/Go/TypeScript にトランスパイル

### 前提条件
- ✅ P1-A (Generate Mode 強化) 完了
- ✅ mumei 側の P2-A (Cross-atom composition) 完了

### 実装済み
- ✅ `examples/e2e_demo_spec.json` — デモ仕様ファイル (fetch_github_user, `inputs`/`requires`/`ensures`/`return_type` 対応)
- ✅ `examples/simple_add_spec.json` — 最小デモ仕様ファイル (mumei バイナリなしでもテスト可能)
- ✅ `examples/simple_e2e_spec.json` — 純粋算術 `safe_div` デモ (エフェクトなし、LLM 不要でフロー確認可能)
- ✅ `examples/run_e2e_demo.py` — デモ実行スクリプト (spec → generate → verify → build → summary, `--dry-run` 対応)
- ✅ `tests/test_e2e_demo.py` — E2E デモのバリデーション・モックテスト (`simple_e2e_spec.json` テスト含む)
- ✅ Contextual suggestion の活用強化 (`format_actionable_fix_hint()` / `_build_retry_prompt()`)

---

## P3-C: CI Verification Gate (中優先度) ✅ Phase 1 Complete

PR 上の `.mm` ファイルを自動検証し、結果をコメントとして投稿するパイプライン。

### Phase 1 — 実装済み
- ✅ `scripts/ci_verify.py` — `.mm` ファイルの自動発見・検証・Markdown レポート生成
- ✅ `.github/workflows/mumei-verify.yml` — 再利用可能な検証ワークフロー (`workflow_call`)
- ✅ `.github/workflows/verify-examples.yml` — `examples/*.mm` の自動検証
- ✅ `tests/test_ci_verify.py` — ファイル発見・Markdown フォーマットのユニットテスト
- ✅ Proof certificate 生成・アーティファクトアップロード対応
- ✅ PR コメントへの検証結果自動投稿 (`marocchino/sticky-pull-request-comment`)

### 対象ファイル
- `scripts/ci_verify.py` — CI 検証ゲートスクリプト
- `.github/workflows/mumei-verify.yml` — 再利用可能ワークフロー
- `.github/workflows/verify-examples.yml` — examples 検証ワークフロー
- `tests/test_ci_verify.py` — ユニットテスト

---

## P6-A: Multi-atom / Multi-file 生成 ✅ Complete

- ✅ Multi-atom spec JSON フォーマット (`atoms: [...]` 配列)
- ✅ `generate_multi_atom()`: 依存関係検出・ソート・一括生成・atom 単位 retry
- ✅ 既存 single-atom spec との後方互換性維持

## P6-B: Pattern Library の学習型拡張 ✅ Complete

- ✅ `FixPattern` に `applied_count` / `success_count` フィールド追加
- ✅ `try_pattern_fix()`: 成功率ベースのパターン自動適用（LLM バイパス）
- ✅ `lookup()` の成功率ランキング
- ✅ `Metrics` に `pattern_attempts` / `pattern_successes` 追加

## P6-C: Specification Refinement Loop ✅ Complete

- ✅ `spec_refinement.py`: 検証失敗時に仕様（requires/ensures）自体の修正を提案
- ✅ `RetryHistory.is_same_error_repeating()` トリガーで仕様洗練モードに切り替え
- ✅ `mumei infer-contracts` 結果を活用した仕様推論

---

## Strategic Initiatives（次期戦略）

mumei エコシステム全体の戦略的イニシアチブ。詳細は [mumei-lang/mumei の docs/CROSS_PROJECT_ROADMAP.md](https://github.com/mumei-lang/mumei/blob/develop/docs/CROSS_PROJECT_ROADMAP.md) を参照。

### SI-1: Zero-Human Challenge — 🔧 In Progress

mumei-agent に難易度の高い課題（100% 安全なキュー、Verified JSON validator 等）を与え、人間が一切介入せずに検証をパスするまでのログを公開する。

**mumei-agent 側の作業**:
- `examples/challenges/` に課題 spec JSON を作成
- generate mode で実行し、全ログを記録
- 成功/失敗の分析ドキュメントを作成

**前提条件**: P6-A (Multi-atom 生成) ✅ 完了済み

### SI-3: Autonomous Delivery Flow — 🔧 In Progress

mumei-agent が mumei コードを書く → 検証 → Rust/Python ラッパーを自動生成 → PR を出す。

**mumei-agent 側の作業**:
- `--publish` モードの追加（生成 → 検証 → ラッパー生成 → git commit → PR）
- GitHub API 連携

**前提条件**: SI-1, SI-2 (Verified FFI Boundary, mumei 側), Rust/Python Wrapper Emitter (mumei 側)

---

## 推奨実行順序

```
P1-C → P1-B → P1-A → P3-B → P6-A/B/C → SI-1 (Zero-Human Challenge) → SI-3 (Autonomous Delivery Flow)
                                  ✅ All Complete          📋 Next              📋 After SI-1/SI-2
```

---

## Related Documents

- [mumei-lang/mumei `docs/CROSS_PROJECT_ROADMAP.md`](https://github.com/mumei-lang/mumei/blob/develop/docs/CROSS_PROJECT_ROADMAP.md) — Cross-project roadmap (incl. Strategic Initiatives)
- [mumei-lang/mumei `docs/ROADMAP.md`](https://github.com/mumei-lang/mumei/blob/develop/docs/ROADMAP.md) — Compiler strategic roadmap
- [mumei-lang/mumei `docs/REPORT_SCHEMA.md`](https://github.com/mumei-lang/mumei/blob/develop/docs/REPORT_SCHEMA.md) — report.json schema (consumed by agent)
