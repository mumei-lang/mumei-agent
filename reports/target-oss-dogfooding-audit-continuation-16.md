# 外部 OSS ドッグフーディング監査継続レポート（第 16 弾 / batch 17）

- 実施日: 2026-07-24
- 監査ツール: mumei-agent (`develop`)
- LLM モデル: 未使用（`LLM_API_KEY=` no-LLM 決定論的スクリーニング）
- 出力ディレクトリ: `/home/ubuntu/repos/mumei-agent/reports/dogfood_continue_17/`

## 結果サマリー

- verified: 48 件
- refuted: 2 件
- unverifiable: 0 件

## 修正対応済みのツール限界

- Go トップレベル ``const`` の整数リテラルを `known_constants` として認識。定数同士の加算で overflow false positive が出なくなった（`crypto/cipher/gcm.go` の `gcmStandardNonceSize + gcmTagSize` 等）。

## 残存 refuted（ツール限界）

- `uniswap-contracts/lib/oz-v4.7.0/contracts/finance/PaymentSplitter.sol`
  - `payee(uint256 index)` で `_payees[index]` にアクセス。Solidity 0.8 では OOB で自動 revert するため実用上は安全だが、mumei-agent は external 入力に対する OOB を検出している。
  - `_pendingPayment` で `_totalShares` による除算。`_addPayee` の `shares_ > 0` と constructor の `payees.length > 0` から `_totalShares > 0` は不変条件だが、ツールは state 変数の不変条件を追跡していない。
- `prysm/beacon-chain/execution/payload_body.go` (`requestBodiesByRange`)
  - `for i := range result` 内で `req.hbns[i]` にアクセス。`len(result) == req.count` と `len(req.hbns) == req.count` は `computeRanges` で保証されているが、関数間の slice 長等式を追跡する dataflow が未対応。

## 全ファイル一覧

| リポジトリ | ファイル | 言語 | ステータス |
|---|---|---|---|
| influxdb | `influxdb3_authz/src/role/role_permissions.rs` | rust | verified |
| influxdb | `core/influxdb2_client/examples/query.rs` | rust | verified |
| uniswap-contracts | `src/briefcase/protocols/v4-hooks-public/aggregator-hooks/interfaces/IAggregatorHook.sol` | solidity | verified |
| grafana | `apps/provisioning/pkg/controller/labels.go` | go | verified |
| uniswap-contracts | `src/briefcase/deployers/v4-periphery/PositionDescriptorDeployer.sol` | solidity | verified |
| influxdb | `influxdb3_catalog/src/catalog/versions/v3/transaction/tests.rs` | rust | verified |
| go | `src/net/sockopt_plan9.go` | go | verified |
| go | `src/cmd/go/internal/mmap/mmap_other.go` | go | verified |
| grafana | `pkg/storage/unified/sql/sqltemplate/into.go` | go | verified |
| uniswap-contracts | `src/briefcase/deployers/DeployerHelper.sol` | solidity | verified |
| influxdb | `core/table_batch/src/builder/column_writer/mod.rs` | rust | verified |
| go | `src/crypto/internal/fips140/rsa/cast.go` | go | verified |
| prysm | `beacon-chain/monitor/process_attestation.go` | go | verified |
| uniswap-contracts | `src/briefcase/protocols/lib-external/oz-v3.4-solc-0.7/contracts/token/ERC721/IERC721.sol` | solidity | verified |
| go | `src/internal/cpu/cpu_windows_test.go` | go | verified |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/finance/PaymentSplitter.sol` | solidity | refuted |
| prysm | `beacon-chain/sync/backfill/pool_test.go` | go | verified |
| go | `src/crypto/cipher/gcm.go` | go | verified |
| grafana | `public/app/features/alerting/unified/components/notification-policies/EditNotificationPolicyForm.tsx` | typescript | verified |
| go | `src/internal/fuzz/worker_test.go` | go | verified |
| grafana | `public/app/features/provisioning/components/utils/path.test.ts` | typescript | verified |
| influxdb | `influxdb3_catalog/src/catalog/versions/v3/usage.rs` | rust | verified |
| prysm | `testing/mock/beacon_validator_server_mock.go` | go | verified |
| prysm | `testing/spectest/mainnet/phase0__epoch_processing__participation_record_updates_test.go` | go | verified |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/proxy/ERC1967/ERC1967Proxy.sol` | solidity | verified |
| go | `src/math/cmplx/abs.go` | go | verified |
| go | `src/runtime/export_arm_test.go` | go | verified |
| prysm | `testing/spectest/minimal/bellatrix__sanity__slots_test.go` | go | verified |
| prysm | `runtime/debug/debug.go` | go | verified |
| go | `src/io/fs/readfile_test.go` | go | verified |
| influxdb | `core/influxdb2_client/src/models/label.rs` | rust | verified |
| go | `src/cmd/test2json/signal_unix.go` | go | verified |
| grafana | `public/app/core/components/DynamicImports/SafeDynamicImport.tsx` | typescript | verified |
| prysm | `beacon-chain/core/blocks/header.go` | go | verified |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/AccessControlCrossChainMock.sol` | solidity | verified |
| influxdb | `core/influxdb2_client/src/models/ast/identifier.rs` | rust | verified |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/utils/Timers.sol` | solidity | verified |
| grafana | `pkg/components/imguploader/s3uploader_test.go` | go | verified |
| prysm | `beacon-chain/p2p/peers/peers_test.go` | go | verified |
| influxdb | `core/iox_query/src/statistics/aggregate_per_chunk.rs` | rust | verified |
| grafana | `pkg/tests/apis/provisioning/fieldselector_test.go` | go | verified |
| grafana | `pkg/services/cloudmigration/api/api.go` | go | verified |
| prysm | `beacon-chain/execution/payload_body.go` | go | refuted |
| grafana | `public/app/plugins/datasource/influxdb/fsql/types.ts` | typescript | verified |
| influxdb | `influxdb3_authz/src/authorizer.rs` | rust | verified |
| grafana | `public/app/features/alerting/unified/components/contact-points/mocks/vanillaAlertmanagerServer.ts` | typescript | verified |
| uniswap-contracts | `src/briefcase/protocols/v3-periphery/libraries/TokenRatioSortOrder.sol` | solidity | verified |
| prysm | `testing/spectest/mainnet/gloas__epoch_processing__rewards_and_penalties_test.go` | go | verified |
| influxdb | `core/jemalloc_stats/src/monitor.rs` | rust | verified |
| uniswap-contracts | `src/briefcase/protocols/v4-periphery/libraries/HexStrings.sol` | solidity | verified |