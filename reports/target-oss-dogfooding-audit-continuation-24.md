# Target OSS Dogfooding Audit - Continuation 24 (Batch 25)

## Summary

- **Date**: 2026-07-21
- **Method**: no-LLM batch sampling
- **Sample size**: 50 files
- **Result**: **50 verified / 0 refuted / 0 unverifiable**

## Tool improvement in this batch

### Solidity `sqrtRatio*X96` / `sqrtPriceX96` nonzero inference

`uniswap-contracts/src/briefcase/protocols/v3-periphery/libraries/LiquidityAmounts.sol` was refuted with `Solidity function getAmount0ForLiquidity can divide by sqrtRatioAX96 without a non-zero contract (Z3 counterexample: sqrtRatioAX96=0)`.

In Uniswap V3, `sqrtRatio*X96` values are fixed-point square-root prices and are guaranteed to be greater than `MIN_SQRT_RATIO` by construction (`TickMath.getSqrtRatioAtTick` never returns zero). This is a domain-level caller contract, similar to how `tickSpacing > 0` is guaranteed by `MIN_TICK_SPACING`.

`_solidity_guaranteed_nonzero_params` now recognizes parameters whose normalized name contains `sqrtratio` or `sqrtprice` and whose type is an integer as guaranteed nonzero. This suppresses the divide-by-zero false positive for V3 liquidity math and other fixed-point price libraries.

## Per-file results

| # | repo | file | language | status | notes |
|---|------|------|----------|--------|-------|
| 1 | go | src/internal/abi/funcpc.go | go | verified | |
| 2 | go | src/mime/encodedword.go | go | verified | |
| 3 | go | src/math/bits/example_math_test.go | go | verified | |
| 4 | go | src/crypto/aes/aes.go | go | verified | |
| 5 | go | src/crypto/internal/fips140/aes/aes.go | go | verified | |
| 6 | go | src/cmd/compile/internal/midway/analysis.go | go | verified | |
| 7 | go | src/compress/flate/deflatefast.go | go | verified | |
| 8 | go | src/internal/goexperiment/exp_simd_off.go | go | verified | |
| 9 | go | src/cmd/compile/internal/ir/html_test.go | go | verified | |
| 10 | go | src/runtime/crash_unix_test.go | go | verified | |
| 11 | prysm | api/grpc/grpcutils.go | go | verified | |
| 12 | prysm | beacon-chain/sync/rpc_blob_sidecars_by_root.go | go | verified | |
| 13 | prysm | testing/spectest/mainnet/altair__epoch_processing__effective_balance_updates_test.go | go | verified | |
| 14 | prysm | beacon-chain/core/peerdas/das_core.go | go | verified | |
| 15 | prysm | beacon-chain/state/stategen/errors.go | go | verified | |
| 16 | prysm | beacon-chain/sync/blobs_test.go | go | verified | |
| 17 | prysm | testing/endtoend/policies/policies.go | go | verified | |
| 18 | prysm | beacon-chain/sync/initial-sync/blocks_fetcher_payload_test.go | go | verified | |
| 19 | prysm | beacon-chain/rpc/prysm/node/server.go | go | verified | |
| 20 | prysm | beacon-chain/db/filesystem/layout_flat.go | go | verified | |
| 21 | grafana | scripts/cli/env-util.ts | typescript | verified | |
| 22 | grafana | public/app/features/correlations/Forms/types.ts | typescript | verified | |
| 23 | grafana | public/app/features/dashboard/components/Inspector/hooks.ts | typescript | verified | |
| 24 | grafana | public/app/features/dashboard-scene/mutation-api/commands/types.ts | typescript | verified | |
| 25 | grafana | packages/grafana-data/src/transformations/transformers/groupToNestedTable.ts | typescript | verified | |
| 26 | grafana | packages/grafana-alerting/rollup.config.ts | typescript | verified | |
| 27 | grafana | e2e-playwright/dashboard-new-layouts/dashboard-duplicate-panel.spec.ts | typescript | verified | |
| 28 | grafana | packages/grafana-ui/src/components/PanelChrome/index.ts | typescript | verified | |
| 29 | grafana | public/app/core/components/NestedFolderPicker/useFoldersQueryAppPlatform.ts | typescript | verified | |
| 30 | grafana | public/app/features/plugins/sandbox/types.ts | typescript | verified | |
| 31 | influxdb | influxdb3_system_tables/src/last_caches.rs | rust | verified | |
| 32 | influxdb | influxdb3_catalog/src/catalog/versions/v2/update/enterprise/tests.rs | rust | verified | |
| 33 | influxdb | core/influxdb2_client/src/api/query.rs | rust | verified | |
| 34 | influxdb | influxdb3_load_generator/src/specification.rs | rust | verified | |
| 35 | influxdb | core/flightsql/src/sql_info/meta.rs | rust | verified | |
| 36 | influxdb | influxdb3_catalog/src/format/records/feature_level.rs | rust | verified | |
| 37 | influxdb | core/object_store_mem_cache/src/cache_system/s3_fifo_cache/fifo.rs | rust | verified | |
| 38 | influxdb | core/iox_http/src/write/single_tenant/auth.rs | rust | verified | |
| 39 | influxdb | core/influxdb_influxql_parser/src/string.rs | rust | verified | |
| 40 | influxdb | influxdb3_wal/src/serialize/tests.rs | rust | verified | |
| 41 | uniswap-contracts | src/briefcase/deployers/v3-periphery/UniswapInterfaceMulticallDeployer.sol | solidity | verified | |
| 42 | uniswap-contracts | src/briefcase/protocols/v4-periphery/interfaces/IV4Router.sol | solidity | verified | |
| 43 | uniswap-contracts | src/briefcase/protocols/swap-router-contracts/interfaces/IQuoter.sol | solidity | verified | |
| 44 | uniswap-contracts | lib/oz-v4.7.0/contracts/mocks/DummyImplementation.sol | solidity | verified | |
| 45 | uniswap-contracts | lib/oz-v3.4-solc-0.7/contracts/drafts/ERC20Permit.sol | solidity | verified | |
| 46 | uniswap-contracts | lib/oz-v4.7.0/contracts/crosschain/CrossChainEnabled.sol | solidity | verified | |
| 47 | uniswap-contracts | lib/oz-v4.7.0/contracts/interfaces/IERC777.sol | solidity | verified | |
| 48 | uniswap-contracts | lib/oz-v4.7.0/contracts/crosschain/amb/LibAMB.sol | solidity | verified | |
| 49 | uniswap-contracts | src/briefcase/protocols/v3-periphery/libraries/LiquidityAmounts.sol | solidity | verified | |
| 50 | uniswap-contracts | lib/oz-v4.7.0/contracts/token/ERC20/extensions/ERC20Wrapper.sol | solidity | verified | |

## Notes

All 50 sampled files passed no-LLM verification. No OSS-side issues were identified in this batch.
