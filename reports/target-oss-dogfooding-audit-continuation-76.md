# Target OSS no-LLM dogfooding audit — continuation 76 (batch 77)

Run: 2026-07-21T22:03:08.564181+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification after fixing `go/src/runtime/map_benchmark_test.go`.

## Tool-side fixes in this batch

- Go: treat a parameter as non-zero when the function contains ``if x == 0 { return }`` before a division by that parameter.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| uniswap-contracts | `lib/oz-v4.7.0/contracts/governance/IGovernor.sol` | verified |  |
| go | `test/fixedbugs/bug377.go` | verified |  |
| grafana | `packages/grafana-ui/src/themes/GlobalStyles/jsonFormatter.ts` | verified |  |
| influxdb | `core/query_functions/src/sleep.rs` | verified |  |
| influxdb | `core/trace_exporters/src/export.rs` | verified |  |
| prysm | `testing/spectest/shared/gloas/epoch_processing/rewards_and_penalties.go` | verified |  |
| influxdb | `core/authz/src/permission.rs` | verified |  |
| prysm | `beacon-chain/rpc/eth/beacon/server.go` | verified |  |
| go | `src/net/http/cookiejar/example_test.go` | verified |  |
| grafana | `public/app/features/explore/hooks/useStateSync/synchronizer/fromURL.ts` | verified |  |
| influxdb | `core/iox_http/src/write/v1.rs` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/utils/introspection/ERC165Checker.sol` | verified |  |
| prysm | `beacon-chain/sync/rpc_execution_payload_envelopes_metrics.go` | verified |  |
| go | `src/internal/poll/iovec_solaris.go` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/ERC20PausableMock.sol` | verified |  |
| grafana | `pkg/registry/apis/query/client/instance_provider.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v4-periphery/interfaces/IEIP712_v4.sol` | verified |  |
| prysm | `beacon-chain/db/kv/archived_point_test.go` | verified |  |
| influxdb | `core/iox_query/src/physical_optimizer/chunk_extraction.rs` | verified |  |
| go | `src/internal/poll/copy_file_range_freebsd.go` | verified |  |
| prysm | `beacon-chain/das/availability_columns_test.go` | verified |  |
| prysm | `beacon-chain/rpc/prysm/v1alpha1/beacon/config_test.go` | verified |  |
| go | `test/fixedbugs/bug074.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/calibur/interfaces/IExecutionHook.sol` | verified |  |
| go | `src/runtime/map_benchmark_test.go` | verified |  |
| grafana | `public/app/features/provisioning/components/Folders/analytics/types.ts` | verified |  |
| grafana | `packages/grafana-api-clients/src/generator/generate.ts` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/MetricsQueryEditor/MetricNameField.tsx` | verified |  |
| influxdb | `core/authz/src/iox_authorizer.rs` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/utils/introspection/ERC165.sol` | verified |  |
| prysm | `beacon-chain/sync/pending_attestations_queue_test.go` | verified |  |
| grafana | `pkg/registry/apis/iam/resourcepermission/validate.go` | verified |  |
| prysm | `testing/spectest/shared/deneb/epoch_processing/registry_updates.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v4-core/libraries/SafeCast.sol` | verified |  |
| influxdb | `core/iox_query/src/statistics/mod.rs` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/uniswapx/v4/interfaces/IHook.sol` | verified |  |
| prysm | `tools/specs-checker/main.go` | verified |  |
| influxdb | `influxdb3_write/src/paths.rs` | verified |  |
| influxdb | `influxdb3_cache/src/distinct_cache/provider.rs` | verified |  |
| go | `test/fixedbugs/issue65362.go` | verified |  |
| grafana | `pkg/registry/apps/annotation/metrics.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/controller/connection_tester_mock.go` | verified |  |
| go | `test/closure7.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v4-core/types/BalanceDelta.sol` | verified |  |
| go | `test/fixedbugs/issue26116.go` | verified |  |
| influxdb | `influxdb3_catalog/src/serialize/versions/mod.rs` | verified |  |
| prysm | `testing/spectest/minimal/deneb__epoch_processing__randao_mixes_reset_test.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/uniswapx/interfaces/IReactorCallback.sol` | verified |  |
| go | `src/syscall/zerrors_linux_ppc64.go` | verified |  |
| grafana | `public/app/features/explore/spec/helper/interactions.ts` | verified |  |
