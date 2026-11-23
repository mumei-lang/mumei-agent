# C06 設計メモ: TypeScript の compiler-backed 束縛解決

状態: 設計メモ（2026-11-24）。監査メモ [`AUDIT_BACKLOG_2026-11-21.md`](AUDIT_BACKLOG_2026-11-21.md)
項目 8 の TypeScript 担当分。初回スライスは実装済み（[`DESIGN_C06_COMPILER_BACKED_BINDINGS.md`](DESIGN_C06_COMPILER_BACKED_BINDINGS.md)
§4、[`ROADMAP.md`](ROADMAP.md)「C06 first compiler-backed TypeScript binding slice」）。
このメモは、実装済みの producer/reader の形と fail-closed 境界を記録し、
未カバー領域の段階案と決定点をまとめる。Go（`tools/go-types`）と
Solidity（`agent/sol_compiler_snapshot.py`）と同じ envelope 形に揃えてある。

## 1. 実装済みの形

| 要素 | 実体 |
|---|---|
| producer（operator 側） | `tools/ts-bindings/helper.js` — Node + 同梱 `typescript` 5.9.3（`package.json` にピン） |
| 出力 envelope | `mumei.tsc-symbol-envelope/v1` — `typescript_version` / `compiler_options` / `file_name` / `source` / `diagnostics` / `unsupported` / `references` |
| 純粋リーダー | `agent/ts_compiler_snapshot.py` — `load_ts_compiler_snapshot` + `compare_with_lexical` |
| 比較レポート | `mumei.ts-compiler-bindings/v1` — 参照ごとに `builtin` / `agree` / `disagree` / `lexical_unresolved` / `lexical_missing` |

agent は Node / helper を一切起動しない。operator が固定版 `typescript` パッケージで
envelope を生成し、reader はそれを読むだけ（`tools/go-types`・`solc` 標準 JSON と同じ分離）。

## 2. 単一ファイルのシンボル解決で得られるもの（実プローブ確認済み）

pinned `typescript` 5.9.3 の `ts.createProgram`（`noResolve`, `strict`, `lib.es2022.d.ts`,
`types: []`）を sandboxed host 経由で動かした実出力:

- 同一ファイル内の宣言は **byte span のペア**で返る（参照 span → 宣言 span）。
  `checker.getSymbolAtLocation` / `getShorthandAssignmentValueSymbol` /
  `getExportSpecifierLocalTargetSymbol` / `getAliasedSymbol` で alias を剥がす。
- メンバ名 `x.foo` は受信側の型から member symbol に解決し、宣言が入力内なら
  span、標準ライブラリ側（`Math.max` 等）なら `library: true`。型チェッカーが
  解決するもののソース宣言を持たないメンバ（`prototype`・mapped-type メンバ等）も
  `library: true`（builtin 扱い、宣言一致とは扱わない）。
- `undefined` / `globalThis` / `arguments` のような intrinsic は宣言なしで
  `library: true`（builtin として記録、宣言一致とは扱わない）。
- シンボルを持たない非メンバ識別子は `declarations: null` で出力され、reader が拒否する
  （例: `console` — `lib.es2022.d.ts` のみなので `Cannot find name` の error diagnostic も付き二重に fail closed）。
- UTF-16 offset は helper 側の UTF-8 byte 写像で変換され、非境界 offset は producer 自身が例外化する。

### 単一ファイルで閉じないもの（envelope の `unsupported` に記録 → reader 拒否）

`ImportDeclaration` / `ImportEqualsDeclaration` / `ExternalExport`（module specifier 付き export）/
`ImportCall`（dynamic import）/ `ImportType` / `RequireCall` / `StringModuleDeclaration` /
`TripleSlashReference` / `TripleSlashTypeReference` / `TripleSlashLibReference`。
これらは `noResolve` host ではそもそも解決対象が読めないため、部分結果を返さず拒否する。

## 3. reader の fail-closed 境界（`load_ts_compiler_snapshot`）

1. envelope は `MAX_REPORT_BYTES` 以下、キー集合は固定の8キーのみ。
2. `typescript_version` は許可リスト `{ "5.9.3" }` に一致。
3. `compiler_options` は固定オブジェクトと完全一致（target/lib/types/noResolve/jsx 等の逸脱は拒否）。
4. `file_name` は `input.ts` / `input.tsx` のみ。
5. `source` は対象ソースと**完全一致**（stale 検出。真正性の主張ではない）。
6. `diagnostics` の `category == "error"` が1件でもあれば拒否（warning 以下は記録のみ）。
7. `unsupported` が非空なら拒否（import 系・triple-slash はここで落ちる）。
8. 各参照: `name` 非空、参照 span が UTF-8 境界かつソース文字列と一致、
   `declarations` は全 span がソース内かつ同名、`library` と宣言リストは排他
   （`library` なら宣言空、非 `library` なら宣言必須）、参照 span 同士は非重複（reader が span でソートしてから検査するため、入力の並び順は受理条件ではない）。
9. `compare_with_lexical` は lexical report の `source_sha256` と envelope のソースハッシュ
   （reader が再計算する `sha256:` 値）の一致を要求し、profile を `mumei.ts-lexical-bindings/v1` に固定する。

## 4. 出力の安定性

- envelope はキーソート済み JSON、span は UTF-8 byte offset で決定的。
- 宣言 span・diagnostic の文言・コードは `typescript` のバージンに依存するため、
  バージン追加は必ず (a) `package.json` のピン更新、(b) `ALLOWED_TYPESCRIPT_VERSIONS` への追加、
  (c) そのバージンの実出力 fixture、の3点セットで行う。
- TypeScript 7.x は JavaScript compiler API を持たないため、現行 API 系（5.9.x）でのみ運用可能。

## 5. 段階案

1. **landed（現行）**: 単一ファイル・import なし・`lib.es2022.d.ts` のみ・メタデータ比較のみ。
compiler option の `lib` は `lib.es2022.d.ts` 単独だが、host は同梱パッケージ内の
   `lib*.d.ts` をすべて提供するため、`lib.es2022.d.ts` が推移参照する `lib.es5.d.ts`・
   `lib.decorators.d.ts` 等も解決される（DOM / Node 型は es2022 の推移集合に含まれず到達しない）。
2. **lib 拡張（小）**: `lib.dom.d.ts` 等を許可する場合は `(version, lib)` の組を許可リスト化し、
   envelope の `compiler_options.lib` をその組で fixture 化。DOM/Node 型の解決は
   「宣言はライブラリ側（source 外）→ `library: true`」のまま変わらないため、reader 側の
   変更は compiler_options の許可集合のみで済む見込み。需要が出るまで実施しない。
3. **import / module 解決（中〜大、別設計必須）**: `noResolve` を外すと複数ファイルの信頼境界になる。
   Rust の LSIF slice（project 同梱バイト列 + ハッシュ、単一 root package 限定）と同じ方式で、
   envelope が解決済みモジュールのソース本文とハッシュを同梱し、cross-file 宣言は
   path + span で記録・lexical 比較は同一ファイル内のみ、という形が候補。需要ゲート。
4. **型情報の出力（大）**: `checker.typeToString` / signature 情報を envelope に載せると
   出力契約の安定性が低下する（バージン差が大きい）。現行は参照→宣言のみを維持し、
   追加する場合は別 envelope profile とする。

## 6. 決定点（推奨を記録）

| 決定点 | 推奨 |
|---|---|
| Node/typescript の provisioning | operator 側に留める（agent は起動しない）。`package-lock.json` のコミット済み固定を維持 |
| バージン許可リスト | `{"5.9.3"}` のまま。追加時は pinned package + fixture + allowlist の3点セット |
| lib の拡張 | 需要があるまで `lib.es2022.d.ts` 単独。拡張時は `(version, lib)` 組の許可リスト化 |
| import / 複数ファイル | fail-closed のまま。拡張する場合は Rust LSIF slice と同じ「ソース同梱 + ハッシュ」方式で別設計 |
| シンボルなしメンバ名 | 現行の「参照として出力しない」を維持（受信式自体が記録されるため検証可能情報を失わない） |
| 型文字列の出力 | 現行の「参照→宣言 span のみ」を維持。追加するなら別 profile で |
| trust への影響 | なし。compiler-backed で解決できても `complete` / trusted-safe / audit / Seal Grade / Lean の判定は変えない。不一致は gap として記録するのみ |

## 7. 受理チェックリストとの対応（#651）

1. unresolved / alias / dynamic を trusted-safe にしない → `declarations: null`・
   `unsupported`・error diagnostic はすべて拒否、`library` は宣言一致として扱わない。
2. 言語ごとの positive / negative fixture → `tests/test_ts_compiler_snapshot.py` に
   byte-span・shadowing・reassignment・stale・許可外バージン・unsupported 各種の fixture あり。
3. 既存ルートへの回帰なし → CLI/MCP ルート追加なし、lexical report の契約は不変。
