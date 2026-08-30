# Capability 委譲の需要検証（Priority 15 タスク 3 / Stage 2 着手ゲート）

> 調査日: 2026-08-30。調査対象のスナップショット: `mumei-lang/mumei-agent` `develop` @ `8b629721`、
> `mumei-lang/mumei` `develop` @ `6f793bd`（以降の件数・「存在しない」の主張はこの 2 コミット時点の実測値）。
> 対象は `mumei-lang/mumei-agent` の self-healing / generate / forge /
> audit / MCP ワークフローで、「信頼できないコード（AI 生成 atom・サードパーティ部品）に対して
> 呼び出しごとに最小権限だけを渡し、返ってきたら失効する」という制御が実際に必要になるかどうかの検証。
> 上位ロードマップは `mumei-lang/mumei` の
> [`docs/CROSS_PROJECT_ROADMAP.md`](https://github.com/mumei-lang/mumei/blob/develop/docs/CROSS_PROJECT_ROADMAP.md)
> "Priority 15: Capability Model 拡張の評価と段階的導入" のタスク 3、設計側の成果物は
> [`docs/CAPABILITY_MODEL_STUDY.md`](https://github.com/mumei-lang/mumei/blob/develop/docs/CAPABILITY_MODEL_STUDY.md)
> （タスク 1・2、結論は「技術的に着手可能」）。本ドキュメントは需要検証の成果物であり、
> コンパイラ・エージェントのコード変更は一切含まない。

## 0. 結論サマリ

**結論: 否定（現時点で需要は実在しない）。Option A（parameterized effects + Z3）継続。
Stage 2（`grant`）以降は §4 のトリガが観測されるまで保留する。**

Stage 1（capability 型宣言 + capability 型パラメータ、`grant` なし）は非破壊であるため
すでに実装済みで（mumei `docs/ROADMAP.md` P29）、本判定はそれを撤回しない。
判定したのは「`grant` / narrowing / 動的 revocation を**いま**実装する需要があるか」である。

| ユースケース候補 | 現行の到達点 | 動的 capability 委譲が本質的に必要か | 必要な Stage |
|---|---|---|---|
| UC-1 self-healing が effect 違反を「effect 宣言の追加」で修復する | 修復器が呼び出し元・呼び出し先の `effects: [...]` に不足 effect を追記する（権限拡大が修復として通る） | ❌ 不要。必要なのは**修復器側の静的な allowlist ゲート**（追加してよい effect の集合）で、呼び出しごとの委譲ではない | なし |
| UC-2 forge / generate が新規 atom を生成する | 生成 atom の effect は spec に静的に書かれ、パス制約は parameterized effect + `requires` で閉じる | ❌ 不要。生成物は単一 atom（または同一モジュール内の閉じた呼び出し）で、呼び出し地点ごとに権限を変える構造が現れない | なし |
| UC-3 サードパーティ部品の取り込み | mumei-agent は third-party `.mm` パッケージを一切消費しない（registry / `mumei add` の利用箇所ゼロ） | ❌ 現時点では対象が存在しない（将来トリガ T1） | 将来 Stage 2+3 |
| UC-4 外部コード（Rust/Go/Solidity/TS）の audit | foreign code は mumei でコンパイルされず effect system の外にある。境界は audit レポートと trusted atom / FFI 数 | ❌ 不適用。`.mm` の capability では foreign code を制約できない | なし |
| UC-5 harness 自身の外部ツール呼び出し（LLM API / Lean bridge / git / MCP） | Python プロセス内の `subprocess` と env var 注入。パス封じ込めは Python 側で実施 | ❌ 不適用。`.mm` の `grant` は harness プロセスの権限を制約できない（必要ならプロセス分離 / OS サンドボックス） | なし |
| UC-6 生成コードの実行時サンドボックス | mumei-agent は生成 `.mm` を**実行しない**（`verify` / `check` / `infer-*` / `build` のみ） | ❌ 不要。失効させる実行時主体が存在しない（将来トリガ T2） | 将来 Stage 4 |

観測データ側でも需要シグナルは出ていない: `reports/` の dogfood 実行記録に
`effect_mismatch` / `effect_propagation` / `effect_violation` の出現は **0 件**であり、
`docs/CAPABILITY_SECURITY.md`（mumei）Next Steps 3「Monitor user feedback for capability
delegation needs」を満たす利用者要求も記録されていない。

---

## 1. ユースケースの洗い出し

### UC-1: self-healing が effect 違反を「権限の追加」で修復する

現行の修復経路は effect 違反に対して**宣言の拡大**を提案する:

| 経路 | 実装 | 挙動 |
|---|---|---|
| ルールベース修復 | `agent/strategies/rule_based_fix.py` → `_fix_effect_mismatch()`（`rule_based_fix_helpers.py`） | `effect_violation.required_effect` を対象 atom の `effects: [...]` に追記する。句が無ければ新規挿入する |
| ルールベース修復 | 同 → `_fix_effect_propagation()` | `effect_violation.missing_effects` を**呼び出し元**の `effects: [...]` に追記する |
| 潜在ベクトル修復（NLAE） | `agent/latent_decoder.py` の `EFFECT_ADD_INDEX`（`_add_effect()`） | 修復コンテキストの `effect_name`（既定は `"Write"`）を effects 句に追加する |
| intent drift 判定 | `agent/intent_tracker.py` `_compare_effects()` | effect 集合が**上位集合**になった変更を `strengthened`（intent impact スコア 0.8）に分類する。権限拡大としては扱わない |

つまり「AI が生成した atom が宣言外の副作用を持つ」場面で、現行ループは
*コードを権限に合わせる*のではなく *権限をコードに合わせる*方向にも修復できる。
これは実在するリスクであり、本調査で最も需要に近い候補である。

### UC-2: forge / generate による新規 atom 生成

- `forge_tasks/` の 40 タスク仕様（`*.json`）のうち effect を宣言するのは 3 タスク
  （`vstd_settlement.json` / `vstd_ownership.json` / `vstd_aviation_control.json`）のみで、内容は
  `Settlement` / `Ownership` / `RunwayAllocation` というドメインの temporal effect である。
  ファイル・ネットワーク等のリソース権限を扱う forge タスクは存在しない。
- 生成物のリソース権限の例は zero-human challenge の
  `examples/challenges/results/validate_json_file/output.mm` で、
  `effects: [SafeFileRead(path)]` + `requires: starts_with(path, "/tmp/") && not_contains(path, "..")`
  の組で閉じている。呼び出し地点ごとに権限を変える構造は現れない。
- `mumei` 側の `.mm` 資産でも同様で、`std/` + `examples/` + `tests/` の `effects: [...]` 宣言（156 箇所 / 67 ファイル）は
  1 atom あたり 1〜3 個の effect 名に収まり、同一 effect に対して**別々の制約を必要とする
  複数の受け渡し**が現れる `.mm` は存在しない（この形が Stage 1 の per-receiver 制限に当たる）。

### UC-3: サードパーティ部品の取り込み

`mumei-agent` は他者製の `.mm` パッケージを消費しない。`agent/mumei_client.py` が起動する
mumei サブコマンドは `verify` / `check` / `infer-effects` / `infer-contracts` / `build`（+ `--proof-cert`）
のみで、`mumei add` も registry 解決も呼ばない（`agent/` 配下に registry 参照ゼロ）。
`agent/publish.py` / `agent/forge.py` が行うのは自身が生成した `.mm` を mumei リポジトリへ
git commit する方向の操作である。したがって「他者が宣言した粗い effect を呼び出し側で狭める」
という典型的な capability 需要の**対象物が現時点で存在しない**。

### UC-4: 外部コード audit（foreign code）

`agent/audit.py` / `agent/strategies/foreign_code_strategy*.py` が扱う Rust / Go / Solidity /
TypeScript / Python のソースは mumei でコンパイルされず、effect containment 証明の対象にならない。
安全性の主張は audit レポート（既存 8 固定キー）と Z3 による Layer B 検査であり、
`.mm` の capability 値を渡す先が存在しない。trust surface の測定側でも
`std/` の trusted atom は 0、FFI 境界も 0 のまま維持されている（Priority 16 の scale 測定）。

### UC-5: harness 自身の外部ツール呼び出し

harness が実際に持つ強い権限は Python プロセス側にある: LLM API 呼び出し、
`agent/lean_bridge.py` の bridge `subprocess`、`agent/publish.py` の git 操作、
`agent/human_review.py` のエディタ起動、そして外部エージェント（Claude Code / Devin）が
`agent/mcp_server.py` 経由で渡す任意パス。MCP 側ではリポジトリ外パスを
`target_path.relative_to(repo)` で弾く封じ込めを Python レベルで行っている
（`agent/mcp_server.py` の forge target 検査）。
これらはいずれも `.mm` の外側であり、`grant` / narrowing / revocation を言語に入れても
harness プロセスの権限は 1 ビットも狭まらない。必要になるのはプロセス分離・OS サンドボックス・
`budget_policy` / `harness_contract` の運用側制約である。

### UC-6: 生成コードの実行時サンドボックス

`MumeiClient` は `run` も `--emit binary` の実行も持たない（`build` は成果物生成まで）。
生成 `.mm` は検証されるが実行されないため、「返ってきたら失効する」という
動的 revocation の対象となる実行時主体が存在しない。move ベース revocation（Stage 4）を
入れても、得られるのは実行されないコードに対するコンパイル時診断のみとなる。

---

## 2. Option A との比較（各ユースケースの判定）

判定の観点は「現行の parameterized effect system（effect 名 + `where` 制約 + `requires` による
暗黙の narrowing + effect containment / propagation）で表現できるか」である。

| UC | Option A で表現できるか | 根拠 |
|---|---|---|
| UC-1 | ✅ できる（言語機能としては既に十分） | 問題は言語の表現力ではなく**修復器の探索空間**にある。`grant` を追加しても、修復器が `grant` の制約を緩める修復を提案できてしまえば同じ穴が残る。必要なのは「修復として追加してよい effect / 緩めてよい制約」の静的ゲートで、これは Option A のまま agent 側に実装できる |
| UC-2 | ✅ できる | 生成 atom の権限は spec に静的に決まり、パス制約は `SafeFileRead(path)` + `requires` で Z3 検証される（`validate_json_file` が実例）。呼び出しごとに異なる権限を渡す必要が生じていない |
| UC-3 | ⚠️ 対象なし | third-party `.mm` を消費し始めた時点で、粗い effect（例: 無パラメータの `FileWrite`）を呼び出し側で狭める手段が Option A には無い。この欠落は `docs/CAPABILITY_SECURITY.md` の Weakness「No dynamic capability delegation」そのものだが、現時点では発火しない |
| UC-4 | ✅ 不適用 | foreign code は effect system の外。capability model は解にならない |
| UC-5 | ✅ 不適用 | harness プロセスの権限は言語機能の対象外 |
| UC-6 | ⚠️ 対象なし | 実行しないため失効の需要が発生しない。実行を始めるなら、Stage 4 の move ベース失効に加えて**実行時強制**（study §4.3 で非対象とされた領域）が必要になる |

Stage 1 の既知の制限（同一 effect に対する複数 capability パラメータの制約が全 perform に
連言で適用される、import 越しの capability 型パラメータ未対応）についても、それを踏む `.mm` が
`mumei` / `mumei-agent` の資産に存在しないため、Stage 2 に進む動機にはならない。

---

## 3. 需要が「実在しない」ことの根拠（否定判定の記録）

1. **委譲の相手が存在しない** — 呼び出しごとに権限を絞って渡す相手は「他者が書いた / AI が書いた
   別モジュールの atom」だが、mumei-agent は third-party `.mm` を消費せず（UC-3）、生成物は
   単一 atom またはモジュール内で閉じた呼び出しである（UC-2）。
2. **失効させる実行時主体が存在しない** — 生成コードは検証されるが実行されない（UC-6）。
3. **強い権限は言語の外にある** — 実際に最小権限化の価値があるのは harness プロセスの
   ファイル・ネットワーク・git 権限で、これは `.mm` の capability では届かない（UC-5）。
4. **最も近い実在リスク（UC-1）は静的ゲートで閉じる** — effect 宣言を拡大する修復は現に可能だが、
   その対策は「呼び出しごとの委譲」ではなく「修復器が追加してよい権限の allowlist」であり、
   Option A のまま agent 側に実装できる。`grant` を先に入れても、修復器が `grant` の制約を
   緩められる限り同じ穴が残るため、Stage 2 は対策にならない。
5. **観測シグナルがゼロ** — dogfood レポート群に effect 違反の記録はなく、利用者からの
   capability 委譲要求も記録されていない。

### 3.1 Option A のまま先に手当てすべき項目（提案。本 PR では実装しない）

Stage 2 より先に効果があり、かつコンパイラ拡張を要しない項目:

1. **修復器の effect allowlist ゲート** — `_fix_effect_mismatch()` / `_fix_effect_propagation()` /
   `latent_decoder._add_effect()` が追加できる effect を、spec（forge task / 抽出 spec）が宣言した
   集合に制限する。集合外の effect が要求された場合は修復せず、既存の
   `verification_violations` / `next_steps` で報告する。
2. **intent drift での権限拡大の扱い** — `_compare_effects()` が effect の上位集合化を
   `strengthened`（0.8）としている点を見直し、権限拡大は drift として扱う。
3. **harness プロセスの権限記述** — LLM / bridge / git / MCP の各外部呼び出しが要求する
   OS レベル権限を `docs/AGENT_HARNESS_SPEC.md` 側で明文化し、必要ならプロセス分離を検討する。

いずれも既存の契約キー（`harness_contract` / `intent_fidelity` / `artifact_paths` /
`budget_policy_fingerprint` / `lean_verified` と no-`.mm` の 8 固定キー）を変更せず、
新しい verdict 語彙も追加せずに実施できる。

---

## 4. 保留解除のトリガ（再調査条件）

以下のいずれかが観測された時点で本判定を再評価し、対応 Stage の着手を検討する。

| トリガ | 内容 | 対応 Stage |
|---|---|---|
| T1 | mumei-agent（または利用者）が third-party / 他エージェント製の `.mm` パッケージを消費し始め、粗い effect を呼び出し側で狭める必要が出る | Stage 2 → Stage 3 |
| T2 | 生成 `.mm` を harness が実行する（`mumei run` / 生成バイナリ実行）、かつ実行文脈が untrusted / multi-tenant である | Stage 4 + 実行時強制の再調査（study §4.3 非対象） |
| T3 | 1 つの atom が同一 effect に対して**異なる制約**の権限を複数受け取る `.mm` が実際に必要になる（Stage 1 の per-receiver 制限に当たる） | Stage 2（per-receiver 解決） |
| T4 | dogfood / 実運用のレポートに effect 違反と権限拡大修復の事例が現れる（§3.1 のゲートを入れても残る場合） | 再評価 |

---

## 5. 契約への影響

なし。本調査は `harness_contract` / `intent_fidelity` / `artifact_paths` /
`budget_policy_fingerprint` / `lean_verified` および no-`.mm` の 8 固定キーのいずれにも触れず、
新しい verdict 分類・別名 alias も追加しない。コンパイラ・エージェントのコード変更も含まない。

## 6. 関連ドキュメント

- mumei `docs/CAPABILITY_MODEL_STUDY.md` — タスク 1・2（非破壊な設計調査と互換性判定、Stage 分割案 §6）
- mumei `docs/CAPABILITY_SECURITY.md` — Weaknesses（dynamic delegation / revocation / first-class capability）と Next Steps 3
- mumei `docs/CROSS_PROJECT_ROADMAP.md` — Priority 15（タスク 1〜4 の canonical 定義）
- mumei `docs/ROADMAP.md` — P19（設計調査の local checkpoint）/ P29（Stage 1 実装）
- `agent/strategies/rule_based_fix_helpers.py` / `agent/latent_decoder.py` / `agent/intent_tracker.py` — UC-1 の実装
- `agent/mumei_client.py` / `agent/mcp_server.py` / `agent/lean_bridge.py` / `agent/publish.py` — UC-5 / UC-6 の実装
- `docs/AGENT_HARNESS_SPEC.md` — harness の外部化契約（UC-5 の記述先）
