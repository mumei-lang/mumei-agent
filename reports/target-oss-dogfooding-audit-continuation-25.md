# Target OSS Dogfooding Audit - Continuation 25 (Batch 26)

## Summary

- **Date**: 2026-07-21
- **Method**: no-LLM batch sampling
- **Sample size**: 50 files
- **Result**: **50 verified / 0 refuted / 0 unverifiable**

## Tool improvement in this batch

### Go `sort.Interface` implementer nil-receiver false positives

`go/src/sort/sort_test.go` was refuted because helper types (`*testingData`, `*nonDeterministicTestingData`, `*adversaryTestingData`) implement `sort.Interface` with `Len`/`Less`/`Swap`, and the safety checker flagged receiver nil dereferences in these methods.

The `sort` package always invokes these methods on a non-nil value, so nil-receiver counterexamples are caller-contract noise.

`_go_sort_interface_receiver_types(functions)` now detects receiver types that define all three `sort.Interface` methods and `_detect_go_safety_issues` suppresses receiver nil-deref issues for `Len`, `Less`, and `Swap` on those receivers.

## Per-file results

| # | repo | file | language | status | notes |
|---|------|------|----------|--------|-------|
| 1 | go | src/image/color/color_test.go | go | verified | |
| 2 | go | src/cmd/go/internal/web/url.go | go | verified | |
| 3 | go | src/internal/cgrouptest/cgrouptest_linux.go | go | verified | |
| 4 | go | src/runtime/mgcscavenge_test.go | go | verified | |
| 5 | go | src/path/filepath/match_test.go | go | verified | |
| 6 | go | src/internal/syscall/windows/mksyscall.go | go | verified | |
| 7 | go | src/sort/sort_test.go | go | verified | |
| 8 | go | src/runtime/mmap.go | go | verified | |
| 9 | go | src/cmd/compile/main.go | go | verified | |
| 10 | go | src/simd/archsimd/internal/simd_test/binary_amd64_test.go | go | verified | |
| 11 | prysm | testing/spectest/shared/gloas/epoch_processing/slashings_reset.go | go | verified | |
| 12 | prysm | beacon-chain/p2p/peers/scorers/peer_status_test.go | go | verified | |
| 13 | prysm | validator/keymanager/remote-web3signer/metrics.go | go | verified | |
| 14 | prysm | api/client/transport.go | go | verified | |
| 15 | prysm | api/server/structs/conversions_blob.go | go | verified | |
| 16 | prysm | api/client/builder/client_gloas.go | go | verified | |
| 17 | prysm | beacon-chain/execution/init_test.go | go | verified | |
| 18 | prysm | monitoring/journald/journald_linux.go | go | verified | |
| 19 | prysm | testing/spectest/mainnet/electra__operations__deposit_test.go | go | verified | |
| 20 | prysm | testing/spectest/mainnet/fulu__operations__deposit_requests_test.go | go | verified | |
| 21 | grafana | packages/grafana-data/src/transformations/transformers/histogram.ts | typescript | verified | |
| 22 | grafana | public/app/features/explore/TraceView/components/CriticalPath/testCases/test7.ts | typescript | verified | |
| 23 | grafana | public/app/core/services/journey/journeyRegistry.ts | typescript | verified | |
| 24 | grafana | packages/grafana-data/src/transformations/matchers/valueMatchers/equalMatchers.test.ts | typescript | verified | |
| 25 | grafana | public/app/features/dashboard/dashgrid/types.ts | typescript | verified | |
| 26 | grafana | public/app/plugins/datasource/loki/module.ts | typescript | verified | |
| 27 | grafana | public/app/plugins/panel/gauge/migrations.test.ts | typescript | verified | |
| 28 | grafana | packages/grafana-api-clients/src/clients/rtkq/logsdrilldown/v1alpha1/index.ts | typescript | verified | |
| 29 | grafana | public/app/plugins/datasource/cloudwatch/language/cloudwatch-sql/completion/statementPosition.test.ts | typescript | verified | |
| 30 | grafana | public/app/features/panel/state/util.ts | typescript | verified | |
| 31 | influxdb | core/arrow_util/src/util.rs | rust | verified | |
| 32 | influxdb | influxdb3_write/src/write_buffer/metrics/tests.rs | rust | verified | |
| 33 | influxdb | influxdb3_catalog/src/format/records/query_group.rs | rust | verified | |
| 34 | influxdb | core/flightsql/src/xdbc_type_info/mod.rs | rust | verified | |
| 35 | influxdb | core/mutable_batch/tests/writer_drop.rs | rust | verified | |
| 36 | influxdb | influxdb3_write/src/write_buffer/mod.rs | rust | verified | |
| 37 | influxdb | core/influxdb_influxql_parser/src/lib.rs | rust | verified | |
| 38 | influxdb | core/service_grpc_flight/src/observer.rs | rust | verified | |
| 39 | influxdb | core/test_helpers/src/timeout.rs | rust | verified | |
| 40 | influxdb | core/arrow_util/src/dictionary.rs | rust | verified | |
| 41 | uniswap-contracts | lib/oz-v4.7.0/contracts/governance/extensions/IGovernorTimelock.sol | solidity | verified | |
| 42 | uniswap-contracts | lib/oz-v4.7.0/contracts/mocks/SignatureCheckerMock.sol | solidity | verified | |
| 43 | uniswap-contracts | lib/oz-v4.7.0/contracts/mocks/ERC20Mock.sol | solidity | verified | |
| 44 | uniswap-contracts | src/briefcase/protocols/permit2/libraries/PermitHash.sol | solidity | verified | |
| 45 | uniswap-contracts | src/briefcase/protocols/v4-hooks-public/utils/HookMinerCreate3.sol | solidity | verified | |
| 46 | uniswap-contracts | src/briefcase/protocols/swap-router-contracts/interfaces/IQuoterV2.sol | solidity | verified | |
| 47 | uniswap-contracts | src/briefcase/protocols/mixed-quoter/interfaces/IMixedRouteQuoterV2.sol | solidity | verified | |
| 48 | uniswap-contracts | lib/oz-v4.7.0/contracts/utils/introspection/ERC165Storage.sol | solidity | verified | |
| 49 | uniswap-contracts | lib/oz-v3.4-solc-0.7/contracts/token/ERC20/ERC20.sol | solidity | verified | |
| 50 | uniswap-contracts | lib/oz-v4.7.0/contracts/utils/Multicall.sol | solidity | verified | |

## Notes

All 50 sampled files passed no-LLM verification. No OSS-side issues were identified in this batch.
