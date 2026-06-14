# 検証ワークフローガイド

## 前提条件（セットアップ）

```bash
# mumei インストール
curl -fsSL https://mumei-lang.github.io/mumei/install.sh | bash
# または: brew install mumei-lang/mumei/mumei

# mumei-agent セットアップ
git clone https://github.com/mumei-lang/mumei-agent
cd mumei-agent
cp .env.example .env
# .env を編集: LLM_BASE_URL / LLM_API_KEY / LLM_MODEL を設定
brew install uv  # 未インストールの場合
uv sync
# 以降は `uv run mumei-agent ...` で実行
# （または `source .venv/bin/activate` 後に `mumei-agent ...`）

# LLM バックエンド起動（Ollama を使う場合）
docker compose up -d
docker exec mumei-ollama ollama pull qwen3.5
```

## ユースケース一覧（早見表）

| やりたいこと | コマンド |
|---|---|
| 自然言語仕様の矛盾チェック | `mumei-agent extract-spec --text "..." --check-contradiction-only --output report.json` |
| 仕様ファイルの矛盾チェック | `mumei-agent extract-spec --text-file spec.txt --check-contradiction-only --output report.json` |
| 単一コードファイルの検証 | `mumei-agent extract-spec --code-file src/foo.rs --output spec.json` |
| ディレクトリ単位のコード検証 | `mumei-agent extract-spec --code-file src/ --output spec.json` |
| 仕様→コード整合性検証 | `mumei-agent extract-spec --text-file spec.txt --generate --generate-output out.mm --output spec.json` |
| コード→仕様の逆検証 | `mumei-agent extract-spec --code-file src/ --check-contradiction-only --output report.json` |
| 自然言語仕様の詳細検証（矛盾・曖昧さ・過制約） | `mumei-agent validate-spec --input spec.txt --format nl` |
| 外国語コードの詳細検証 | `mumei-agent validate-code --input code.py --language python` |
| 仕様→コードの整合性検証 | `mumei-agent validate-spec-to-code --spec spec.txt --code src/foo.py --language python` |
| コード→仕様のドリフト検出 | `mumei-agent validate-code-to-spec --code src/foo.py --spec spec.txt --language python` |
| 仕様の健全性チェック（vacuity含む） | `mumei-agent check-spec-health spec.mm` |
| 外国語コードのコントラクト抽出・検証 | `mumei-agent verify-foreign --input code.rs --language rust` |
| エディタ統合（LSP） | `mumei lsp` |
| MCP 経由（Claude Code 等） | `.mcp.json` 設定後、AI エージェントから利用 |

## 1. 自然言語仕様の検証

**目的**: 仕様書・要件定義文書に矛盾・不整合がないかを Z3 で検証する。

### 1-1. インラインテキスト（単一仕様）

```bash
mumei-agent extract-spec \
  --text "送金額は正の整数のみ。送金後の残高は非負。残高不足はエラー。" \
  --check-contradiction-only \
  --output /tmp/spec_report.json \
  --domain financial  # 任意
```

出力例（矛盾なし）:

```text
No direct contradiction was detected in the extracted specification.
Contradiction report written to /tmp/spec_report.json
```

出力例（矛盾あり）:

```text
The extracted natural-language specification contains a direct contradiction.
SpecValidation failed for the synthesized specification: ...
```

### 1-2. テキストファイルから読み込む

```bash
# spec.txt に仕様を記述
mumei-agent extract-spec \
  --text-file docs/requirements/payment_spec.txt \
  --check-contradiction-only \
  --output reports/payment_contradiction.json \
  --domain financial  # 任意
```

### 1-3. ドメインヒント一覧

`--domain` は任意引数。未指定でも実行できる。指定できる値: `financial`, `compliance`, `regtech`, `security`, `iot`, `web`, `data_structure`, `math`, `general`

### 1-4. MCP 経由（AI エージェントから）

`check_spec_contradiction` ツールを呼ぶ:

```json
{
  "natural_language": "x must be greater than 0 and less than 0",
  "domain_hint": "math"
}
```

### 1-5. validate-spec（詳細検証）

`extract-spec --check-contradiction-only` より詳細な検証を行う専用コマンド。矛盾・曖昧さ・過制約・Z3充足可能性を個別に報告する。

#### 単一テキストファイル

```bash
mumei-agent validate-spec \
  --input docs/requirements/payment_spec.txt \
  --format nl \
  --domain financial  # 任意
```

#### 出力フィールド

- `contradictions[]`: 論理的矛盾（例: x > 0 かつ x < 0）
- `ambiguities[]`: 曖昧な記述（複数解釈が可能な箇所）
- `overconstraints[]`: 過制約（Z3で充足不可能な組み合わせ）
- `satisfiable`: Z3による充足可能性（true/false/null）
- `inferred_atoms[]`: 推論されたMumeiコントラクト

## 2. 既存コードの検証

**目的**: Rust/C/Go/Python/TypeScript 等の既存コードに論理的な問題がないかを抽出・検証する。

`extract-spec --code-file` は単一ファイルとディレクトリの両方を受け付ける。ディレクトリを渡すと対応拡張子のファイルをまとめて処理する。
`validate-code --input`、`validate-spec-to-code --code`、`validate-code-to-spec --code` は単一コードファイルを指定する。

`extract-spec` の対応言語: `rust`, `c`, `cpp`, `go`, `python`, `javascript`, `typescript`, `java`（拡張子から自動検出）。
`validate-code` の `--language` は必須で、`python|rust|go` のいずれかを指定する。`validate-spec-to-code` / `validate-code-to-spec` の `--language` は任意で、省略時はコードファイルの拡張子から推定する。

### 2-1. 単一ファイル

```bash
mumei-agent extract-spec \
  --code-file src/payment.rs \
  --output reports/payment_spec.json \
  --domain financial  # 任意
```

言語を明示する場合:

```bash
mumei-agent extract-spec \
  --code-file src/payment.rs \
  --code-language rust \
  --output reports/payment_spec.json
```

### 2-2. ディレクトリ単位（複数ファイル）

```bash
mumei-agent extract-spec \
  --code-file src/ \
  --output reports/src_spec.json \
  --domain financial  # 任意
```

ディレクトリ内の対応拡張子ファイルをすべて処理し、マージされた仕様を出力する。
出力 JSON の `files[]` に各ファイルの個別結果、`merged_spec` に統合仕様が含まれる。

### 2-3. 矛盾チェックまで一括実行

```bash
mumei-agent extract-spec \
  --code-file src/ \
  --check-contradiction-only \
  --output reports/src_contradiction.json
```

### 2-4. MCP 経由

`extract_spec` ツールで `code_file` を指定する:

```json
{
  "code_file": "/repo/src/payment.rs",
  "language": "rust",
  "domain_hint": "financial",
  "generate": false,
  "mumei_repo": "/path/to/mumei"
}
```

### 2-5. validate-code（詳細検証）

`extract-spec --code-file` より詳細な検証を行う専用コマンド。コントラクト推論・Z3検証・Mumei検証を統合して実行する。`--input` には単一コードファイルを指定する。

```bash
mumei-agent validate-code \
  --input src/payment.py \
  --language python  # 必須: python|rust|go
```

`validate-code` の `--language` は必須。自動検出は行わない。

出力フィールド:

- `inferred_atoms[]`: 推論されたMumeiコントラクト
- `mumei_source`: 生成されたMumei仕様コード
- `satisfiable`: Z3による充足可能性
- `issues[]`: 検出された問題（kind: contradiction/overconstraint/verification等）

## 3. 自然言語仕様 → 既存コードの整合性検証

**目的**: 仕様書に基づいてコードが正しく実装されているかを検証する。

### 3-1. 仕様からコードを生成して検証（仕様が正しいかの確認）

```bash
mumei-agent extract-spec \
  --text-file docs/requirements/payment_spec.txt \
  --generate \
  --generate-output /tmp/payment_verified.mm \
  --output /tmp/payment_spec.json \
  --domain financial  # 任意
```

成功時: `Generated verified code written to /tmp/payment_verified.mm`
失敗時: `Warning: Generated code written to ... but verification failed`

### 3-2. 既存コードと仕様の cross-spec 検証（複数ファイル間）

まず各ファイルから `.mm` 仕様を生成し、cross-spec で整合性を確認する:

```bash
# 仕様抽出 → .mm 生成
mumei-agent extract-spec \
  --code-file src/account.rs \
  --generate \
  --generate-output /tmp/account.mm \
  --output /tmp/account_spec.json

mumei-agent extract-spec \
  --code-file src/transfer.rs \
  --generate \
  --generate-output /tmp/transfer.mm \
  --output /tmp/transfer_spec.json

# cross-spec 検証
mumei verify \
  --report-dir reports/cross-spec \
  --cross-spec-files /tmp/account.mm \
  /tmp/transfer.mm
```

`reports/cross-spec/cross_spec.json` に以下が出力される:

- `contract_consistency[]`: 呼び出し元/先のコントラクト整合性
- `global_invariants[]`: 全体で共有される不変条件
- `global_invariant_conflicts[]`: 矛盾する不変条件
- `circular_dependencies[]`: 循環依存

### 3-3. MCP 経由（cross-spec）

`check_cross_spec_consistency` ツールを呼ぶ:

```json
{
  "spec_files": ["/tmp/account.mm", "/tmp/transfer.mm"]
}
```

### 3-4. validate-spec-to-code（専用コマンド）

仕様書に記述された制約がコードに実装されているかを直接検証する。`extract-spec` + cross-spec の2ステップを1コマンドで実行できる。

```bash
mumei-agent validate-spec-to-code \
  --spec docs/requirements/payment_spec.txt \
  --code src/payment.py \
  --language python  # 任意: python|rust|go
```

`--spec` は仕様ファイル、`--code` は単一コードファイルを指定する。

出力フィールド:

- `missing_constraints[]`: 仕様にあるがコードに実装されていない制約
- `divergences[]`: 仕様とコードで矛盾する制約
- `spec_atoms[]`: 仕様から推論されたコントラクト
- `code_atoms[]`: コードから推論されたコントラクト
- `satisfiable`: 統合後の充足可能性

## 4. 既存コード → 自然言語仕様の逆検証

**目的**: コードから仕様を逆抽出し、元の要件定義と照合する。

### 4-1. コードから仕様を抽出する

```bash
mumei-agent extract-spec \
  --code-file src/payment.rs \
  --output reports/extracted_spec.json
```

出力 JSON の `natural_language_spec` フィールドに自然言語仕様が含まれる。

### 4-2. 抽出仕様の矛盾チェック

```bash
mumei-agent extract-spec \
  --code-file src/payment.rs \
  --check-contradiction-only \
  --output reports/code_contradiction.json
```

### 4-3. ディレクトリ全体から仕様を逆抽出

```bash
mumei-agent extract-spec \
  --code-file src/ \
  --check-contradiction-only \
  --output reports/src_contradiction.json
```

`files[].natural_language_spec` に各ファイルの自然言語仕様が含まれる。
これを元の要件定義と人手で照合するか、さらに `--text-file` で元仕様を渡して比較する。

### 4-4. 既存 .mm ファイルの直接検証

すでに `.mm` ファイルがある場合は mumei CLI を直接使う:

```bash
# 単一ファイル
mumei verify src/main.mm

# JSON 出力（AI・スクリプト向け）
mumei verify --json src/main.mm

# レポートディレクトリ指定
mumei verify --report-dir reports/ src/main.mm

# 複数ファイル cross-spec
mumei verify --report-dir reports/ --cross-spec-files src/account.mm src/transfer.mm
```

### 4-5. validate-code-to-spec（専用コマンド）

コードが変更された際に、仕様書が追従できているかを検証する（仕様ドリフト検出）。

```bash
mumei-agent validate-code-to-spec \
  --code src/payment.py \
  --spec docs/requirements/payment_spec.txt \
  --language python  # 任意: python|rust|go
```

`--code` は単一コードファイル、`--spec` は仕様ファイルを指定する。

出力フィールド:

- `drift_issues[]`: コードと仕様の乖離（kind: drift/alignment）
- `changed_hunks[]`: コードの変更箇所
- `spec_atoms[]`: 仕様から推論されたコントラクト
- `code_atoms[]`: コードから推論されたコントラクト

## 5. 人間が操作する際のヒント・配慮

### 5-1. エディタ統合（LSP）

```bash
# LSP サーバー起動
mumei lsp
```

VS Code 拡張（`editors/vscode/`）をインストールすると:

- `requires`/`ensures` のインライン表示
- Intent Drift スコア（0.00〜1.00）の CodeLens 表示
- カウンター例のゴーストテキスト装飾
- 複数スパン診断（関連ソース位置の同時表示）

### 5-2. REPL（対話的な検証）

```bash
mumei repl
```

小さな仕様を試しながら Z3 検証を確認できる。

### 5-3. MCP 経由（Claude Code / Devin 等）

`mumei-lang/mumei` リポジトリルートで:

```bash
pip install "mcp[cli]>=1.0"
python mcp_server.py
```

`mumei-lang/mumei-agent` で:

```bash
uv run mumei-agent mcp-server
```

`.mcp.json` 設定例（両サーバーを同時利用）:

```json
{
  "mcpServers": {
    "mumei-forge": {
      "command": "sh",
      "args": ["-lc", "cd /path/to/mumei && exec python mcp_server.py"]
    },
    "mumei-agent": {
      "command": "sh",
      "args": ["-lc", "cd /path/to/mumei-agent && exec uv run mumei-agent mcp-server"]
    }
  }
}
```

### 5-4. 診断出力の読み方

`mumei verify` の出力はバイリンガル（EN/JP）:

```text
× Verification Error: Postcondition (ensures) is not satisfied.
  help: ensures の条件を確認してください。body の返り値が事後条件を満たすか検討してください
```

JSON 出力（`--json`）の主要フィールド:

- `failure_type`: エラー種別（`precondition_violated`, `effect_mismatch` 等）
- `counterexample`: Z3 が見つけた反例の具体値
- `semantic_feedback.violated_constraints`: 違反した制約の詳細
- `semantic_feedback.data_flow`: データフロー追跡
- `suggestion`: 修正提案

### 5-5. 自己修復ループ（繰り返し検証）

```bash
# 既存 .mm ファイルを自動修復
uv run mumei-agent heal src/main.mm

# 予算制限付き
uv run mumei-agent heal src/main.mm --budget-policy budget_policy.json

# 自己修正プロトコル（収束まで繰り返す）
uv run mumei-agent self-correct src/main.mm --max-repairs 10 --required-successes 3
```

### 5-6. 仕様の健全性チェック（vacuity）

仕様が弱すぎないかを確認する:

```bash
MUMEI_ENABLE_VACUITY_CHECK=1 mumei verify spec.mm
# または
mumei verify --enable-vacuity-check spec.mm
```

### 5-7. ドキュメント生成

検証済みコードからドキュメントを生成:

```bash
mumei doc src/main.mm -o docs/api/ --format html
mumei doc src/main.mm -o docs/api/ --format markdown
```

### 5-8. check-spec-health（仕様の健全性チェック）

既存の `.mm` ファイルの仕様が矛盾・過制約・vacuity（弱すぎる仕様）を含んでいないかを確認する。

```bash
uv run mumei-agent check-spec-health src/main.mm
```

### 5-9. verify-foreign（外国語コードのコントラクト抽出・検証）

外国語コードからコントラクトを抽出し、Mumei atomとして形式検証する。

```bash
uv run mumei-agent verify-foreign \
  --input src/payment.rs \
  --language rust
```

## フィードバックの読み方

| フィールド | 意味 | 対処 |
|---|---|---|
| `contradiction_found: true` | 仕様内に矛盾がある | `natural_language_explanation` を読んで仕様を修正 |
| `precondition_violated` | 事前条件が満たされない | `requires` 節を見直す |
| `postcondition_violated` | 事後条件が満たされない | `ensures` 節またはロジックを見直す |
| `effect_mismatch` | 副作用の宣言漏れ | `effects:` 節に不足エフェクトを追加 |
| `outside_decidable_fragment` | Z3 の決定可能フラグメント外 | 線形算術に書き直すか Lean エスカレーション |
| `inconsistent_calls` | 呼び出し元/先のコントラクト不整合 | 呼び出し元の `requires` を強化するか呼び出し先の `requires` を緩和 |
| `ambiguity` | 仕様の記述が曖昧で複数解釈が可能 | 曖昧な箇所を具体的な数値・条件で明確化する |
| `overconstraint` | 制約が強すぎてZ3で充足不可能 | 制約を緩和するか、条件を分割する |
| `missing_implementation` | 仕様の制約がコードに実装されていない | コードに対応するバリデーション・ガード節を追加する |
| `drift` | コードが変更されたが仕様が追従していない | 仕様書を最新のコードに合わせて更新する |

詳細は [`docs/REPORT_SCHEMA.md`](https://github.com/mumei-lang/mumei/blob/develop/docs/REPORT_SCHEMA.md) および [`docs/SPEC_GUIDE.md`](https://github.com/mumei-lang/mumei/blob/develop/docs/SPEC_GUIDE.md) を参照。
