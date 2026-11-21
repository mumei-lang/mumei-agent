# C06 設計メモ: TS / Rust / Solidity の compiler-backed 束縛解決（次スライス）

状態: 設計メモ（2026-11-21）。監査メモ [`AUDIT_BACKLOG_2026-11-21.md`](AUDIT_BACKLOG_2026-11-21.md) 項目 8 の
`agent` 担当分（TS / Rust / Solidity）。Go 側（`tools/go-types`、`agent/go_interprocedural.py`）は対象外。

## 1. 現状（develop で確認済み）

| 言語 | コマンド | スキーマ | 解決方式 |
|---|---|---|---|
| Rust | `python -m agent rust-bindings <file> --pointer-width {16,32,64}` | `mumei.rust-lexical-bindings/v1` | tree-sitter、単一ファイル |
| Solidity | `python -m agent sol-bindings <file>` | `mumei.sol-lexical-bindings/v1` | tree-sitter、単一ファイル |
| TypeScript | `python -m agent ts-bindings <file>` | `mumei.ts-lexical-bindings/v1` | tree-sitter、単一ファイル（`.tsx` は TSX 文法） |

- 共有モデルと fail-closed リーダーは `agent/lexical_bindings.py`（`PROFILE_RESOLUTION = "lexical"`）。
- 未解決名（import、修飾パス、builtin、オーバーロード等）や gap（マクロ、`cfg`、inline assembly、`eval` 等）が
  1つでもあると `complete=false` になり、trusted-safe には扱われない。
- 3言語ともコンパイラは一切関与しない。型推論・import 解決・オーバーロード解決は行わない。
- Go だけは compiler-backed の先行スライスがある（`tools/go-types`: operator がビルドする helper が
  `go/types` で単一ファイルを型検査し、`agent.go_type_snapshot` の純粋な fail-closed リーダーが消費する。
  agent 自身はプロセスを起動しない）。

#651 の C06 受理チェックリスト（未チェック）:
1. unresolved / alias / dynamic な束縛を trusted-safe として扱わない。
2. 言語ごとの positive / negative fixture。
3. 既存ルート（audit、Seal Grade、Lean freshness/trust）の回帰なし。

## 2. 言語ごとの compiler-backed 候補

| 言語 | 候補の producer | 単一ファイルで閉じるか | provisioning | 出力の安定性 |
|---|---|---|---|---|
| Solidity | `solc --standard-json`（AST の識別子ノードが宣言 ID を参照する） | import なしなら閉じる | 単一バイナリ。バージョン固定が容易 | コンパイラバージョンごとに固定 |
| TypeScript | TypeScript compiler API（type checker のシンボル解決） | `lib.d.ts` 等の標準ライブラリ宣言が必要 | Node と `typescript` パッケージの同梱が必要 | パッケージのバージョンごとに固定 |
| Rust | rust-analyzer の SCIP 出力など | Cargo プロジェクトが前提。単一ファイルで閉じない | rustup のコンポーネント | rust-analyzer の内部表現に依存し、安定した契約がない |

（表の producer の能力は各ツールの公開ドキュメントに基づく見立て。Solidity は
`solc` 0.8.39+commit.ce47f2c8 の実出力 fixture を採取済み。TypeScript / Rust は未採取。）

## 3. 推奨: 最初のスライスは Solidity

理由:
- Go の `go-types` と同じ形（単一ファイル・import なら fail-closed・バージョン固定のコンパイラ）に最も素直に乗る。
- 既存の `sol-bindings` が `complete=false` になる主因（オーバーロード、継承、builtin）は、コンパイラの
  宣言参照で解決できる種類のもの。
- TypeScript は標準ライブラリ宣言とパッケージ同梱、Rust はプロジェクト前提と出力契約の不安定さが先に問題になる。

### 3.1 形（Go の先行スライスに合わせる）

- **producer は operator 側**: agent は `solc` を起動しない。operator が固定バージョンの `solc` で
  standard-JSON の入力と出力を用意する。agent はツールの選択・ダウンロード・実行をしない。
- **純粋な fail-closed リーダー**（例: `agent/sol_compiler_snapshot.py`）:
  - 入力 JSON のソース本文が対象ファイルのバイト列と完全一致すること（不一致は stale として拒否）。
  - 出力に severity `error` があれば拒否。部分的な束縛は返さない。
  - `import` を含むソースは拒否（単一ファイル限定。Go 側と同じ）。
  - コンパイラバージョンを記録し、許可リスト外なら拒否。standard-JSON の出力自体にはバージョン欄がないため、
    operator は同じバイナリの `solc --version` の出力を入力・出力 JSON と一緒に渡す（3点を1つの封筒にまとめる）。
    出力に contract の `metadata` が含まれる場合は、その `compiler.version` との一致も検査し、不一致は拒否する。
- **出力はメタデータのみ**: 識別子の span → 宣言 span の対応を、既存の lexical report の binding ID に
  突き合わせた結果（一致 / 不一致 / lexical 側が未解決）として出す。
  `require` や `msg` などの組み込みは対象ソース内に宣言位置がないため、span の照合とは別に `builtin` として記録する
  （固定版の AST での組み込み参照の表現は、fixture 採取時に確認してから決める）。組み込みへの解決は宣言 span の一致として扱わない。
- **trust を上げない**: compiler-backed で解決できても、`complete`、trusted-safe、audit 判定、Seal Grade、
  Lean の trust/freshness は変えない。不一致は gap として記録する。ソースの一致は staleness の検出であり、
  producer の真正性や意味の正しさは主張しない。

### 3.2 受理条件（チェックリストとの対応）

1. オーバーロード・継承・modifier で、lexical 側が `unresolved` / `opaque_overload` の参照が、
   compiler 側では具体的な宣言に解決される positive fixture。builtin の参照は宣言 span に解決せず、
   `builtin` として記録されることを確認する fixture。
2. import を含むソース、コンパイルエラー、ソース不一致、許可外バージョン、出力の切り詰めがすべて
   選択なし（fail-closed）になる negative fixture。
3. inline assembly・低レベル呼び出し（`call` / `delegatecall`）・関数型の値は、compiler 側で宣言が
   見えても dynamic として trusted-safe にしない。
4. 既存の `sol-bindings` の出力と、audit / CLI / MCP のルートは変わらない。

### 3.3 前提条件と実装状況

- 状態: `solc` 0.8.39+commit.ce47f2c8 の fixture 採取済み。最初の実装範囲と境界は
  `docs/ROADMAP.md` の「C06 first compiler-backed Solidity binding slice」を参照。
- 実際の standard-JSON 出力の fixture（AST 形式はバージョンで変わるため、許可リストのバージョンごと）。

## 4. 後続（このメモでは実装しない）

- TypeScript: `typescript` パッケージを固定バージョンで同梱する operator helper（Node）＋純粋リーダー。
  標準ライブラリ宣言を helper に同梱し、ユーザーの `tsconfig` や `node_modules` は読まない。
- Rust: 単一ファイルで閉じないため、プロジェクト単位の解決（C06 の「project/import resolution」）を
  先に設計する必要がある。それまでは lexical report のまま。
