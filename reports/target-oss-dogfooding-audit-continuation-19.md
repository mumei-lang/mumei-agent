# 外部 OSS ドッグフーディング監査継続レポート（第 19 弾 / batch 20）

- 実施日: 2026-07-24
- 監査ツール: mumei-agent (`develop`)
- LLM モデル: 未使用（`LLM_API_KEY=` no-LLM 決定論的スクリーニング）
- 出力ディレクトリ: `/home/ubuntu/repos/mumei-agent/reports/dogfood_continue_20/`

## 結果サマリー

- verified: 50 件
- refuted: 0 件
- unverifiable: 0 件

## 全ファイル一覧

| リポジトリ | ファイル | 言語 | ステータス |
|---|---|---|---|
| uniswap-contracts | `src/briefcase/protocols/v3-core/libraries/LiquidityMath.sol` | solidity | verified |
| uniswap-contracts | `src/briefcase/protocols/lib-external/solidity-lib/contracts/libraries/Babylonian.sol` | solidity | verified |
| influxdb | `core/service_grpc_flight/src/lib.rs` | rust | verified |
| uniswap-contracts | `src/briefcase/protocols/lib-external/openzeppelin-contracts/contracts/utils/introspection/IERC165.sol` | solidity | verified |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/Header/EditableQueryName.tsx` | typescript | verified |
| grafana | `packages/grafana-e2e-selectors/src/resolver.ts` | typescript | verified |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/governance/extensions/GovernorSettings.sol` | solidity | verified |
| grafana | `pkg/tests/apis/iam/user/user_service_integration_test.go` | go | verified |
| prysm | `testing/assertions/assertions_test.go` | go | verified |
| prysm | `testing/spectest/mainnet/electra__light_client__single_merkle_proof_test.go` | go | verified |
| uniswap-contracts | `src/briefcase/protocols/v4-periphery/hooks/permissionedPools/interfaces/IPermissionsAdapterFactory.sol` | solidity | verified |
| influxdb | `core/object_store_mock/src/lib.rs` | rust | verified |
| influxdb | `core/parquet_file/src/storage.rs` | rust | verified |
| influxdb | `influxdb3_catalog/src/format/records/restore.rs` | rust | verified |
| uniswap-contracts | `src/briefcase/protocols/v3-core/interfaces/callback/IUniswapV3MintCallback.sol` | solidity | verified |
| influxdb | `core/table_batch/src/lib.rs` | rust | verified |
| uniswap-contracts | `src/briefcase/deployers/v3-core/UniswapV3FactoryDeployer.sol` | solidity | verified |
| go | `src/cmd/internal/objabi/reloctype_string.go` | go | verified |
| grafana | `public/app/plugins/datasource/cloudwatch/aws_url.ts` | typescript | verified |
| go | `src/simd/archsimd/types_arm64.go` | go | verified |
| prysm | `validator/keymanager/remote-web3signer/internal/metrics.go` | go | verified |
| influxdb | `influxdb3_catalog/src/format/reader.rs` | rust | verified |
| go | `src/net/error_unix_test.go` | go | verified |
| grafana | `public/app/features/dashboard-scene/assistant/AssistantPopoverContext.tsx` | typescript | verified |
| prysm | `beacon-chain/rpc/eth/shared/errors_test.go` | go | verified |
| go | `src/runtime/pprof/vminfo_darwin.go` | go | verified |
| grafana | `pkg/services/authz/zanzana/server/reconciler/reconciler.go` | go | verified |
| influxdb | `object_store_utils/src/retryable_object_store/tests.rs` | rust | verified |
| influxdb | `core/influxdb2_client/src/api/setup.rs` | rust | verified |
| grafana | `pkg/services/ngalert/provisioning/limits.go` | go | verified |
| grafana | `public/app/plugins/datasource/cloudwatch/language/dynamic-labels/CompletionItemProvider.ts` | typescript | verified |
| prysm | `beacon-chain/blockchain/testing/log.go` | go | verified |
| grafana | `public/app/plugins/datasource/azuremonitor/components/MetricsQueryEditor/DimensionFields.tsx` | typescript | verified |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/preferences/v1alpha1/baseAPI.ts` | typescript | verified |
| prysm | `validator/db/filesystem/attester_protection.go` | go | verified |
| uniswap-contracts | `src/briefcase/protocols/v4-periphery/libraries/CurrencyRatioSortOrder.sol` | solidity | verified |
| go | `src/internal/poll/sendfile.go` | go | verified |
| prysm | `testing/spectest/minimal/electra__forkchoice__forkchoice_test.go` | go | verified |
| prysm | `testing/spectest/minimal/electra__epoch_processing__eth1_data_reset_test.go` | go | verified |
| go | `src/archive/zip/writer_test.go` | go | verified |
| influxdb | `core/influxdb_influxql_parser/src/visit_mut.rs` | rust | verified |
| uniswap-contracts | `script/cli/src/screens/types/select_or_enter.rs` | rust | verified |
| go | `src/runtime/cgo/openbsd.go` | go | verified |
| go | `src/cmd/go/internal/load/flag.go` | go | verified |
| prysm | `testing/spectest/mainnet/deneb__finality__finality_test.go` | go | verified |
| prysm | `testing/spectest/shared/deneb/epoch_processing/eth1_data_reset.go` | go | verified |
| influxdb | `influxdb3/tests/server/logs.rs` | rust | verified |
| go | `src/hash/maphash/example_bloom_test.go` | go | verified |
| go | `src/cmd/go/internal/verylongtest/go_test.go` | go | verified |
| uniswap-contracts | `src/briefcase/deployers/v4-hooks-public/WstETHRoutingHookDeployer.sol` | solidity | verified |