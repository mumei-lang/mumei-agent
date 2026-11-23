# C06 設計メモ: Rust の compiler-backed 束縛解決

状態: 設計メモ（2026-11-24）。監査メモ [`AUDIT_BACKLOG_2026-11-21.md`](AUDIT_BACKLOG_2026-11-21.md)
項目 8 の Rust 担当分。初回スライスは実装済み（[`DESIGN_C06_COMPILER_BACKED_BINDINGS.md`](DESIGN_C06_COMPILER_BACKED_BINDINGS.md)
§4、[`ROADMAP.md`](ROADMAP.md)「C06 first compiler-backed Rust binding slice」）。
このメモは rust-analyzer 出力の単一ファイル限界（実プローブ結果）、実装済みの
producer/reader 形と fail-closed 境界、および残領域の段階案・決定点をまとめる。
Go（`tools/go-types`）・Solidity（`agent/sol_compiler_snapshot.py`）・
TypeScript（`agent/ts_compiler_snapshot.py`）と同じ envelope 形に揃えてある。

## 1. 実装済みの形

| 要素 | 実体 |
|---|---|
| producer（operator 側） | pinned `rust-analyzer lsif` 1.100.0 (`0ef1bc3 2026-11-09`)。`tests/fixtures/rust_analyzer/regenerate.py` が `file:///project`・`file:///sysroot` に URI を正規化してバイト再現可能な envelope を生成 |
| 出力 envelope | `mumei.rust-analyzer-lsif-envelope/v1` — `rust_analyzer_version` / `target` / `documents`（project 同梱バイト列 + sha256）/ `lsif` |
| 純粋リーダー | `agent/rust_compiler_snapshot.py` — `load_rust_compiler_snapshot` + `compare_with_lexical` |
| 比較レポート | `mumei.rust-compiler-bindings/v1` — 参照ごとに `agree` / `disagree` / `lexical_unresolved` / `lexical_missing` / `cross_file` / `external` |

agent は rust-analyzer / Cargo / rustc を一切起動しない。

## 2. rust-analyzer の単一ファイル限界（実プローブ: 1.100.0 stable）

CLI サブコマンド（`lsif` / `scip` / `analysis-stats` / `diagnostics` / `unresolved-references` /
`prime-caches`）はすべて **プロジェクトルートのディレクトリを要求**する。
ベアな `main.rs` を渡すと `Not a directory` で失敗する（`ProjectManifest::discover_single`）。

実測（pinned 1.100.0、rust-src インストール済み sysroot）:

- `rust-analyzer lsif` は `<path>` に Cargo.toml または `rust-project.json` を持つ
  ディレクトリを要求し、UTF-16 offset の LSIF JSONL を約160msで出力する。
- 演算子合成の単一 crate `rust-project.json`（`root_module` = 対象ファイル、
  `deps: []`）でも LSIF は生成されるが、**std prelude が入らず `println!` が
  `unresolved macro` になる**（Cargo の暗黙 `extern crate std` 相当が無い）。
  `rust-project.json` の `crates` に `std`/`core`/`alloc` を `sysroot_src` 配下の
  `library/*/src/lib.rs` として列挙し `deps` で繋げると prelude が解決し
  `unresolved-references` が空になる。
- `rust-analyzer scip` も同様にプロジェクトルートが必要で、binary protobuf
  （`index.scip`）を出力する。LSIF を採用済み（JSONL で機械可読・差分可視）。
- `rust-analyzer diagnostics` / `unresolved-references` も `rust-project.json` を
  受け付ける。`diagnostics` はソースにエラーがあれば exit 1 で報告する。

### 単一ファイルに閉じる代替手段の検討

| 手段 | 結果 |
|---|---|
| `rustc -Zunpretty` / save-analysis | stable では `-Z` は拒否（nightly のみ）。save-analysis は rustc から削除済み。不採用 |
| `rust-analyzer` LSP detached files | LSP クライアント経路のみ。batch producer として契約化しにくい。不採用 |
| 合成 `rust-project.json`（crate-local） | **動作する**。上記の通り prelude 解決には sysroot crate 列挙 + deps が必要で、project model を operator が再現する責任が発生する。次段階の候補（§5-3） |
| 実 Cargo プロジェクト + `lsif`（現行） | Cargo.toml/Cargo.lock を project document として同梱・ハッシュ照合する方式で採用済み |

## 3. reader の fail-closed 境界（`load_rust_compiler_snapshot`）

1. envelope は固定キーのみ。`rust_analyzer_version` は許可リスト
   `{"1.100.0 (0ef1bc3 2026-11-09)"}` に一致、`toolInfo.name == "rust-analyzer"`。
2. `lsif` の label は許可リスト（`document`/`range`/`resultSet`/`item`/`moniker`/
   `textDocument/*` 等の固定集合）に限定。未知 label は拒否。
3. `documents` に対象ソース・`Cargo.toml`・`Cargo.lock` のバイト列と sha256 を要求する。
   各 document の sha256 は同梱 content との内部一致の検査であり、呼び出し側の現行
   バイト列と照合するのは対象ソースのみ（stale 検出は対象ソースに限り、
   Cargo.toml/lock や別ファイルの事後変更は検出しない）。真正性の主張ではない。
4. Cargo 境界: 単一 root package のみ。`dependencies` / `dev-dependencies` /
   `build-dependencies`、workspace member、build script、proc-macro crate は拒否。
   lock 内の package は local（path）のみ。
5. `target` ファイル内のローカル宣言 span のみ lexical report（同一ソースハッシュ必須）
   と比較する。cross-file（project 相対パス + span）・external（moniker のみ）は
   メタデータ記録で、lexical 解決を主張しない。
6. lexical gap `macro_invocation` / `macro_definition` / `conditional_compilation`
   があれば比較自体を fail closed にする。
7. LSIF の range は UTF-16 → byte offset 変換で検査、identifier の妥当性も確認。

## 4. 出力の安定性

- rust-analyzer のサブコマンドと LSIF 内部表現は「stability guarantee なし」と
  ヘルプが明記している。バージン固定（許可リスト）+ 実出力 fixture で対処する現行方針を維持。
- fixture は `file:///project`・`file:///sysroot` への URI 正規化と document ハッシュで
  マシン非依存にバイト再現可能。
- バージン追加は pinned toolchain + fixture + `ALLOWED_RUST_ANALYZER_VERSIONS` の
  3点セットで行う。

## 5. 段階案

1. **landed（現行）**: 実 Cargo プロジェクト・単一 root package・依存なし・
   Cargo.toml/lock 同梱ハッシュ・ローカル宣言 span のみ lexical 比較。
2. **workspace / 依存の拡張（別設計必須）**: 現行は dependency・workspace member を
   一律拒否。許可する場合は dependency 解決結果（lock の整合）と vendored ソースの
   同梱方式が論点。需要ゲート。
3. **合成 `rust-project.json` 経路（中）**: Cargo プロジェクトを持たない単一ファイル
   （スクリプト的な `.rs`）に対して、operator が合成 manifest + sysroot crate 列挙で
   prelude を解決させる方式は実プローブで確認済み。ただし project model を
   operator 合成物が再現するため、envelope に manifest バイト列も同梱して
   「合成 manifest が正規形か」を検査する設計が必要。需要があるまで実施しない。
4. **macro / cfg 配下の解決（大）**: 現行は gap として fail closed。macro 展開後の
   参照解決は LSIF の hover/definition 情報の読み取り範囲拡張が必要で、
   別設計・別 profile が妥当。

## 6. 決定点（推奨を記録）

| 決定点 | 推奨 |
|---|---|
| producer の起動主体 | operator 側に留める（agent は rust-analyzer/Cargo/rustc を起動しない） |
| 出力形式 | LSIF（JSONL、許可 label フィルタ・差分可視）。SCIP は binary protobuf で検査コストが高いため不採用 |
| プロジェクト前提 | 現行の「実 Cargo プロジェクト・単一 root・依存なし」を維持。合成 `rust-project.json` は需要が出た段階で manifest 同梱検査つきの別 profile として検討 |
| バージン許可リスト | `{"1.100.0 (0ef1bc3 2026-11-09)"}` のまま。不安定なサブコマンド契約なので pin 維持 |
| cross-file / external 宣言 | メタデータ記録のみで lexical 比較しない現行を維持 |
| macro / cfg | fail closed のまま（§5-4） |
| `rustc` 系代替 | nightly 依存・save-analysis 廃止のため採用しない |
| trust への影響 | なし。`complete` / trusted-safe / audit / Seal Grade / Lean の判定は変えない |

## 7. 受理チェックリストとの対応（#651）

1. unresolved / alias / dynamic を trusted-safe にしない → dependency・workspace・
   build/proc-macro・macro/cfg gap・label 逸脱・stale はすべて拒否、cross-file/external
   は宣言一致として扱わない。
2. 言語ごとの positive / negative fixture → `tests/fixtures/rust_analyzer/` に
   `local_shadowing` / `cross_file` / `external_stdlib` / `macro_usage` /
   `build_script` / `member_access` の実出力 envelope + `regenerate.py`。
3. 既存ルートへの回帰なし → CLI/MCP ルート追加なし、lexical report の契約は不変。
