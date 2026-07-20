# 外部 OSS ドッグフーディング監査継続レポート（第 17 弾 / batch 18）

- 実施日: 2026-07-24
- 監査ツール: mumei-agent (`develop`)
- LLM モデル: 未使用（`LLM_API_KEY=` no-LLM 決定論的スクリーニング）
- 出力ディレクトリ: `/home/ubuntu/repos/mumei-agent/reports/dogfood_continue_18/`

## 結果サマリー

- verified: 50 件
- refuted: 0 件
- unverifiable: 0 件

## 修正対応済みのツール限界

- `crypto/internal/fips140/sha3/sha3_amd64.go` の `write`/`read`/`sum` が `*Digest` の nil レシーバーとして誤検出された問題を修正。これらは `hash.Hash` 実装の内部ヘルパーで、常に非 nil の concrete value 経由で呼ばれる。

## 全ファイル一覧

| リポジトリ | ファイル | 言語 | ステータス |
|---|---|---|---|
| grafana | `pkg/tsdb/azuremonitor/schema.go` | go | verified |
| uniswap-contracts | `src/briefcase/protocols/uniswapx/interfaces/IProtocolFeeController.sol` | solidity | verified |
| influxdb | `core/tokio_watchdog/src/lib.rs` | rust | verified |
| prysm | `api/apiutil/log.go` | go | verified |
| uniswap-contracts | `script/cli/src/main.rs` | rust | verified |
| go | `src/internal/poll/export_test.go` | go | verified |
| grafana | `pkg/apis/datasource/v0alpha1/connection.go` | go | verified |
| prysm | `beacon-chain/rpc/prysm/v1alpha1/validator/proposer_gloas_test.go` | go | verified |
| uniswap-contracts | `src/briefcase/protocols/v3-core/libraries/TickMath.sol` | solidity | verified |
| grafana | `apps/provisioning/pkg/connection/github/factory.go` | go | verified |
| prysm | `validator/client/runner.go` | go | verified |
| grafana | `public/app/features/dashboard-scene/assistant/PanelAssistantHint.test.tsx` | typescript | verified |
| go | `src/crypto/ecdsa/boring.go` | go | verified |
| uniswap-contracts | `src/briefcase/protocols/view-quoter-v3/libraries/PoolAddress.sol` | solidity | verified |
| grafana | `public/app/features/dashboard-scene/scene/GoToSnapshotOriginButton.test.tsx` | typescript | verified |
| grafana | `public/app/features/alerting/unified/triage/scene/expressionBuilder.test.ts` | typescript | verified |
| prysm | `testing/spectest/mainnet/gloas__sanity__slots_test.go` | go | verified |
| uniswap-contracts | `src/briefcase/protocols/lib-external/webauthn-sol/lib/FreshCryptoLib/solidity/src/FCL_ecdsa.sol` | solidity | verified |
| grafana | `pkg/services/user/model.go` | go | verified |
| influxdb | `influxdb3_client/src/tests.rs` | rust | verified |
| uniswap-contracts | `src/briefcase/protocols/v4-hooks-public/aggregator-hooks/implementations/StableSwapNG/interfaces/ICurveStableSwapFactoryNG.sol` | solidity | verified |
| prysm | `testing/spectest/shared/electra/operations/voluntary_exit.go` | go | verified |
| grafana | `public/app/features/dashboard-scene/settings/enterprise-components/DashboardTemplateExtension.tsx` | typescript | verified |
| prysm | `network/external_ip_test.go` | go | verified |
| grafana | `pkg/registry/apps/wireset.go` | go | verified |
| prysm | `beacon-chain/state/stategen/replay_test.go` | go | verified |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/utils/Strings.sol` | solidity | verified |
| go | `src/cmd/compile/internal/ir/mini.go` | go | verified |
| go | `src/crypto/des/const.go` | go | verified |
| uniswap-contracts | `src/briefcase/protocols/permit2/interfaces/IDAIPermit.sol` | solidity | verified |
| prysm | `beacon-chain/sync/validate_data_column_test.go` | go | verified |
| grafana | `public/app/features/alerting/unified/utils/ruleStats.ts` | typescript | verified |
| go | `src/go/types/typeparam.go` | go | verified |
| go | `src/crypto/internal/fips140/sha3/sha3_amd64.go` | go | verified |
| go | `src/cmd/compile/internal/noder/dump.go` | go | verified |
| influxdb | `influxdb3_wal/src/object_store/tests.rs` | rust | verified |
| prysm | `beacon-chain/core/peerdas/info.go` | go | verified |
| influxdb | `core/partition/src/traits/mutable_batch.rs` | rust | verified |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/token/ERC721/extensions/ERC721URIStorage.sol` | solidity | verified |
| influxdb | `core/iox_query_params/src/lib.rs` | rust | verified |
| go | `src/cmd/go/internal/bug/bug.go` | go | verified |
| prysm | `beacon-chain/core/altair/epoch_precompute.go` | go | verified |
| influxdb | `core/influxdb2_client/src/models/ast/dialect.rs` | rust | verified |
| go | `src/simd/archsimd/_gen/simdgen/gen_simdTypes.go` | go | verified |
| influxdb | `core/influxdb_iox_client/src/client/flight/query.rs` | rust | verified |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/ERC20PermitMock.sol` | solidity | verified |
| go | `src/unicode/utf16/utf16_test.go` | go | verified |
| influxdb | `core/influxdb_influxql_parser/src/internal.rs` | rust | verified |
| influxdb | `core/iox_query/src/analyzer/mod.rs` | rust | verified |
| influxdb | `influxdb3_authz/src/authorizer/tests.rs` | rust | verified |