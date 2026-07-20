# 外部 OSS ドッグフーディング監査継続レポート（第 20 弾 / batch 21）

- 実施日: 2026-07-24
- 監査ツール: mumei-agent (`develop`)
- LLM モデル: 未使用（`LLM_API_KEY=` no-LLM 決定論的スクリーニング）
- 出力ディレクトリ: `/home/ubuntu/repos/mumei-agent/reports/dogfood_continue_21/`

## 結果サマリー

- verified: 50 件
- refuted: 0 件
- unverifiable: 0 件

## 修正対応済みのツール限界

- Go の `for i := range domain` ループ変数や、`parallel := make([]T, len(domain))` で同じ長さに確保されたローカルスライスへのインデックスアクセス `parallel[i]` / `domain[i]` を境界内と認識。`prysm/testing/endtoend/evaluators/node.go` の `compareChainHeads` で `headEpochs[i]` 等の誤検出を抑制。

## 全ファイル一覧

| リポジトリ | ファイル | 言語 | ステータス |
|---|---|---|---|
| grafana | `public/app/features/explore/RecentQueries/RecentQueriesDescription.test.tsx` | typescript | verified |
| prysm | `beacon-chain/core/helpers/randao.go` | go | verified |
| uniswap-contracts | `src/briefcase/protocols/swap-router-contracts/interfaces/ISwapRouter02.sol` | solidity | verified |
| grafana | `public/app/features/provisioning/Shared/RepoIcon.tsx` | typescript | verified |
| grafana | `pkg/registry/apis/secret/encryption/manager/oss_dek_cache_test.go` | go | verified |
| prysm | `consensus-types/blocks/testing/factory.go` | go | verified |
| influxdb | `influxdb3_catalog/src/repository/tests.rs` | rust | verified |
| prysm | `testing/spectest/shared/deneb/epoch_processing/historical_summaries_update.go` | go | verified |
| prysm | `beacon-chain/state/fieldtrie/helpers_test.go` | go | verified |
| go | `src/os/file_posix.go` | go | verified |
| grafana | `apps/dashvalidator/pkg/validator/prometheus/validator_test.go` | go | verified |
| influxdb | `core/metric/src/counter.rs` | rust | verified |
| grafana | `pkg/expr/ml.go` | go | verified |
| influxdb | `core/client_util/src/namespace_translation.rs` | rust | verified |
| go | `src/strconv/quote_test.go` | go | verified |
| uniswap-contracts | `src/briefcase/protocols/v3-periphery/libraries/SqrtPriceMathPartial.sol` | solidity | verified |
| prysm | `runtime/maxprocs/maxprocs.go` | go | verified |
| prysm | `beacon-chain/core/epoch/precompute/attestation_test.go` | go | verified |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/access/Ownable.sol` | solidity | verified |
| uniswap-contracts | `script/cli/src/screens/shared/skip_verification.rs` | rust | verified |
| go | `src/internal/runtime/cgobench/bench_test.go` | go | verified |
| influxdb | `core/generated_types/build.rs` | rust | verified |
| go | `src/net/tcpsock_unix.go` | go | verified |
| go | `src/cmd/compile/internal/base/mapfile_read.go` | go | verified |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/GovernorWithParamsMock.sol` | solidity | verified |
| uniswap-contracts | `src/briefcase/protocols/calibur/libraries/ModeDecoder.sol` | solidity | verified |
| influxdb | `influxdb3_catalog/src/format/feature_level/tests.rs` | rust | verified |
| go | `src/runtime/mgcscavenge.go` | go | verified |
| grafana | `packages/grafana-test-utils/src/handlers/apis/dashboard.grafana.app/v0alpha1/handlers.ts` | typescript | verified |
| influxdb | `core/iox_query/src/physical_optimizer/cached_parquet_data.rs` | rust | verified |
| grafana | `pkg/registry/apis/provisioning/controller/webhook.go` | go | verified |
| grafana | `public/app/features/alerting/unified/components/rule-editor/alert-rule-form/simplifiedRouting/SimplifiedRouting.tsx` | typescript | verified |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/interfaces/IERC3156FlashLender.sol` | solidity | verified |
| grafana | `public/app/features/dashboard-scene/settings/variables/editors/QueryVariableEditor/VariableOptionsSpreadsheet/VariableOptionsSpreadsheet.tsx` | typescript | verified |
| uniswap-contracts | `src/briefcase/deployers/v2-periphery/UniswapV2Router01Deployer.sol` | solidity | verified |
| influxdb | `influxdb3_clap_blocks/src/disk_size.rs` | rust | verified |
| prysm | `testing/util/logging_test.go` | go | verified |
| uniswap-contracts | `script/cli/src/screens/shared/error_screen.rs` | rust | verified |
| influxdb | `core/influxdb_influxql_parser/src/visit.rs` | rust | verified |
| go | `src/internal/abi/abi_ppc64x.go` | go | verified |
| go | `src/internal/runtime/maps/memhash_noaes.go` | go | verified |
| prysm | `beacon-chain/forkchoice/doubly-linked-tree/unrealized_justification.go` | go | verified |
| go | `src/net/tcpsock_test.go` | go | verified |
| influxdb | `core/influxdb2_client/src/models/data_point.rs` | rust | verified |
| prysm | `testing/spectest/mainnet/gloas__epoch_processing__pending_consolidations_test.go` | go | verified |
| uniswap-contracts | `src/briefcase/protocols/calibur/libraries/BatchedCallLib.sol` | solidity | verified |
| go | `src/cmd/compile/internal/noder/quirks.go` | go | verified |
| prysm | `testing/endtoend/evaluators/node.go` | go | verified |
| influxdb | `core/trogging/src/cli.rs` | rust | verified |
| grafana | `public/app/features/dashboard-scene/settings/version-history/VersionHistoryButtons.test.tsx` | typescript | verified |