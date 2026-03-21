# mumei-agent Roadmap (2026-03 〜)

> mumei-agent の次期ロードマップ。mumei の思想（proof-first / AI生成コード → 検証済み資産への変換）に沿って優先度を設定。
>
> 全体のクロスプロジェクトロードマップは [mumei-lang/mumei の docs/CROSS_PROJECT_ROADMAP.md](https://github.com/mumei-lang/mumei/blob/develop/docs/CROSS_PROJECT_ROADMAP.md) を参照。

## 現状

- mumeiリポジトリから分離直後（[mumei-lang/mumei#90](https://github.com/mumei-lang/mumei/pull/90)）
- single/multi-stage strategy、retry history、generate mode、metricsが実装済み
- 対応する violation type: `division_by_zero`, `linearity_violated`, `invariant_violated`, `postcondition_violated`, `temporal_effect_violated`

---

## P1-A: Generate Mode の強化 (最高優先度)

現在の `generate_code` は基本的なコード生成のみ。以下を追加:

- **仕様からの atom 生成**: 自然言語で `requires`/`ensures` を記述 → LLMが `atom` を生成 → `mumei verify --json` で検証 → 失敗時は self-healing ループへ
- **`mumei infer-contracts`/`mumei infer-effects` との統合**: 生成前にエフェクト推論を実行し、LLMプロンプトに注入
- **テンプレートベースの生成**: `atom` のスケルトン（requires/ensures/body）をLLMに埋めさせる形式で、hallucination を抑制

### 対象ファイル
- `agent/strategies/` — 新規 generate strategy
- `agent/prompts/` — generate 用プロンプトテンプレート
- `agent/self_healing.py` — generate → verify → fix ループの統合

---

## P1-B: structured_unsat_core の活用 (最高優先度)

mumei側で追加された `structured_unsat_core`（mumei PR #97）をagent側で消費する:

- `report.json` の `structured_unsat_core` フィールドをパースし、LLMプロンプトに「どの制約が矛盾しているか」を具体的に伝える
- 現在のプロンプトテンプレート群（`agent/prompts/`）を拡張し、unsat core 情報を活用

### 対象ファイル
- `agent/strategies/fix_strategy.py` — unsat core パース追加
- `agent/prompts/` — unsat core 情報を含むプロンプトテンプレート

---

## P1-C: E2E テスト・CI の整備 (高優先度)

- GitHub Actions で `pytest` を実行するCI（`.github/workflows/ci.yml` を新規作成）
- mumei バイナリのモック or 実バイナリを使ったインテグレーションテスト
- 各 violation type（precondition, effect_mismatch, temporal_effect 等）に対する修正成功率の回帰テスト

### 対象ファイル
- `.github/workflows/ci.yml` — 新規作成
- `tests/` — テストケース追加
- `requirements-dev.txt` or `pyproject.toml` — テスト依存追加

---

## P3-B: 「仕様 → 検証済みAPIクライアント」E2Eデモ (中優先度)

mumeiの思想の究極的な体現:

1. 自然言語で「GitHub API からユーザー情報を取得し、名前を返す」と指示
2. mumei-agent が `atom` を生成（`effects: [SecureHttpGet]`, `requires`/`ensures` 付き）
3. `mumei verify` で検証
4. 失敗時は self-healing ループで自動修正
5. 検証通過後、Rust/Go/TypeScript にトランスパイル

### 前提条件
- P1-A (Generate Mode 強化) 完了
- mumei 側の P2-A (Cross-atom composition) 完了

---

## 推奨実行順序

P1-C (CI整備) → P1-B (unsat core活用) → P1-A (Generate Mode強化) → P3-B (E2Eデモ)

---

## Related Documents

- [mumei-lang/mumei `docs/CROSS_PROJECT_ROADMAP.md`](https://github.com/mumei-lang/mumei/blob/develop/docs/CROSS_PROJECT_ROADMAP.md) — Cross-project roadmap
- [mumei-lang/mumei `docs/ROADMAP.md`](https://github.com/mumei-lang/mumei/blob/develop/docs/ROADMAP.md) — Compiler strategic roadmap
- [mumei-lang/mumei `docs/REPORT_SCHEMA.md`](https://github.com/mumei-lang/mumei/blob/develop/docs/REPORT_SCHEMA.md) — report.json schema (consumed by agent)
