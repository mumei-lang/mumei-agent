# V1-A〜V1-E 達成状況ギャップレポート

> 調査日: 2026-06-29
> canonical 基準: `mumei-lang/mumei/docs/CROSS_PROJECT_ROADMAP.md` (V1-A〜V1-E セクション)
> 自己申告: `mumei-lang/mumei-agent/docs/ROADMAP.md` P14-A〜P14-D (✅ Implemented)

---

## 調査方法

canonical roadmap の V1-A〜V1-E 達成基準を箇条書きで抽出し、mumei-agent の実コード（CLI argparse choices、コアロジック関数、MCP tool 定義、テスト assertion）を直接確認して「完了 / 部分実装 / 未完」を判定した。判定の根拠はファイルパス・行番号・テスト名を明記する。

---

## V1-A: 自然言語仕様の健全性検証

### canonical 達成基準

- V1-A-1: 仕様充足可能性チェック（矛盾検出、暗黙前提条件の欠落警告、Z3 充足可能性事前チェック）
- V1-A-2: 仕様完全性チェック（ドメインヒントに基づく必須条件欠落検出）
- V1-A-3: 人向けフィードバックレポート（日本語/英語、重要度表示、CLI `validate-spec`、MCP `check_spec_contradiction`）
- 対応言語は仕様テキスト入力のため言語非依存
- `contradiction_type` を CLI / MCP / Markdown report で統一的に返す
- 7 固定キーのうち `spec_health_issues` と `next_steps` が出力される

### P14-A 自己申告の成功指標

- `.mm` 生成前に直接矛盾を検出できる
- CLI / MCP / Markdown report が同じ `contradiction_type` を返す
- LLM 生成失敗ではなく仕様側の問題として human review に回せる

### 実コード裏取り結果: **✅ 完了**

| 基準 | 根拠 |
|------|------|
| `validate-spec` CLI | `agent/__main__.py:15` に `"validate-spec"` が `_SUBCOMMANDS` に存在 |
| `extract-spec --check-contradiction-only` | `agent/extract_spec.py` に `--check-contradiction-only` flag 実装済み |
| `contradiction_type` フィールド | `agent/cross_validation.py:17` `NLSpecValidationResult.contradiction_type` |
| MCP `check_spec_contradiction` | `agent/mcp_server.py` に `check_spec_contradiction` tool 定義済み |
| `spec_health_issues` + `next_steps` 出力 | `tests/test_cross_validation.py` で assertion 済み |
| 人向けレポート（日/英） | `agent/report_formatter.py:109` が `### next_steps (V1-E-1)` を Findings より前に配置、`_resolve_lang()` で日/英自動判定 |
| ドメインヒント | `agent/cross_validation.py` の `domain_hint` 引数、`tests/test_cross_validation.py` でテスト |

**ギャップ: なし**

---

## V1-B: 既存他言語コードの検証・フィードバック

### canonical 達成基準

- V1-B-1: コード→仕様→Z3 検証パイプライン（`code_to_spec` → mumei verify → 行番号マッピング）
- V1-B-2: 言語別検証ヒューリスティクス（Python / Rust / TypeScript / Go の4言語）
- V1-B-3: 差分フィードバック（CLI `audit --code-file`, MCP `scan_and_fix`）
- Rust overflow/bounds、TypeScript null/undefined、Go bounds/nil/overflow の決定的 fixture
- 7 固定キーのうち `spec_health_issues`, `verification_violations`, `cross_validation_gaps`, `next_steps` が出力される
- `audit -> migrate-suggest -> heal` gate order

### P14-B 自己申告の成功指標

- `audit --code-file src/` が複数ファイルを処理し、成功/失敗件数を集約する
- Rust / TypeScript / Go 入力でも `AUDIT_SCHEMA_KEYS` が alias なしで揃う
- 回帰テストは Rust overflow、TypeScript null/undefined、Go bounds を deterministic/no-LLM fixture で固定

### 実コード裏取り結果: **✅ 完了**

| 基準 | 根拠 |
|------|------|
| `audit --code-file` CLI | `agent/__main__.py:13` (`"audit"`), `agent/audit.py:515-518` argparse |
| 4言語対応 | `agent/audit.py:26` `SUPPORTED_AUDIT_LANGUAGES = ("python", "rust", "typescript", "go")` |
| MCP `scan_and_fix` | `agent/mcp_server.py:1969` に定義、`language` 引数で4言語受付 |
| ディレクトリスキャン | `agent/audit.py` `audit_directory()` メソッド、`tests/test_audit.py` でテスト |
| `--auto-migrate` / `--auto-heal` | `agent/audit.py` argparse に実装 |
| Rust/TS/Go deterministic fixture | `tests/test_audit.py` に Rust overflow / TS null / Go bounds テスト、`mumei-demo/scenarios/no_mm_audit/` に `buggy_add.rs` / `buggy_name_length.ts` / `buggy_nth.go` fixture 配置 |
| 7固定キー alias 禁止テスト | `tests/test_audit.py:574` `test_scan_and_fix_shares_audit_contract_and_next_steps_review_gate` |
| `cross_validation.py` 4言語対応 | `agent/cross_validation.py:36` `SUPPORTED_FOREIGN_CODE_LANGUAGES = {"python", "rust", "typescript", "go"}` |
| TS infer contracts | `agent/cross_validation.py:2702` `_infer_typescript_contracts()` 実装済み |

**ギャップ: なし**

---

## V1-C: 仕様→コード整合性検証 (spec→code conformance)

### canonical 達成基準

- V1-C-1: 仕様→コード網羅性チェック（requires/ensures がコードに実装されているか）
- V1-C-2: 未実装条件の特定とフィードバック（unimplemented_conditions / hidden_specifications）
- V1-C-3: トレーサビリティマトリクス生成（CLI `verify-conformance --spec ... --code ... --language rust`）
- **対応言語: Python / Rust / TypeScript / Go**（canonical roadmap は V1-B と同じ4言語を要求）
- MCP: `verify_spec_code_conformance` (実際は `verify_conformance`)
- 出力: `missing_constraints[]`, `divergences[]`, `cross_validation_gaps`, `next_steps`

### P14-C 自己申告の成功指標

- `missing_constraints[]`, `divergences[]`, `drift_issues[]` が structured JSON で返る
- V1-D-3 は `conformance`, `drift`, `cross_validation_gaps`, `drift_score`, `next_steps` だけを使う
- 複数 `.mm` の cross-spec result を MCP client が直接取得できる

### 実コード裏取り結果: **⚠️ 部分実装**

| 基準 | 状態 | 根拠 |
|------|------|------|
| `verify-conformance` CLI | ✅ | `agent/__main__.py:19`, `agent/verify_conformance.py` |
| `conformance_verifier.py` コアロジック | ✅ | `agent/conformance_verifier.py` — `verify_conformance()`, `ConformanceVerificationResult` |
| MCP `verify_conformance` | ✅ | `agent/mcp_server.py:1786` |
| `unimplemented_conditions` / `hidden_specifications` | ✅ | `agent/conformance_verifier.py:47-48` |
| `traceability_matrix` | ✅ | `agent/conformance_verifier.py:52` |
| `cross_validation_gaps` | ✅ | `agent/conformance_verifier.py:53` |
| `next_steps` first 順序テスト | ✅ | `tests/test_cross_validation.py:700` `test_verify_conformance_human_report_keeps_next_steps_first_and_review_keys` |
| `--format human\|json\|markdown` | ✅ | `agent/verify_conformance.py:23-28` |
| **CLI `--language` 4言語** | **❌** | `agent/verify_conformance.py:21` `choices=["python", "rust", "go"]` — **TypeScript が欠落** |
| **`_source_line_map` TypeScript** | **❌** | `agent/conformance_verifier.py:341-347` — Python/Rust/Go のみ実装、TypeScript は `{}` を返す（line 348 の暗黙 fallback） |

### ギャップ詳細

1. **CLI `--language` choices にTypeScript がない** (`agent/verify_conformance.py:21`)
   - canonical roadmap は V1-B と同じ4言語カバレッジを要求
   - `audit --code-file` (V1-B) は `["python", "rust", "typescript", "go"]` で正しく4言語
   - `validate-spec-to-code` / `validate-code-to-spec` (cross_validation.py) も `["python", "rust", "typescript", "go"]` で正しい
   - しかし `verify-conformance` CLI のみ3言語に制限されている

2. **`conformance_verifier.py` の `_source_line_map()` に TypeScript パスがない** (line 341-347)
   - Python: `_python_source_line_map()`
   - Rust: regex `(?:pub\s+)?fn\s+(...)`
   - Go: regex `func\s+(...)`
   - TypeScript: 未実装 → 空の `{}` を返す
   - これにより、TypeScript コードに対する conformance 検証の traceability_matrix が関数行番号なしになる

3. **MCP `verify_conformance` ツールの `language` パラメータ**: 型は `str | None` で runtime 制限なし。TypeScript を渡すこと自体は可能だが、CLI からは入力不可。

### 推奨対応

- **オプション A（コード修正）**: `verify_conformance.py:21` の choices に `"typescript"` を追加し、`conformance_verifier.py` の `_source_line_map()` に TypeScript 用 regex（例: `(?:export\s+)?(?:async\s+)?function\s+(...)` / arrow function 等）を追加する。
- **オプション B（docs 修正のみ）**: ROADMAP.md の P14-C 成功指標に「V1-C の対応言語は Python/Rust/Go（TypeScript は V1-B audit 経由で間接カバー、conformance 単体は未対応）」と実態を反映する注記を追加。
- **推奨**: オプション A が canonical roadmap の意図に合致する。修正は小規模（argparse choices 追加 + regex 1行）。

---

## V1-D: コード→仕様整合性検証 (code→spec conformance)

### canonical 達成基準

- V1-D-1: コード→抽出仕様 vs 元仕様の差分検出
- V1-D-2: 仕様ドリフトレポート（drift_score 0.0〜1.0）
- V1-D-3: 双方向整合性サマリ（`verify-traceability --code ... --spec ...`）
- **対応言語: Python / Rust / TypeScript / Go**
- MCP: `verify_code_spec_traceability`
- 出力: `conformance`, `drift`, `cross_validation_gaps`, `drift_score`, `next_steps`

### 実コード裏取り結果: **⚠️ 部分実装**

| 基準 | 状態 | 根拠 |
|------|------|------|
| `verify-traceability` CLI | ✅ | `agent/__main__.py:21`, `agent/verify_traceability.py` |
| `traceability_verifier.py` コアロジック | ✅ | V1-C `verify_conformance` + V1-D `validate_code_to_spec` を結合 |
| MCP `verify_code_spec_traceability` | ✅ | `agent/mcp_server.py:1829` |
| `drift_score` 出力 | ✅ | `agent/traceability_verifier.py:156` `_drift_score()` |
| `cross_validation_gaps` 統合 | ✅ | `agent/traceability_verifier.py:141` `_combined_gaps()` |
| `next_steps` first 順序テスト | ✅ | `tests/test_traceability.py:49` `test_verify_traceability_report_keeps_next_steps_before_findings` |
| `next_steps` JSON key first テスト | ✅ | `tests/test_traceability.py:74` `test_verify_traceability_cli_json_keeps_next_steps_first` |
| **CLI `--language` 4言語** | **❌** | `agent/verify_traceability.py:18` `choices=["python", "rust", "go"]` — **TypeScript が欠落** |

### ギャップ詳細

`verify-traceability` CLI の `--language` choices が V1-C と同様に `["python", "rust", "go"]` の3言語のみ。TypeScript が欠落。

`traceability_verifier.py` のコアロジック自体は `verify_conformance()` を呼ぶため、conformance 側の TypeScript gap がそのまま伝搬する。

### 推奨対応

V1-C と同時に修正する。`verify_traceability.py:18` の choices に `"typescript"` を追加するだけで完了（コアロジックは `cross_validation.py` 経由で TypeScript 対応済み。conformance 側の `_source_line_map` 追加と合わせれば完全対応）。

---

## V1-E: 人向け UX 強化 (Human-Friendly UX)

### canonical 達成基準

- V1-E-1: `--format human|json|markdown` 選択、重要度表示、日/英切替、コピペ可能な修正提案
- V1-E-2: インタラクティブ検証モード（mumei repl `:verify-spec` / `:verify-code`）
- V1-E-3: エディタ統合（LSP 拡張）
- V1-E-4: mumei-demo `spec_code_verification_suite` への統合
- **すべての V1-E surface で `next_steps` が findings より前に出る**
- `next_steps`-first の human/markdown レポート

### P14-D 自己申告の成功指標

- `scan_and_fix` だけで同じ workflow を実行できる
- 問題なし / 自動修復可能 / human review の分岐が README と guide で一致する
- `V1-E` user-facing output で `next_steps` before findings

### 実コード裏取り結果: **✅ 完了**

| 基準 | 根拠 |
|------|------|
| `--format human\|json\|markdown` | `verify_conformance.py:23-28`, `verify_traceability.py:20-25`, `agent/__main__.py` audit の `--json` flag |
| 日/英自動切替 | `agent/report_formatter.py:150-153` `_resolve_lang()` → `_contains_japanese()` |
| `next_steps` before findings (report) | `agent/report_formatter.py:109-116`: `### next_steps (V1-E-1)` → `### Findings` の固定順序 |
| `next_steps` first テスト (traceability) | `tests/test_traceability.py:49,74` |
| `next_steps` first テスト (conformance) | `tests/test_cross_validation.py:700` |
| `next_steps` first テスト (scan_and_fix) | `tests/test_report_formatter.py:144` `report.index("### next_steps (V1-E-1)") < report.index("### Human review entrypoints")` |
| V1-E-4 mumei-demo | `mumei-demo/scenarios/spec_code_verification_suite/scenario.json` に mode_a〜mode_d 実装 |
| V1-E-2 REPL 拡張 | `mumei/src/main.rs` の repl `:verify-spec` / `:verify-code` (canonical roadmap line 1598-1602 に「実装済み」記載) |
| V1-E-3 LSP 拡張 | `mumei/src/lsp.rs` の mumei-agent diagnostics (canonical roadmap line 1604-1609 に「実装済み」記載) |
| MCP `scan_and_fix` `output_format` | `agent/mcp_server.py:1996` `output_format: json, human, or markdown` |

**ギャップ: なし**

---

## デモとの整合確認

### `mumei-demo/scenarios/spec_code_verification_suite`

- `mode_a` → V1-A: `validate-spec` — ✅ 整合
- `mode_b` → V1-B: `validate-code --language python` — ✅ 整合
- `mode_c` → V1-C: `verify-conformance --spec ... --code ... --language python` — ✅ 整合（Python のみだが demo として成立）
- `mode_d` → V1-D: `validate-code-to-spec` / `verify-traceability` — ✅ 整合

### `mumei-demo/scenarios/no_mm_audit`

- Python/Rust/TypeScript/Go の4言語 audit fixture — ✅ V1-B 4言語カバレッジ整合
- `audit -> migrate-suggest -> heal` gate order — ✅ canonical contract 整合
- 7固定キーのみ（alias なし） — ✅ `artifact_keys` が7固定キーに一致

### デモ側のギャップ: なし

`spec_code_verification_suite` が V1-C/V1-D を Python のみでデモしている点は、デモの範囲として適切（canonical は「カバレッジ」を要求するが demo は代表例で十分）。`no_mm_audit` が4言語の audit を fixture 付きでカバーしている。

---

## 総合判定サマリ

| V1 Surface | 判定 | 未完/不整合の内容 |
|------------|------|------------------|
| V1-A | ✅ 完了 | — |
| V1-B | ✅ 完了 | — |
| V1-C | ⚠️ 部分実装 | CLI `--language` に TypeScript 欠落; `_source_line_map()` に TS パスなし |
| V1-D | ⚠️ 部分実装 | CLI `--language` に TypeScript 欠落（V1-C gap の伝搬） |
| V1-E | ✅ 完了 | — |

---

## ROADMAP.md 自己申告との食い違い

`mumei-agent/docs/ROADMAP.md` の P14-C は「✅ Implemented」と表記しているが、実際には TypeScript の CLI 言語カバレッジが V1-B / `cross_validation.py` と非対称であり、canonical roadmap が要求する4言語均一カバレッジを満たしていない。

ただし以下の点で実質的影響は限定的:
- MCP `verify_conformance` / `verify_code_spec_traceability` は `language: str | None` で TypeScript を受け付ける（runtime 制限なし）
- TypeScript コードを `audit --code-file ... --language typescript` → `scan_and_fix` 経由で検証することは可能
- 不足しているのは `verify-conformance` / `verify-traceability` **単体 CLI** の argparse choices のみ

---

## 推奨次タスク候補（本タスクでは着手しない）

1. **V1-C/V1-D TypeScript CLI choices 追加** (小規模: `verify_conformance.py:21`, `verify_traceability.py:18` に `"typescript"` 追加)
2. **`conformance_verifier.py` `_source_line_map()` TypeScript regex** (TypeScript function/arrow function/class method の行番号マッピング追加)
3. **回帰テスト追加**: `tests/test_cross_validation.py` に TypeScript 用 conformance テスト
4. ~~MCP sampling の後回し項目（tool-enabled sampling / multimodal）~~ — 本タスク非対象
5. ~~新機能実装・リファクタリング~~ — 本タスク非対象
