# mumei-agent Roadmap (2026-03 〜)

> mumei-agent の次期ロードマップ。mumei の思想（proof-first / AI生成コード → 検証済み資産への変換）に沿って優先度を設定。
>
> 全体のクロスプロジェクトロードマップは [mumei-lang/mumei の docs/CROSS_PROJECT_ROADMAP.md](https://github.com/mumei-lang/mumei/blob/develop/docs/CROSS_PROJECT_ROADMAP.md) を参照。

## 現状

- mumeiリポジトリから分離直後（[mumei-lang/mumei#90](https://github.com/mumei-lang/mumei/pull/90)）
- single/multi-stage strategy、retry history、generate mode、metricsが実装済み
- 対応する violation type: `division_by_zero`, `precondition_violated`, `postcondition_violated`, `invariant_violated`, `linearity_violated`, `effect_mismatch`, `effect_propagation`, `temporal_effect_violated`

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

### SI-1: Zero-Human Challenge — ✅ Complete

mumei-agent に難易度の高い課題（100% 安全なキュー、Verified JSON validator 等）を与え、人間が一切介入せずに検証をパスするまでのログを公開する。

**mumei-agent 側の作業**:
- ✅ `examples/challenges/` に課題 spec JSON を作成（safe_queue, verified_json_validator, deadlock_free_producer_consumer, bounded_queue, safe_arithmetic, payment, verified_clamp）
- ✅ `examples/challenges/benchmark.py` — ベンチマーク集計・Markdown レポート生成
- ✅ `examples/challenges/run_challenge.py` — チャレンジ実行パイプライン + パターン自動登録
- ✅ rule_based_fix: postcondition_violated, invariant_violated, linearity_violated 対応追加
- ✅ `agent/metrics.py` — `llm_tokens_used` フィールド追加
- ✅ `--dry-run` モードで全 7 spec のバリデーション完了 (7/7 OK)
- ✅ `examples/challenges/results/` に結果テンプレート・サンプル生成コードを配置
- ✅ `docs/ZERO_HUMAN_CHALLENGE.md` — チャレンジ分析ドキュメント作成
- ✅ `.github/workflows/challenge.yml` — `workflow_dispatch` でフル実行可能

**前提条件**: P6-A (Multi-atom 生成) ✅ 完了済み

### SI-3: Autonomous Delivery Flow — ✅ Complete (実地検証完了)

mumei-agent が mumei コードを書く → 検証 → Rust/Python ラッパーを自動生成 → PR を出す。

**mumei-agent 側の作業**:
- ✅ `--publish` モードの追加（生成 → 検証 → ラッパー生成 → git commit → PR）
- ✅ GitHub API 連携
- ✅ GitHub Actions CI テスト（`.github/workflows/verify-publish.yml`）
  - PR 内の `.mm` ファイルを自動検出
  - `mumei verify --json` で検証
  - `--emit c-header` / `rust-wrapper` / `python-wrapper` の生成・コンパイル確認
  - `rustc` によるRustラッパーコンパイルチェック
  - Python `ast.parse` による構文チェック
  - 結果を PR コメントとして投稿（`marocchino/sticky-pull-request-comment`）
- ✅ `examples/publish_demo/` — デモ spec + ドキュメント
- ✅ `tests/test_publish.py` — パイプライン全体のユニットテスト（dry-run, emit targets, verification failure, branch naming）

**実地検証（E2E テスト・CI 連携確認）**:
- ✅ `tests/test_publish_e2e.py` — E2E インテグレーションテスト
  - 既存 spec（`simple_add_spec.json`, `simple_e2e_spec.json`, `payment_spec.json`）を使った dry-run パイプラインテスト
  - mock mumei バイナリ（`tests/fixtures/mock_mumei.py`）を使った完全パイプラインテスト
  - 生成ファイル（`.mm`）の存在・内容検証
  - `@pytest.mark.integration` マーカー付与
- ✅ `tests/test_wrapper_validation.py` — FFI ラッパー静的検証テスト
  - C ヘッダー: `#ifndef` ガード、`stdint.h` インクルード、関数宣言、Doxygen `@pre`/`@post`
  - Rust ラッパー: `extern "C"` ブロック、安全ラッパー（`_checked`）、`Option<T>` 戻り値
  - Python ラッパー: `ctypes` インポート、`argtypes`/`restype` 定義、型ヒント、`ast.parse` 検証
  - クロスラッパー一貫性: 関数名・パラメータ数・マルチ atom 対応の整合性チェック
- ✅ `.github/workflows/verify-examples.yml` — publish dry-run テストジョブ追加
- ✅ `docs/AUTONOMOUS_DELIVERY.md` — パイプライン全体フロー図（mermaid）、使い方、環境変数、CI 連携、FFI glue code の説明

**前提条件**: SI-1, SI-2 (Verified FFI Boundary, mumei 側), Rust/Python Wrapper Emitter (mumei 側)

---

## P9: Autonomous Forge Mode — ✅ Infrastructure Complete / 🔧 Expansion In Progress

`forge` モードは、mumei-agent が自律的に std ライブラリを拡張・検証・コミットする新しい運用モード。既存の generate + self-healing + publish パイプラインを再利用し、「タスク発見」と「オーケストレーション」のレイヤーを追加する。

### P9-A: Forge Infrastructure ✅ Complete (PR #31)

- ✅ `forge_tasks/` — タスク spec JSON 配置ディレクトリ (`vstd_safe_add.json`, `vstd_safe_multiply.json`, `README.md`)
- ✅ `agent/forge_discovery.py` — `discover_tasks()` / `scan_std_todos()` / `filter_completed_tasks()`
- ✅ `agent/forge.py` — `MumeiForge` オーケストレーター（`append` / `create` / `replace` モード、`forge_log.json` ロギング、`fcntl.flock` による排他制御）
- ✅ `agent/prompts/forge/` — 鍛冶職人（Master Blacksmith）システムプロンプト + append mode プロンプト（`reference_patterns` で指定された既存 atom のコードを style context として注入）
- ✅ `python -m agent forge` CLI サブコマンド（`--tasks-dir` / `--mumei-repo` / `--max-tasks` / `--task` / `--dry-run` / `--auto-commit` / `--max-retries` / `--log-path`）
- ✅ `tests/test_forge_discovery.py`, `tests/test_forge.py`, `tests/test_forge_e2e.py`（最後は `@pytest.mark.integration`）
- ✅ `.github/workflows/forge.yml` — 手動 workflow_dispatch 実行用（schedule はコメントアウト）
- ✅ ファイル復元機構（post-write verify 失敗時のロールバック）
- ✅ `forge_log.json` によるタスク完了追跡

### P9-B: Z3 Logical Repair Protocol ✅ Integrated

- ✅ `FORGE_SYSTEM_PROMPT` に論理修復プロトコル（Counterexample Extraction → Unsat Core Analysis → Repair Strategy Selection → Code Transformation）を組み込み
- ✅ `build_append_prompt` のリトライセクションを Logical Repair Analysis 指示文に書き換え
- ✅ `_forge_append` の verify 失敗時に `report_formatter` の `format_actionable_fix_hint` / `format_counterexample` / `format_structured_unsat_core` を再利用し、LLM に構造化された修復ヒントを注入

### P9-C: Cross-file Context Loading ✅ Integrated

- ✅ タスク spec の `context_files` フィールドで関連モジュールを LLM コンテキストに注入（`MumeiForge._load_context_files` + `build_append_prompt(cross_file_context=...)`）
- ✅ 複数 std ファイルをまたいだスタイル / 契約パターンの参照基盤
- ✅ `create` / `replace` モードでも `_task_to_generate_spec` が spec に `cross_file_context` を付与

### P9-D: vStd Autonomous Expansion 🚧 In Progress

- ✅ `forge_tasks/vstd_safe_list.json` — `std/container/safe_list.mm` の `safe_push` / `safe_pop` / `safe_peek` / `safe_len` 鍛造ターゲット（`safe_queue.mm` パターン拡張）
- ✅ `forge_tasks/vstd_fixed_point.json` — `std/math/fixed_point.mm` 固定小数点演算モジュール（`fixed_from_int` / `fixed_to_int` / `fixed_add` / `fixed_mul`、`safe_mul.mm` を活用）
- ✅ `forge_tasks/vstd_string_utils.json` — `std/string_utils.mm` 文字列ユーティリティ（`safe_truncate` / `is_ascii`、propose-driven gap task）
- ✅ `forge_tasks/vstd_math_min_max.json` — `std/math/min_max.mm` min/max プリミティブ（`min2` / `max2` / `min3`、propose-driven gap task）
- ✅ `forge_tasks/vstd_iter.json` — `std/iter.mm` index-based iterator primitives（`analyze_std_gaps` の iter gap rule に対応）
- ✅ `forge_tasks/vstd_hash.json` — `std/hash.mm` Hashable primitives（`analyze_std_gaps` の hash gap rule に対応）
- ✅ `forge_tasks/vstd_math_gcd.json` — `std/math/gcd.mm` Euclidean-algorithm step atoms（Z3 整数理論で完全検証可能）
- ✅ `forge_tasks/vstd_math_clamp.json` — `std/math/clamp.mm` clamp primitives（`std/contracts.mm` の `clamp` を独立モジュール化）
- ✅ `forge_tasks/vstd_container_deque.json` — `std/container/deque.mm` 両端キュー（`safe_queue.mm` パターン拡張）
- ✅ `forge_tasks/vstd_math_sqrt.json` — `std/math/sqrt.mm` 整数平方根 `isqrt`（`n >= 0` → `result >= 0 && result * result <= n`）
- ✅ `forge_tasks/vstd_container_priority_queue.json` — `std/container/priority_queue.mm` 優先度キュー（`pq_push` / `pq_pop` / `pq_peek`）
- ✅ `forge_tasks/vstd_bitwise.json` — `std/bitwise.mm` ビット演算プリミティブ（and/or/xor/shift）
- ✅ `forge_tasks/vstd_math_log2.json` — `std/math/log2.mm` 整数 `ilog2`（`n > 0` → `result >= 0`）
- ✅ `forge_tasks/vstd_container_set.json` — `std/container/set.mm` 集合操作（`set_contains` / `set_add` / `set_size`）
- ✅ `tests/test_llm_benchmark.py` — LLM モデル別 forge 生成品質ベンチマーク基盤（`@pytest.mark.benchmark` で opt-in、`forge_tasks/vstd_math_abs.json` を基準タスクとする）
  - `LLM_BENCHMARK_MODELS` / `LLM_BENCHMARK_TRIALS` / `LLM_BENCHMARK_OUTPUT` 環境変数でモデル・試行回数・出力先を制御
  - `success_rate` / `avg_code_length` / `avg_time_seconds` を JSON に記録（`generate_code` は retries を返さないため、コード長を品質プロキシとして利用）
  - `.github/workflows/proliferate.yml` の `llm_model` 入力説明に推奨モデルと品質トレードオフを追記
- ✅ `.github/workflows/proliferate.yml` schedule 実行でも LLM benchmark を自動実行し、`docs/BENCHMARK_HISTORY.md` に `success_rate` / `avg_code_length` の時系列を最大50行で蓄積
- 📋 vStd ロードマップ残項目の forge タスク化

---

## SI-5: Self-Improving Standard Library (Phase 2) — ✅ Implemented

mumei 側の `analyze_std_gaps` MCP ツール（提案を吐き出す）と mumei-agent 側の forge パイプラインを直接接続し、`std/core.mm` の公理型を新規 std モジュール生成プロンプトに常時注入することで、std の自己拡張ループをクローズする。

### SI-5 Phase 2-A: Forge Task Auto-Proposal ✅ Implemented

- ✅ `agent/propose.py` — `analyze_std_gaps` の JSON 出力から forge task spec (`forge_tasks/vstd_*.json`) を自動生成
  - `depends_on` → `import "<path>" as <alias>;` プレアンブル自動構築
  - `difficulty` に応じて `max_retries` をスケール（low=3 / medium=5 / high=8）
  - 既存 `forge_discovery._load_task` と互換な spec フォーマット
- ✅ `python -m agent propose` CLI サブコマンド
  - `--gaps-json <path>` — ファイル入力モード
  - `--auto` — mumei MCP サーバーの `analyze_std_gaps` をインプロセス呼び出し
  - `--output-dir` / `--overwrite` / `--dry-run`
  - 各提案の概要（task_id / target / difficulty / depends_on / reason）を stdout に表示
- ✅ `tests/test_propose.py` — 全 fixture 駆動の互換性テスト（difficulty → retries 変換、import プレアンブル生成、`forge_discovery` ラウンドトリップ、CLI エントリポイント）
- ✅ `tests/fixtures/sample_gaps.json` — `analyze_std_gaps` の代表的な JSON 出力を fixture として固定化

### SI-5 Phase 2-B: Core Axiom Injection ✅ Implemented

- ✅ `agent/strategies/generate_strategy.py` — `std/` 配下モジュール生成時に `std/core.mm` の公理（型定義 + atom シグネチャ）をプロンプトへ常時注入
  - `_is_std_module(spec)` — `target_file` / `module_name` / `output_path` / `name` の先頭 `std/` を検出
  - `_summarise_core_axioms(source)` — `type ...;` と `atom ... requires/ensures;` のみを抽出（`body: {...};` はトークン節約のため除去）
  - `_load_core_axiom_context(path)` — `(path, mtime)` でキャッシュし、プロンプトブロック（マークダウン + コードブロック）を返却
  - 単一 atom (`generate_code`) と複数 atom (`generate_multi_atom`) 両方に接続
- ✅ `agent/config.py`
  - `AgentConfig.core_axiom_path` — `CORE_AXIOM_PATH` 環境変数、または隣接 `../mumei/std/core.mm` を自動検出
  - `AgentConfig.inject_core_axioms` — `INJECT_CORE_AXIOMS` 環境変数（default: `true`）
- ✅ `tests/test_core_axiom_injection.py` — std vs non-std の振る舞い、フラグ OFF 時の挙動、環境変数経路、単一/複数 atom の両経路でのプロンプト注入を検証

### SI-5 Phase 2-C: Self-Healing + Forge 統合ループ ✅ Implemented

- ✅ `agent/proliferate.py` — 自律増殖ループ: 欠落発見 → spec 生成 → コード鍛造 → 既存 std 影響検査 → 修復 → PR
  - `analyze_gaps(std_dir)` — `mcp_server.py` の `analyze_std_gaps` と同等のロジックをローカル実装（MCP 起動不要）
    - 依存グラフ、trusted atom、TODO/FIXME、提案リストを返す
    - 提案は difficulty + 未充足依存数でランキングし先頭 3 件に priority を付与
  - `generate_specs_from_gaps(gaps, max_count)` — `propose.build_spec_from_proposal` を再利用して forge 互換 spec を生成
  - `check_blast_radius(mumei_client, repo_dir, new_file_path, code)` — 新規 `.mm` を `std/` に仮配置 → 既存 `std/*.mm` を全検証 → 仮ファイルを自動除去（例外時も cleanup）
  - `attempt_heal(client, model, broken_info, mumei_client, max_retries=3)` — 既存 `fix_strategy.get_fix` を再利用し、壊れた既存ファイルを自動修復
  - `proliferate(mumei_repo_dir, max_proposals=3, dry_run=False)` — 全体オーケストレーター
    - 各提案を独立処理（1 件の失敗が他をブロックしない）
    - blast radius で壊れたファイルが生じた場合、rollback or heal を自動選択
    - ループの前後で `measure_health` を呼び出し、健全度の delta をログ出力
- ✅ `python -m agent proliferate` CLI サブコマンド
  - `--mumei-repo <path>` — mumei ローカルクローンへの絶対/相対パス
  - `--max-proposals N` — 一度に処理する提案数（default: 3）
  - `--mumei-bin <path>` — mumei バイナリのオーバーライド
  - `--dry-run` — git/PR 操作と生成ファイルの永続化をスキップ
  - `--enable-lean-fallback` — `MUMEI_LEAN_REPO` の mumei-lean bridge 経由で Z3 `unknown` atom の Lean 4 証明を追加試行
- ✅ `tests/test_proliferate.py` — 26 ケース
  - `analyze_gaps` の依存グラフ、trusted atom、TODO 検出、ランキング
  - `generate_specs_from_gaps` の `max_count` リスペクト + forge 互換性
  - `check_blast_radius` の broken_files 報告、例外時 cleanup
  - `attempt_heal` の already-verified ショートサーキット、固定点検出、fix 適用後成功
  - `proliferate` の dry_run end-to-end（`generate_code` / `MumeiClient` をモック）
  - Lean fallback CLI フラグ伝搬と `summary.json` 内 `lean_fallback` 監査フィールドの保持を検証

### SI-5 Phase 3-B: Scheduled Autonomous Runs ✅ Implemented

週次の GitHub Actions で「欠落発見 → spec 生成 → コード鍛造 → 検証 → PR」を人間の介入なしで回し続ける定常ループ。`mumei-lang/mumei` 側の `verify-std.yml` と組み合わせて、自動生成 PR のマージ前に std 全体を再検証する安全柵も追加。

- ✅ `.github/workflows/proliferate.yml` — SI-5 Autonomous Proliferation workflow
  - `cron: '0 0 * * 1'`（毎週月曜 00:00 UTC = JST 09:00）+ `workflow_dispatch` による手動トリガー
  - `workflow_dispatch` 入力: `max_proposals`（default: 3）、`dry_run`（default: true）
  - `schedule` 起動時 / `dry_run=true` では `--dry-run` を必ず付与し、初期は PR を作らずにパイプラインだけを検証
  - mumei-agent / mumei / mumei-lean を checkout → mumei コンパイラを `cargo build --release` → `PATH` に追加
  - Lean toolchain を best-effort で導入し、`MUMEI_LEAN_REPO=${{ github.workspace }}/mumei-lean` + `--enable-lean-fallback` で Z3 `unknown` atom の Lean 4 証明を CI 常時試行（Lean/lake 不在時は bridge 側で graceful degrade）
  - `python -m agent health` で pre/post-flight のヘルス JSON を取得
  - `python -m agent proliferate --mumei-repo ../mumei --output-json /tmp/proliferate/summary.json --enable-lean-fallback`
  - 生成物: `pre_health.json` / `post_health.json` / `proliferate.log` / `summary.json` を `proliferate-logs` artifact として保存
  - **ハイブリッド LLM プロファイル**（`workflow_dispatch` 入力 `llm_profile` / `llm_model` で切替。cron ではデフォルト `ollama-local` + `qwen3.5:0.8b` を使用し外部依存ゼロで動作）:
    - `ollama-local`（default）: runner 内で `ollama serve` を起動 → `ollama pull ${llm_model}` → `LLM_BASE_URL=http://localhost:11434/v1` に接続。`~/.ollama/models` を `actions/cache@v4` で `llm_model` 毎にキャッシュ。既定モデルは軽量な `qwen3.5:0.8b`、品質優先なら `qwen3.5:4b` / `qwen2.5-coder:7b`、予備枠として 1bit 量子化系（例: `bonsai-1bit-qwen`）を `llm_model` 入力で指定可能
    - `remote`: 任意の OpenAI 互換エンドポイント（DashScope / vLLM / tailscale 経由の自宅 Ollama / OpenAI）を secrets 経由で利用。優先順: `LLM_API_KEY` → legacy `OPENAI_API_KEY`。`LLM_BASE_URL` / `LLM_MODEL` は optional、後者は未設定なら `llm_model` 入力で上書き
  - 必要なシークレット（操作者が手動で設定）:
    - `MUMEI_REPO_TOKEN`（必須） — mumei-lang/mumei への cross-repo write / PR 作成権限を持つ PAT or GitHub App token
    - `LLM_API_KEY`（`llm_profile=remote` 時に必須） — OpenAI 互換エンドポイントの API key
    - `LLM_BASE_URL`（`remote` 時 optional） — 非 OpenAI エンドポイント URL
    - `LLM_MODEL`（`remote` 時 optional） — `llm_model` 入力より優先
    - `OPENAI_API_KEY`（optional） — `LLM_API_KEY` 未設定時の後方互換 fallback。`agent/config.py` の `LLM_API_KEY` → `OPENAI_API_KEY` fallback と整合
- ✅ `agent/proliferate.py` の CI 対応強化
  - `[PROLIFERATE] Step N/4: ...` 形式のステップログで CI 出力を人間が追跡しやすく
  - `_log_step()` / `_log_info()` ヘルパーで一貫したプレフィックス付きログを出力
  - `--output-json <path>` オプションで構造化サマリを書き出し（`timestamp` / `dry_run` / `pre_health` / `post_health` / `proposals_processed` / `proposals_succeeded` / `proposals_failed` / `details[]`）
  - `_jsonify_result()` で巨大な生成コード本体を `code_length` に圧縮して JSON artifact サイズを抑制
  - `_build_pr_body_extra()` で PR description を構築: 提案（target / reason / difficulty / depends_on / priority）+ 健全度 delta + 検証サマリ
  - `publish()` に `pr_title_prefix` / `pr_body_extra` を追加し、PR タイトルに `[SI-5 Autonomous Proliferation]` を付与
- ✅ `mumei-lang/mumei` `.github/workflows/verify-std.yml` — std/ 変更 PR に対する自動検証ゲート（cross-repo 安全柵）

### 検証手順
1. mumei-lang/mumei-agent の Settings → Secrets and variables → Actions で `MUMEI_REPO_TOKEN` を登録する（必須）。`remote` プロファイルを使いたい場合のみ `LLM_API_KEY`（+ 必要に応じて `LLM_BASE_URL` / `LLM_MODEL`）も登録する。`ollama-local` プロファイルでは追加 secret は不要。
2. 初回は Actions タブから "SI-5 Autonomous Proliferation" を `workflow_dispatch` + `llm_profile=ollama-local` + `dry_run=true` で起動し、`proliferate-logs` artifact の `summary.json` / `proliferate.log` を確認する（runner 内で ollama 起動 → qwen3.5:0.8b を pull する 1 回目は数分かかる、2 回目以降はキャッシュが効く）。
3. 問題がなければ `dry_run=false` に切り替えて実行し、生成される PR のタイトル・description・health delta を確認する。
4. 最後に週次 cron（月曜 00:00 UTC = JST 09:00）の自動起動を待つ。cron は常に `ollama-local` + `dry_run=true` で起動するため、`dry_run=false` で恒常運用したい場合は `cron` 行を `on.workflow_dispatch` だけに縮退させるか、`Run proliferate` step の `DRY_RUN_FLAG` 分岐を調整する。

### 恒常運用の推奨設定（PR 4）

- **モデル選択**: cron でのデフォルトは `qwen3.5:4b`（`LLM_MODEL_INPUT` のデフォルト値）。`qwen3.5:0.8b` は CI のスモークテスト用と割り切り、品質優先のラン（PR を本当に開くラン）では `4b` 以上を選ぶ。`qwen2.5-coder:7b` は精度が最も高いが ollama-local では runner キャッシュ容量を圧迫する点に注意。
- **max_proposals**: デフォルトの `3` を維持。1 ラン = 最大 3 PR を上限とすることで、レビューキューが詰まらないバランスをとる。スパイク的な大量提案が必要な場合のみ `workflow_dispatch` で個別に上書きする。
- **健全度ゲート**: `Compare pre/post health` ステップが post-flight `health_score` < pre-flight - 0.001 のときに `::warning` アノテーションを出すようになった。ジョブ自体は失敗させないが、運用ダッシュボードでこの警告を週次で集計し、3 週連続で警告が出る場合は `qwen3.5:4b` から `qwen2.5-coder:7b` への昇格、または `forge_tasks/` の難易度シフトを検討する。
- **summary.json の `health_delta`**: `agent.proliferate._write_output_json()` が pre/post の `health_score` 差分を `health_delta` として出力する。負値が出たランは PR を作っていても本質的には red とみなして再走させる運用が安全。

---

### SI-5 Phase 3-A: Proof Health Metrics ✅ Implemented

- ✅ `agent/std_health.py` — `std/` 全体の証明健全度を定量測定
  - `measure_health(mumei_client, std_dir)` — 各 `.mm` を `mumei verify` で検証 + atom/trusted/TODO を集計
    - 返却フィールド: `total_files` / `verified_files` / `failed_files` / `total_atoms` / `verified_atoms` / `trusted_atoms` / `health_score` / `todo_count` / `details[]`
  - `compute_health_score(total, verified, trusted, todo)` — 0.0〜1.0 クランプされたスコア
    - base = `(verified_atoms - trusted_atoms) / total_atoms`
    - TODO ペナルティは 1 件あたり 0.01、累積上限 0.2
    - trusted atom は「信仰による証明」として差し引く設計
  - `_format_table(report)` — 人間向けテーブルレンダラー
- ✅ `python -m agent health` CLI サブコマンド
  - `--mumei-repo <path>` — 対象 mumei リポジトリ
  - `--format json|table` — 出力形式（default: json）
  - 失敗ファイルが 1 つでもあれば exit code 2（CI ゲート用）
- ✅ `proliferate.py` からの統合 — ループ前後で `measure_health` を呼び出し、delta をログ表示
- ✅ `tests/test_std_health.py` — 13 ケース
  - `compute_health_score` のエッジケース（0 atoms / 全 trusted / TODO キャップ / クランプ）
  - `measure_health` の missing dir、empty、all-verified、trusted 混在、mixed pass/fail、TODO カウント、details 生成
  - CLI パーサーと table フォーマッター

### 関連 (mumei 側)
- [`mcp_server.py`](https://github.com/mumei-lang/mumei/blob/develop/mcp_server.py) の `analyze_std_gaps` — Phase 2-A 入力源 / Phase 2-C ローカル実装の参照元
- [`std/core.mm`](https://github.com/mumei-lang/mumei/blob/develop/std/core.mm) — Phase 2-B 注入源
- [`docs/CROSS_PROJECT_ROADMAP.md`](https://github.com/mumei-lang/mumei/blob/develop/docs/CROSS_PROJECT_ROADMAP.md) の SI-5 セクションと連携

### タスク spec フォーマット
`forge_tasks/README.md` を参照。主なフィールド:
- `task_id` — 完了重複排除の識別子
- `target_file` — mumei リポジトリ root 相対パス（例: `std/contracts.mm`）
- `mode` — `append` / `create` / `replace`
- `atoms` — 1 つ以上の atom spec（`reference_patterns` で既存 atom を style context として指定可能）
- `auto_commit` — 成功時に git commit を自動実行するか

### 関連 (mumei 側)
- [`docs/CROSS_PROJECT_ROADMAP.md`](https://github.com/mumei-lang/mumei/blob/develop/docs/CROSS_PROJECT_ROADMAP.md) の vStd セクション (vStd-1〜4, vStd-MCP) と連携

---

## 推奨実行順序

```
P1-C → P1-B → P1-A → P3-B → P6-A/B/C → SI-1 (Zero-Human Challenge) → SI-3 (Autonomous Delivery Flow) → P9 (Forge Mode)
                                  ✅ All Complete        ✅ Complete              ✅ Complete                🚧 In Progress
```

---

## P10: MCP Integration Strengthening ✅Implemented

mumei-agent と mumei MCP server の双方向 MCP 統合を強化。外部 MCP クライアント
（Claude Code / Devin / Codex 等）からも forge / heal / health / propose を直接
呼び出せるようになり、内部の検証パイプラインも opt-in で MCP server の richer
feedback（`semantic_feedback` / `machine_readable` / `counter_example` /
`effect_violation`）を消費できる。

- ✅`agent/mcp_server.py` — `FastMCP("Mumei-Agent")` を起動し以下のツールを公開
  - `forge_task(task_json, mumei_repo, dry_run=true)` — `MumeiForge.forge_one`
    の MCP ラッパ
  - `heal_file(source_code, error_report)` — `agent.strategies.fix_strategy.get_fix`
    によるセルフヒール
  - `measure_std_health(mumei_repo)` — `agent.std_health.measure_health` を委譲
  - `propose_forge_tasks(mumei_repo, max_proposals)` — `analyze_gaps` →
    `generate_specs_from_gaps` を MCP 経由で実行
  - `list_forge_log(log_path)` — `forge_log.json` の読み出し
  - `get_agent_status()` — LLM provider / mumei binary / 利用可能サブコマンド一覧
- ✅`agent/__main__.py` に `mcp-server` サブコマンドを登録
  （`python -m agent mcp-server`）
- ✅`pyproject.toml` / `requirements.txt` に `mcp[cli]>=1.0` を追加
- ✅`pyproject.toml` の `[project.scripts]` に `mumei-agent-mcp` エントリポイントを追加

- ✅`agent/mcp_client.py` — `MumeiMCPClient`（drop-in `MumeiClient` 互換）
  - `validate_logic` / `analyze_gaps` / `list_catalog` / `get_effects` /
    `visualize_graph` を mumei MCP server に委譲
  - 自動トランスポート選択: in-process（`PYTHONPATH` に mumei が乗っていれば直接
    `import mcp_server`）/ stdio subprocess（`MUMEI_MCP_COMMAND` 設定時）
  - `verify(source_path)` シムが `MumeiClient.verify` と同じシグネチャで
    `validate_logic` を呼び richer な `report` を返す
  - 失敗時は `MumeiClient` サブプロセス呼び出しに自動フォールバック
- ✅`USE_MCP_CLIENT` 環境変数 — `agent.mumei_client.create_mumei_client` ファクトリ経由で
  forge / heal / proliferate が `MumeiClient` か `MumeiMCPClient` かを切り替え

- ✅`agent/gap_rules.py` — `_STD_GAP_RULES` / `_scan_std_imports` /
  `_collect_trusted_atoms` / `_collect_todo_comments` / `_evaluate_rule` /
  `analyze_gaps_local` をオフライン用フォールバックとして分離
- ✅`agent/proliferate.py` — `_STD_GAP_RULES` 等を `agent.gap_rules` から再エクスポートし
  in-file 重複を排除
- ✅`PREFER_MCP_GAPS` 環境変数 — `true` のとき `proliferate.analyze_gaps` が mumei
  リポの `mcp_server.analyze_std_gaps` に委譲（`_load_gaps_from_mcp` 経由）。
  `SystemExit`（mumei 不在）の場合は静かにローカル分析にフォールバック
- ✅`.github/workflows/proliferate.yml` — `PREFER_MCP_GAPS=true` と
  `PYTHONPATH=${{ github.workspace }}/mumei` を設定し CI 上で常に mumei リポの
  ルールセットを使用

- ✅`tests/test_mcp_server.py` — 全 6 ツールを直接呼び出してアサーション
  （`MumeiForge` / `AgentConfig` / `measure_health` / `get_fix` をモック）
- ✅`tests/test_mcp_client.py` — `MumeiMCPClient` のモード判定 / fallback /
  `verify` シム / `create_mumei_client` ファクトリ
- ✅`tests/test_gap_rules.py` — `analyze_gaps_local` の純関数挙動 /
  `PREFER_MCP_GAPS` ON-OFF / fake `mcp_server` モジュールでのデリゲーション

### Cross-repo: mumei-side MCP tools (P10-D)

mumei-lang/mumei 側 `mcp_server.py` に以下を追加して external agents が
mumei-agent のインストールなしに proof health / proof certificate /
documentation を取得できるようにする:

- `measure_std_health()` — std/ 全体に対する health metric を JSON で返却
- `get_proof_certificate(module_path)` — `std/certs/` または proof bundle から
  proof certificate JSON を返却
- `generate_doc(source_code, format="json")` — `mumei doc --format json` を起動し
  構造化ドキュメントを返却

---

## Task 2-C: mumei-lean integration pipeline (opt-in)

mumei-agent の forge / verify サクル、`z3_check_result == "unknown"` の atom が残た合に[mumei-lang/mumei-lean](https://github.com/mumei-lang/mumei-lean)Lean 4 ロフバクド連携、人手の介在なし lean_verified 状態を昇格さるプライ。

### 概

- **オトイン導入** — 既存ローは byte-identical に動作し`--enable-lean-fallback` フグまた `MUMEI_LEAN_REPO` 環境変数を有効化したきの起。
- **subprocess ベの薄連携** — `agent.lean_bridge.run_lean_bridge()` `mumei-lean` リの `scripts/bridge.py` を `python -m scripts.bridge --cert ... --lean-cert-out ...`使形動。Lean toolchain (`lake`) が無ても`bridge.py` が`lake_missing` を伝搬 fallback は best-effort 失敗。
- **non-mutating merge** — `merge_lean_cert_into_proof_cert()` 元の proof certificate を deep-copy 上で`lean_verified` ル上書しない atom はそのま据え置く。bundle 体の `all_verified` `unsat` ま `lean_verified` の atom のみで構成さている合に True に。

### Pipeline 概観

1. `proliferate()` ロプ通常通生 → verify → publish を行
2. `--enable-lean-fallback` が有効 ループ後 `_run_lean_fallback()` を起。
3. 各 `spec_result.publish_result.proof_certificate` を走査 `unknown` atom を取出。
4. Tempfile に proof-cert を書出し`scripts/bridge.py --cert ... --lean-cert-out ...` を呼出。
5. 出力 `.lean-cert.json` を読込元の proof-cert と merge`spec_result["lean_fallback"]` `{"attempted": True, "unknown_count": N, "proved": K, "success": bool, "returncode": int}` を録。
6. 健康度算出れの工程続。

### 動作

```
export MUMEI_LEAN_REPO=/path/to/mumei-lang/mumei-lean
python -m agent proliferate \
    --mumei-repo /path/to/mumei-lang/mumei \
    --enable-lean-fallback \
    --output-json /tmp/proliferate-summary.json
```

`AgentConfig.mumei_lean_repo` プロパティ`MUMEI_LEAN_REPO` 環境変数か起かに値を取得しないば `None`。`None` の場 `lean_fallback_available()` `False` を返す`_run_lean_fallback()` no-op に。

### 関連ドキメ

- [mumei-lang/mumei-lean README](https://github.com/mumei-lang/mumei-lean/blob/main/README.md) — Lean 側の bridge / ingest_cert / export_cert の仕。
- `agent/lean_bridge.py` — agent 側のルパ層`tests/test_lean_bridge.py` テスを照。

---

## Related Documents

- [mumei-lang/mumei `docs/CROSS_PROJECT_ROADMAP.md`](https://github.com/mumei-lang/mumei/blob/develop/docs/CROSS_PROJECT_ROADMAP.md) — Cross-project roadmap (incl. Strategic Initiatives)
- [mumei-lang/mumei `docs/ROADMAP.md`](https://github.com/mumei-lang/mumei/blob/develop/docs/ROADMAP.md) — Compiler strategic roadmap
- [mumei-lang/mumei `docs/REPORT_SCHEMA.md`](https://github.com/mumei-lang/mumei/blob/develop/docs/REPORT_SCHEMA.md) — report.json schema (consumed by agent)
