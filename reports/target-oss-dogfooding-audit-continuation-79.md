# Target OSS no-LLM dogfooding audit — continuation 79 (batch 80)

Run: 2026-07-21T22:26:39.971114+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| prysm | `api/client/event/event_stream_test.go` | verified |  |
| go | `src/syscall/ztypes_freebsd_arm64.go` | verified |  |
| prysm | `beacon-chain/sync/pending_blocks_queue_payload_envelopes_test.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v3-periphery/interfaces/external/IERC20PermitAllowed.sol` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v2-core/interfaces/IUniswapV2ERC20.sol` | verified |  |
| go | `test/fixedbugs/issue14651.go` | verified |  |
| uniswap-contracts | `script/cli/src/screens/shared/chain_id.rs` | verified |  |
| influxdb | `core/partition/src/template.rs` | verified |  |
| influxdb | `core/iox_http/src/write/v2.rs` | verified |  |
| prysm | `validator/client/grpc-api/grpc_client_manager.go` | verified |  |
| prysm | `cmd/config.go` | verified |  |
| grafana | `apps/preferences/pkg/apis/preferences/v1/zz_generated.openapi.go` | verified |  |
| grafana | `public/app/features/browse-dashboards/components/DeletedDashboardsLimitBanner.tsx` | verified |  |
| go | `src/net/cgo_android.go` | verified |  |
| go | `src/runtime/netpoll_kqueue.go` | verified |  |
| go | `test/fixedbugs/issue4326.go` | verified |  |
| grafana | `pkg/services/ngalert/evaluation_runner.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v4-hooks-public/aggregator-hooks/implementations/FluidDexLite/interfaces/IFluidDexLite.sol` | verified |  |
| influxdb | `core/tracker/src/lib.rs` | verified |  |
| go | `test/fixedbugs/issue8612.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v4-hooks-public/interfaces/IWstETH.sol` | verified |  |
| influxdb | `core/object_store_mem_cache/src/cache_system/test_utils.rs` | verified |  |
| influxdb | `core/jemalloc_stats/src/lib.rs` | verified |  |
| influxdb | `influxdb3_catalog/src/catalog/versions/v3/ops/config.rs` | verified |  |
| prysm | `beacon-chain/das/data_column_cache.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/metric_find_query_test.go` | verified |  |
| go | `src/internal/syscall/unix/renameat2_sysnum_linux.go` | verified |  |
| influxdb | `influxdb3_commands/src/write.rs` | verified |  |
| grafana | `packages/grafana-ui/src/components/StatsPicker/StatsPicker.tsx` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/swap-router-contracts/interfaces/IPeripheryPaymentsWithFeeExtended.sol` | verified |  |
| grafana | `public/app/features/expressions/components/SqlExpressions/hooks/useFunctionSignatures.ts` | verified |  |
| prysm | `beacon-chain/p2p/types/object_mapping.go` | verified |  |
| influxdb | `influxdb3/tests/server/client.rs` | verified |  |
| grafana | `pkg/tsdb/influxdb/simplejson/simplejson_test.go` | verified |  |
| go | `test/strength.go` | verified |  |
| prysm | `proto/migration/v1alpha1_to_v1_test.go` | verified |  |
| go | `src/text/tabwriter/tabwriter_test.go` | verified |  |
| prysm | `beacon-chain/sync/checkpoint/api_test.go` | verified |  |
| go | `src/go/types/typelists.go` | verified |  |
| prysm | `testing/spectest/shared/fulu/operations/withdrawal_request.go` | verified |  |
| grafana | `packages/grafana-sql/src/SQLVariableUtils.ts` | verified |  |
| influxdb | `influxdb3_catalog/src/catalog/versions/v1/resource.rs` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/token/ERC20/extensions/ERC20FlashMint.sol` | verified |  |
| prysm | `testing/spectest/mainnet/altair__operations__attester_slashing_test.go` | verified |  |
| grafana | `e2e-playwright/test-plugins/grafana-extensionstest-app/components/QueryModal/QueryModal.tsx` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/governance/extensions/GovernorVotesComp.sol` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v3-core/libraries/BitMath.sol` | verified |  |
| influxdb | `core/query_functions/src/group_by.rs` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v4-core/interfaces/IExttload.sol` | verified |  |
| grafana | `public/app/features/variables-management/api.ts` | verified |  |
