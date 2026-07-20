# 外部 OSS ドッグフーディング監査継続レポート（第 18 弾 / batch 19）

- 実施日: 2026-07-24
- 監査ツール: mumei-agent (`develop`)
- LLM モデル: 未使用（`LLM_API_KEY=` no-LLM 決定論的スクリーニング）
- 出力ディレクトリ: `/home/ubuntu/repos/mumei-agent/reports/dogfood_continue_19/`

## 結果サマリー

- verified: 50 件
- refuted: 0 件
- unverifiable: 0 件

## 修正対応済みのツール限界

- Solidity 0.8 の default 算術チェックを尊重。`pragma solidity ^0.8.0` かつ関数内に `unchecked` ブロックがない場合、`a + b` の overflow 誤検出を抑制（`Votes.sol` の `_add` 等）。
- Go の `goexperiment` ビルドタグ付き実験ファイル（`simd/archsimd/internal/simd_test/simulation_helpers_test.go`）を no-LLM 監査対象からスキップ。これらは通常のビルドに含まれず、`mumei verify` の未対応機能でスタックオーバーフローするため。

## 全ファイル一覧

| リポジトリ | ファイル | 言語 | ステータス |
|---|---|---|---|
| uniswap-contracts | `lib/oz-v4.7.0/contracts/access/AccessControlCrossChain.sol` | solidity | verified |
| grafana | `public/app/features/variables/adhoc/urlParser.test.ts` | typescript | verified |
| prysm | `beacon-chain/operations/blstoexec/doc.go` | go | verified |
| uniswap-contracts | `script/cli/src/screens/screen_manager.rs` | rust | verified |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v27.go` | go | verified |
| influxdb | `core/catalog_cache/src/api/list/mod.rs` | rust | verified |
| influxdb | `core/influxdb2_client/src/models/ast/dict_item.rs` | rust | verified |
| grafana | `pkg/tsdb/grafana-postgresql-datasource/proxy.go` | go | verified |
| grafana | `public/app/features/plugins/extensions/registry/useRegistrySlice.test.tsx` | typescript | verified |
| prysm | `validator/client/propose.go` | go | verified |
| grafana | `public/app/plugins/datasource/cloudwatch/components/QueryEditor/MetricsQueryEditor/SQLBuilderEditor/SQLFilter.tsx` | typescript | verified |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/utils/introspection/ERC1820Implementer.sol` | solidity | verified |
| prysm | `cmd/validator/accounts/wallet_utils_test.go` | go | verified |
| go | `src/simd/archsimd/internal/simd_test/simulation_helpers_test.go` | go | verified |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/ERC1155PausableMock.sol` | solidity | verified |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/ERC165StorageMock.sol` | solidity | verified |
| influxdb | `influxdb3_catalog/src/serialize/versions/v1/tests.rs` | rust | verified |
| prysm | `testing/bls/sign_test.yaml.go` | go | verified |
| prysm | `beacon-chain/db/kv/state_summary_cache.go` | go | verified |
| influxdb | `core/object_store_mem_cache/src/object_store_helpers.rs` | rust | verified |
| prysm | `beacon-chain/core/requests/withdrawals.go` | go | verified |
| go | `src/runtime/pprof/proto_test.go` | go | verified |
| uniswap-contracts | `src/briefcase/protocols/v3-periphery/interfaces/IQuoter.sol` | solidity | verified |
| go | `src/os/executable_path.go` | go | verified |
| grafana | `pkg/services/navtree/models_test.go` | go | verified |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelStylesSection.test.tsx` | typescript | verified |
| uniswap-contracts | `src/briefcase/protocols/lib-external/oz-v3.4-solc-0.7/contracts/token/ERC721/IERC721Enumerable.sol` | solidity | verified |
| go | `src/cmd/go/internal/imports/scan.go` | go | verified |
| go | `src/crypto/tls/key_schedule_test.go` | go | verified |
| prysm | `beacon-chain/core/blocks/eth1_data_test.go` | go | verified |
| go | `src/crypto/internal/fips140test/acvp_fips140v1.0_test.go` | go | verified |
| influxdb | `influxdb3_internal_api/src/query_executor.rs` | rust | verified |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/finance/VestingWallet.sol` | solidity | verified |
| prysm | `testing/spectest/mainnet/phase0__epoch_processing__registry_updates_test.go` | go | verified |
| grafana | `public/app/features/provisioning/utils/repositoryTypes.test.ts` | typescript | verified |
| influxdb | `influxdb3_process/src/lib.rs` | rust | verified |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/governance/utils/Votes.sol` | solidity | verified |
| influxdb | `influxdb3_catalog/src/format/records/feature_level/tests.rs` | rust | verified |
| influxdb | `influxdb3_catalog/src/format/records/types.rs` | rust | verified |
| prysm | `beacon-chain/sync/data_columns_reconstruct_test.go` | go | verified |
| go | `src/cmd/internal/osinfo/doc.go` | go | verified |
| grafana | `public/app/plugins/datasource/influxdb/influxql_metadata_query.test.ts` | typescript | verified |
| go | `src/os/user/lookup_plan9.go` | go | verified |
| prysm | `internal/logrusadapter/adapter_test.go` | go | verified |
| influxdb | `core/influxdb_iox_client/src/client/health.rs` | rust | verified |
| influxdb | `influxdb3_id/src/serialize.rs` | rust | verified |
| go | `src/crypto/tls/fipsonly/fipsonly.go` | go | verified |
| grafana | `pkg/services/live/pushurl/values.go` | go | verified |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/ECDSAMock.sol` | solidity | verified |
| go | `src/crypto/internal/fips140/sha512/sha512block.go` | go | verified |