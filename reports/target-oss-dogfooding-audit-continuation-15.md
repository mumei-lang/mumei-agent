# 外部 OSS ドッグフーディング監査継続レポート（第 15 弾 / batch 16）

- 実施日: 2026-07-24
- 監査ツール: mumei-agent (`develop`, PR #405 マージ後 + batch 16 対応中)
- LLM モデル: 未使用（`LLM_API_KEY=` no-LLM 決定論的スクリーニング）
- 出力ディレクトリ: `/home/ubuntu/repos/mumei-agent/reports/dogfood_continue_16/`

## 結果サマリー

- verified: 50 件
- refuted: 0 件
- unverifiable: 0 件

## 修正対応済みのツール限界

- Go パッケージレベル ``map`` 変数の key access を安全と認識（`crypto/tls` の `aesgcmCiphers[cID]` 等）。
- Go 標準インターフェース実装メソッドの nil レシーバー誤検出を抑制:
  - `cipher.AEAD`: `Seal` / `Open` / `Overhead` / `NonceSize`
  - `hash.Hash`: `Sum` / `Size` / `BlockSize`
- Go の「インデックス = ``... % len(container)``」という剰余による境界内インデックスを認識（`getDummyRenderedURL` 等のテストヘルパー）。

## 全ファイル一覧

| リポジトリ | ファイル | 言語 | ステータス |
|---|---|---|---|
| prysm | `beacon-chain/execution/options.go` | go | verified |
| prysm | `encoding/ssz/query/ssz_info.go` | go | verified |
| prysm | `beacon-chain/cache/proposer_preferences.go` | go | verified |
| uniswap-contracts | `src/briefcase/protocols/lib-external/solmate/src/utils/Bytes32AddressLib.sol` | solidity | verified |
| go | `src/syscall/syscall_linux.go` | go | verified |
| go | `src/cmd/compile/internal/ssa/flagalloc.go` | go | verified |
| go | `src/crypto/tls/cipher_suites.go` | go | verified |
| influxdb | `core/object_store_mem_cache/src/cache_system/mod.rs` | rust | verified |
| prysm | `beacon-chain/slasher/service_test.go` | go | verified |
| go | `src/crypto/sha256/example_test.go` | go | verified |
| grafana | `public/app/features/variables/adapters.ts` | typescript | verified |
| prysm | `beacon-chain/state/state-native/custom-types/state_roots_test.go` | go | verified |
| influxdb | `core/iox_query/src/exec/gapfill/buffered_input.rs` | rust | verified |
| uniswap-contracts | `src/briefcase/protocols/v4-hooks-public/aggregator-hooks/implementations/FluidDexLite/interfaces/IFluidDexLiteResolver.sol` | solidity | verified |
| go | `src/runtime/os_linux_s390x.go` | go | verified |
| grafana | `pkg/services/ngalert/notifier/legacy_storage/inhibition_rules.go` | go | verified |
| influxdb | `core/iox_query/src/extension.rs` | rust | verified |
| uniswap-contracts | `src/briefcase/deployers/universal-router-2_0/UniversalRouter2_0Deployer.sol` | solidity | verified |
| grafana | `public/app/features/dashboard-scene/edit-pane/dashboard/helpers.ts` | typescript | verified |
| prysm | `beacon-chain/forkchoice/doubly-linked-tree/no_vote_test.go` | go | verified |
| grafana | `public/app/features/teams/TeamList.tsx` | typescript | verified |
| grafana | `pkg/tsdb/azuremonitor/standalone/datasource.go` | go | verified |
| grafana | `pkg/services/ngalert/notifier/legacy_storage/v1/inhibition_rules.go` | go | verified |
| influxdb | `core/influxdb2_client/src/models/authorization.rs` | rust | verified |
| uniswap-contracts | `src/briefcase/protocols/lib-external/openzeppelin-contracts/contracts/utils/cryptography/P256.sol` | solidity | verified |
| influxdb | `core/iox_query_influxql/src/plan/planner/source_field_names.rs` | rust | verified |
| uniswap-contracts | `src/briefcase/protocols/v3-core/interfaces/pool/IUniswapV3PoolImmutables.sol` | solidity | verified |
| grafana | `public/app/plugins/datasource/loki/querybuilder/components/QueryPatternsModal.test.tsx` | typescript | verified |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/GovernorCompatibilityBravoMock.sol` | solidity | verified |
| uniswap-contracts | `src/briefcase/protocols/permit2/interfaces/IEIP712.sol` | solidity | verified |
| go | `src/net/netcgo_on.go` | go | verified |
| grafana | `public/app/features/alerting/unified/components/alert-groups/AlertGroupFilter.tsx` | typescript | verified |
| grafana | `pkg/registry/apis/provisioning/webhooks/pullrequest/changes_test.go` | go | verified |
| influxdb | `influxdb3_catalog/src/log.rs` | rust | verified |
| go | `src/cmd/cgo/internal/test/issue24161e2/main.go` | go | verified |
| prysm | `testing/spectest/shared/capella/epoch_processing/historical_summaries_update.go` | go | verified |
| influxdb | `core/iox_query_influxql/src/window/elapsed.rs` | rust | verified |
| go | `src/crypto/internal/fips140/sha3/hashes.go` | go | verified |
| grafana | `public/app/features/variables/shared/formatVariable.ts` | typescript | verified |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/ERC1155URIStorageMock.sol` | solidity | verified |
| prysm | `beacon-chain/sync/rpc_beacon_blocks_by_root_test.go` | go | verified |
| prysm | `beacon-chain/rpc/service.go` | go | verified |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/Create2Impl.sol` | solidity | verified |
| prysm | `beacon-chain/core/epoch/sortable_indices_test.go` | go | verified |
| influxdb | `core/iox_query_influxql/src/window.rs` | rust | verified |
| go | `src/math/bits/bits_errors_bootstrap.go` | go | verified |
| influxdb | `core/client_util/src/lib.rs` | rust | verified |
| go | `src/cmd/compile/internal/base/print.go` | go | verified |
| uniswap-contracts | `src/briefcase/protocols/uniswapx/interfaces/IValidationCallback.sol` | solidity | verified |
| influxdb | `core/iox_v1_query_api/src/error.rs` | rust | verified |