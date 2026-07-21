# Target OSS no-LLM dogfooding audit — continuation 52 (batch 53)

Run: 2026-07-21T13:21:55.108887+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All 50 sampled files passed no-LLM verification.

## Tool-side fixes in this batch

- Go: skip `// run` compiler/driver test files (deliberate runtime behavior tests).
- Go: treat the integer parameter of functions named `Div` as a guaranteed non-zero divisor.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| grafana | `pkg/services/screenshot/cache_mock.go` | verified | |
| go | `src/cmd/compile/internal/syntax/testdata/issue31092.go` | verified | |
| prysm | `beacon-chain/core/peerdas/semi_supernode_test.go` | verified | |
| prysm | `api/server/structs/conversions_block_gloas_test.go` | verified | |
| grafana | `public/app/features/provisioning/GettingStarted/IconCircle.tsx` | verified | |
| uniswap-contracts | `script/cli/src/workflows/workflow_manager.rs` | verified | |
| grafana | `public/app/plugins/datasource/azuremonitor/i18next.config.ts` | verified | |
| influxdb | `influxdb3_load_generator/src/line_protocol_generator/tests.rs` | verified | |
| influxdb | `influxdb3_load_generator/src/commands/query.rs` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v4-core/types/PoolKey.sol` | verified | |
| go | `test/fixedbugs/bug008.go` | verified | |
| prysm | `beacon-chain/sync/validate_beacon_attestation.go` | verified | |
| prysm | `io/logs/logutil_test.go` | verified | |
| grafana | `public/app/features/alerting/unified/components/rule-editor/notificaton-preview/NotificationRoute.tsx` | verified | |
| influxdb | `influxdb3_catalog/src/format/records/retention.rs` | verified | |
| grafana | `public/app/plugins/datasource/cloudwatch/mocks/cloudwatch-logs-sql-test-data/commentOnlyQuery.ts` | verified | |
| go | `test/typeparam/issue49893.dir/b.go` | verified | |
| grafana | `public/app/features/dashboard-scene/scene/dashboard-filters-overview/useFiltersOverviewState.ts` | verified | |
| uniswap-contracts | `src/briefcase/protocols/mixed-quoter/libraries/V3CallbackValidation.sol` | verified | |
| grafana | `pkg/tests/api/alerting/api_provisioning_test.go` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/crosschain/arbitrum/CrossChainEnabledArbitrumL1.sol` | verified | |
| influxdb | `influxdb3_catalog/src/enterprise/format/records/login_identity_oauth.rs` | verified | |
| prysm | `beacon-chain/core/peerdas/reconstruction_helpers_test.go` | verified | |
| prysm | `beacon-chain/operations/attestations/kv/unaggregated.go` | verified | |
| uniswap-contracts | `src/briefcase/deployers/v4-hooks-public/PermissionedHooksDeployer.sol` | verified | |
| go | `test/fixedbugs/issue10486.go` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/token/ERC20/extensions/draft-IERC20Permit.sol` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v4-core/types/BeforeSwapDelta.sol` | verified | |
| go | `src/cmd/asm/internal/asm/expr_test.go` | verified | |
| influxdb | `influxdb3/src/commands/serve/jemalloc.rs` | verified | |
| go | `test/fixedbugs/issue22921.go` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/token/ERC777/presets/ERC777PresetFixedSupply.sol` | verified | |
| uniswap-contracts | `script/cli/src/workflows/default_workflow.rs` | verified | |
| grafana | `public/app/features/dashboard-scene/behaviors/DefaultControlsBehavior.ts` | verified | |
| prysm | `testing/spectest/shared/bellatrix/epoch_processing/participation_flag_updates.go` | verified | |
| go | `test/float_lit.go` | verified | |
| influxdb | `influxdb3_test_helpers/src/lib.rs` | verified | |
| prysm | `beacon-chain/rpc/eth/validator/handlers_test.go` | verified | |
| go | `src/image/geom.go` | verified | |
| go | `src/runtime/malloc_stubs.go` | verified | |
| uniswap-contracts | `script/cli/src/workflows/verify/mod.rs` | verified | |
| grafana | `pkg/util/debouncer/debouncer_test.go` | verified | |
| influxdb | `core/data_types/src/snapshot/table.rs` | verified | |
| grafana | `pkg/services/serviceaccounts/manager/service_test.go` | verified | |
| go | `test/fixedbugs/bug023.go` | verified | |
| prysm | `testing/spectest/mainnet/electra__operations__execution_layer_withdrawals_test.go` | verified | |
| influxdb | `influxdb3_commands/src/write/tests.rs` | verified | |
| prysm | `beacon-chain/db/kv/init_test.go` | verified | |
| influxdb | `influxdb3/tests/cli/system_tables.rs` | verified | |
| influxdb | `influxdb3_catalog/src/catalog/versions/v2/resource.rs` | verified | |
