# Non-deferred backlog audit (2026-11-21)

Status: investigation report. Sources: every comment on
[issue #651](https://github.com/mumei-lang/mumei-agent/issues/651) (222 comments),
[`docs/ROADMAP.md`](ROADMAP.md) and mumei
[`docs/CROSS_PROJECT_ROADMAP.md`](https://github.com/mumei-lang/mumei/blob/develop/docs/CROSS_PROJECT_ROADMAP.md)
at develop on 2026-11-21, plus PRs merged on 2026-11-20/21 in mumei, mumei-agent and mumei-demo.

根拠: 担当境界を固定した後に重複なく残件を進めるため、「非 deferred で未着地」の項目を一覧化し、各項目に推定担当領域を付ける。
本メモは計画であって、ここに挙げた項目の着地や完了を主張しない。

## Ownership legend

| Tag | Area |
| --- | --- |
| `go-ip` | mumei-agent `agent/go_interprocedural.py` (Go deep analysis, chan and non-chan) |
| `core-B` | mumei Core C10 Option B (object-code TV, `native-bundle` commands) |
| `core-ve` | mumei Core verifier/emitter deep work |
| `agent` | mumei-agent outside `agent/go_interprocedural.py` (routes, docs, ROADMAP) |
| `demo` | mumei-demo scenarios and assertions |
| `sync` | mumei `docs/CROSS_PROJECT_ROADMAP.md` supplement sync |

## Non-deferred, not yet landed

| # | Item | Owner | Gate | Note |
| --- | --- | --- | --- | --- |
| 1 | Demo scenario whose atom exercises branching and direct calls, so `machine_code_direct_call_site_tv` / `machine_code_forward_branch_function_tv` / `machine_code_acyclic_branch_function_tv` / `machine_code_conditional_call_function_tv` are actually performed and discharged in a demo run | `demo` | none (Core #1206/#1209/#1210 and agent #1062/#1064/#1066 landed) | 既存 `native_machine_tv_recheck` の atom は分岐も呼び出しも持たず、上記4チェックは常に未実施。demo では leaf TV しか通っていない。 |
| 2 | Demo scenarios for agent routes with no demo coverage: `evidence-accept-list`, `evidence-check-adapter`, `evidence-check-attempt-acceptance`, `evidence-acceptance-eval` | `demo` | none | `evidence_check_schedule` などの兄弟ルートには scenario がある。C13 の回帰面として不足。 |
| 3 | CROSS_PROJECT_ROADMAP sync gaps (landed, PR number absent from the file): agent #1026, #1037, #1041, #1048, #1061, #1065, #1067; demo #163, #164; Core #1167, #1169, #1170, #1184–#1191, #1208, #1211 | `sync` | none | Core 側の機能 PR は本文が文言で反映されている場合があるため、番号の相互参照として追補する。docs-sync PR 自体は対象外。 |
| 4 | `native-object-accept` / object-stage acceptance consumer | `agent` | Core object-stage acceptance producer (`core-B`) | Core に `accept-object` 相当がないため、agent 側で受理を発明しない。 |
| 5 | `object_translation_correspondence` discharge (full object TV) | `core-B` then `agent` | Core full object-TV producer | bounded machine-TV/object recheck では discharge しない。 |
| 6 | Further machine-TV profile widening (cyclic control flow / loops, ABI) | `core-B` | research | agent/demo は Core が語彙を追加した時点で追従する。 |
| 7 | C06/C07 Go generic models beyond the chan frontier (e.g. closures, struct/nested literal escapes left closed in #1061/#1065/#1067) | `go-ip` | none stated | cce5 が chan 系 frontier の完了を #651 で報告済み。残りは汎用モデル課題として `go-ip` 担当。 |
| 8 | C06 acceptance checklist on #651 (unresolved/alias/dynamic not trusted-safe; per-language fixtures; regressions) | `go-ip` for Go; `agent` for TS/Rust/Solidity binding reports | none | 3 項目とも未チェック。TS/Rust/Sol は lexical binding report 段階で、compiler-backed 解決は未着手。言語ごとの次スライスは別途設計が必要。 |
| 9 | Core `docs/MCP_TOOL_CONTRACT.md` omits many agent MCP tools (`native_*`, `evidence_*`, `go_summaries*`) | mumei docs outside `sync` | none | 本担当の範囲（CROSS_PROJECT_ROADMAP のみ）外のため記録のみ。 |

## Landed since the audit (2026-11-23)

- Item 1 — landed: `native_machine_tv_branch_call_recheck` asserts all four
  branch/call checks in `checks_performed`
  ([mumei-demo#171](https://github.com/mumei-lang/mumei-demo/pull/171)).
- Item 2 — landed: all four routes have scenarios
  ([mumei-demo#172](https://github.com/mumei-lang/mumei-demo/pull/172)).
- Item 3 — covered by 追補（31）in
  [mumei#1340](https://github.com/mumei-lang/mumei/pull/1340) (draft): agent
  #1026/#1037/#1041/#1048/#1061/#1065/#1067, demo #163/#164, Core #1167/#1169/
  #1170/#1184–#1191/#1208/#1211 are cross-referenced by number.

## Deferred or demand-gated (excluded)

- C12 authority correspondence: demand-gated (concrete use case required).
- C14 WASM, additional solvers, dynamic capability stages: deferred.
- C08 key rotation / revocation beyond the current declared list: deferred.

## Plan within this owner's area

1. Items 3 (`sync`) and 1 (`demo`) first; both have no external gate.
2. Item 2 one route per PR.
3. Items 4–9 are recorded only; they cross into `core-B`, `core-ve`, `go-ip` or Core docs, or need a separate design.

根拠: 1 と 3 は依存がなく、主張範囲も既存の bounded 語彙の範囲に収まる。2 は既存ルートの回帰面の追加で新しい主張を増やさない。
