# Target OSS no-LLM dogfooding audit — continuation 42 (batch 43)

Run: 2026-07-21T10:34:10.905226+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All 50 sampled files passed no-LLM verification.

## Tool-side fixes in this batch

- Rust doc comments that state a parameter must be non-zero (``If `num_buckets` is zero, this will panic.``) are now parsed and the parameter is added to `guaranteed_nonzero`, suppressing modulo divide-by-zero false positives.
- Sampling now excludes ``.test.*``, ``.spec.*``, ``.stories.*``, and ``.story.*`` files to avoid test-only files in future batches.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| influxdb | `core/iox_query_influxql/src/aggregate/percentile.rs` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v4-hooks-public/aggregator-hooks/implementations/UniswapV3/interfaces/IUniswapV3Pool.sol` | verified | |
| influxdb | `core/data_types/src/partition_template.rs` | verified | |
| influxdb | `influxdb3_catalog/src/catalog/versions/v3/schema/cache.rs` | verified | |
| grafana | `packages/grafana-sql/src/components/visual-query-builder/SelectRow.tsx` | verified | |
| go | `src/cmd/internal/src/xpos.go` | verified | |
| go | `src/cmd/internal/pgo/serialize_test.go` | verified | |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/historian.alerting/v0alpha1/endpoints.gen.ts` | verified | |
| prysm | `testing/spectest/minimal/electra__operations__execution_layer_withdrawals_test.go` | verified | |
| influxdb | `influxdb3_processing_engine/src/virtualenv.rs` | verified | |
| prysm | `beacon-chain/execution/jsonrpc_error.go` | verified | |
| prysm | `beacon-chain/rpc/prysm/v1alpha1/beacon/init_test.go` | verified | |
| influxdb | `core/trace/src/ctx.rs` | verified | |
| prysm | `validator/db/migrate_test.go` | verified | |
| go | `test/fixedbugs/bug504.dir/c.go` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/MerkleProofWrapper.sol` | verified | |
| go | `src/text/template/multi_test.go` | verified | |
| go | `test/fixedbugs/issue33013.dir/b.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/swap-router-contracts/libraries/Constants.sol` | verified | |
| grafana | `pkg/registry/apis/provisioning/resources/repository_test.go` | verified | |
| grafana | `pkg/components/loki/lokigrpc/config.go` | verified | |
| prysm | `testing/spectest/mainnet/deneb__operations__attestation_test.go` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/crosschain/receivers.sol` | verified | |
| influxdb | `core/jemalloc_pprof_http/src/lib.rs` | verified | |
| grafana | `apps/example/pkg/apis/example/v0alpha1/example_codec_gen.go` | verified | |
| uniswap-contracts | `src/briefcase/deployers/v4-hooks-public/WETHHookDeployer.sol` | verified | |
| influxdb | `core/object_store_mock/src/interceptor.rs` | verified | |
| influxdb | `core/service_grpc_flight/src/planner.rs` | verified | |
| influxdb | `core/iox_query/src/frontend/reorg.rs` | verified | |
| grafana | `pkg/registry/apps/alerting/rules/recordingrule/authorize.go` | verified | |
| go | `src/internal/trace/traceviewer/fakep.go` | verified | |
| prysm | `beacon-chain/state/prometheus.go` | verified | |
| grafana | `public/app/features/explore/QueryLibrary/OpenQueryLibraryExposedComponent.tsx` | verified | |
| go | `src/syscall/zsyscall_linux_ppc64.go` | verified | |
| go | `src/crypto/cipher/common_test.go` | verified | |
| prysm | `validator/client/beacon-api/index.go` | verified | |
| grafana | `public/app/plugins/panel/traces/FiltersEditor.tsx` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v4-periphery/interfaces/IPositionManager.sol` | verified | |
| grafana | `pkg/services/sqlstore/migrations/accesscontrol/test/service_account_action_set_migration_test.go` | verified | |
| uniswap-contracts | `test/ReservesLensDeployer.t.sol` | verified | |
| prysm | `testing/spectest/mainnet/phase0__epoch_processing__rewards_and_penalties_test.go` | verified | |
| influxdb | `influxdb3_internal_api/src/lib.rs` | verified | |
| go | `test/fixedbugs/issue5002.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v4-core/libraries/UnsafeMath.sol` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/proxy/transparent/TransparentUpgradeableProxy.sol` | verified | |
| go | `src/runtime/testdata/testprog/stw_mexit.go` | verified | |
| prysm | `beacon-chain/sync/initial-sync/round_robin.go` | verified | |
| prysm | `validator/client/beacon-api/beacon_api_validator_client.go` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/governance/extensions/GovernorCountingSimple.sol` | verified | |
| grafana | `public/app/features/provisioning/GettingStarted/FeaturesList.tsx` | verified | |
