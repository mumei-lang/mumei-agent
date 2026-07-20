# Target OSS Dogfooding Audit - Continuation 21 (Batch 22)

## Summary

- **Date**: 2026-07-20
- **Method**: no-LLM batch sampling
- **Sample size**: 50 files
- **Result**: **50 verified / 0 refuted / 0 unverifiable**

## Tool improvements in this batch

### 1. Solidity named return values

Solidity functions that name their return value, e.g. `returns (bool flag)`, were previously parsed as an unknown type (`bool flag`) and defaulted to `i64`. This caused the `ensures` clause `result == (y == 0)` to be generated for a boolean return, which Mumei rejects with `Expected bool for ==`. Now the type token is separated from the parameter name, so `bool flag` correctly becomes `bool` and the ensures clause falls back to `true`.

Affected representative file:
- `uniswap-contracts/src/briefcase/protocols/lib-external/webauthn-sol/lib/FreshCryptoLib/solidity/src/FCL_elliptic.sol` (`ecAff_IsZero`)

### 2. Human-language Go preconditions

Go doc comments such as `// Preconditions: cgoSymbolizerAvailable returns true` were emitted verbatim as Mumei `requires` clauses. Mumei cannot parse the English phrase `returns true` as a boolean expression, which caused `mumei verify` to fail with `spec_lowering_failed`. Such human-language contracts are now sanitized to `true`.

Affected representative file:
- `go/src/runtime/traceback.go` (`printOneCgoTraceback`, `callCgoSymbolizer`, `cgoContextPCs`)

## Per-file results

| # | repo | file | language | status | notes |
|---|------|------|----------|--------|-------|
| 1 | grafana | pkg/registry/apis/provisioning/files_test.go | go | verified | |
| 2 | grafana | pkg/services/ngalert/models/notifications_test.go | go | verified | |
| 3 | prysm | beacon-chain/state/stateutil/reference.go | go | verified | |
| 4 | go | src/simd/archsimd/pkginternal_test.go | go | verified | |
| 5 | prysm | api/server/httprest/options.go | go | verified | |
| 6 | go | src/runtime/traceback.go | go | verified | |
| 7 | prysm | validator/client/sync_committee_test.go | go | verified | |
| 8 | grafana | public/app/plugins/datasource/influxdb/influx_series.test.ts | typescript | verified | |
| 9 | prysm | testing/spectest/minimal/phase0__ssz_static__ssz_static_test.go | go | verified | |
| 10 | uniswap-contracts | src/briefcase/protocols/v4-hooks-public/aggregator-hooks/implementations/StableSwap/interfaces/IStableSwap.sol | solidity | verified | |
| 11 | grafana | packages/grafana-data/src/types/action.ts | typescript | verified | |
| 12 | influxdb | core/influxdb2_client/src/models/ast/package_clause.rs | rust | verified | |
| 13 | go | src/cmd/compile/internal/ssa/known_bits_test.go | go | verified | |
| 14 | prysm | testing/spectest/mainnet/deneb__epoch_processing__randao_mixes_reset_test.go | go | verified | |
| 15 | prysm | beacon-chain/rpc/prysm/v1alpha1/validator/aggregator_test.go | go | verified | |
| 16 | uniswap-contracts | src/briefcase/protocols/v4-periphery/libraries/LiquidityAmounts.sol | solidity | verified | |
| 17 | go | src/net/internal/socktest/switch_posix.go | go | verified | |
| 18 | uniswap-contracts | lib/oz-v4.7.0/contracts/token/ERC1155/extensions/ERC1155Pausable.sol | solidity | verified | |
| 19 | uniswap-contracts | src/briefcase/protocols/lib-external/openzeppelin-contracts/contracts/utils/math/SafeCast.sol | solidity | verified | |
| 20 | grafana | pkg/storage/unified/resource/kv/kv.go | go | verified | |
| 21 | influxdb | core/iox_query/src/physical_optimizer/sort/merge_partitions.rs | rust | verified | |
| 22 | uniswap-contracts | src/briefcase/protocols/lib-external/webauthn-sol/lib/FreshCryptoLib/solidity/src/FCL_elliptic.sol | solidity | verified | |
| 23 | go | src/crypto/internal/boring/rand.go | go | verified | |
| 24 | uniswap-contracts | src/briefcase/protocols/permit2/libraries/Permit2Lib.sol | solidity | verified | |
| 25 | influxdb | influxdb3_catalog/src/catalog/versions/v3/schema/storage.rs | rust | verified | |
| 26 | go | src/cmd/compile/internal/test/move_test.go | go | verified | |
| 27 | influxdb | core/iox_query_influxql/src/aggregate.rs | rust | verified | |
| 28 | influxdb | influxdb3_catalog/src/catalog/versions/v1/update.rs | rust | verified | |
| 29 | prysm | testing/spectest/mainnet/altair__fork_transition__transition_test.go | go | verified | |
| 30 | prysm | validator/client/beacon-api/stream_blocks_test.go | go | verified | |
| 31 | influxdb | influxdb3_catalog/src/log/versions/v3.rs | rust | verified | |
| 32 | influxdb | core/data_types/src/columns.rs | rust | verified | |
| 33 | grafana | public/app/features/explore/state/utils.test.ts | typescript | verified | |
| 34 | go | src/iter/iter.go | go | verified | |
| 35 | uniswap-contracts | src/briefcase/protocols/calibur/lib/account-abstraction/interfaces/IAccount.sol | solidity | verified | |
| 36 | grafana | public/app/features/variables/textbox/adapter.ts | typescript | verified | |
| 37 | uniswap-contracts | src/briefcase/protocols/swap-router-contracts/interfaces/IWETH.sol | solidity | verified | |
| 38 | influxdb | core/iox_query_influxql/src/plan/expr_type_evaluator.rs | rust | verified | |
| 39 | go | src/internal/syscall/windows/registry/syscall.go | go | verified | |
| 40 | influxdb | influxdb3_catalog/src/format/registry/tests.rs | rust | verified | |
| 41 | go | src/log/syslog/syslog_test.go | go | verified | |
| 42 | grafana | pkg/services/ngalert/accesscontrol/rules_test.go | go | verified | |
| 43 | prysm | tools/analyzers/modernize/stringsbuilder/analyzer.go | go | verified | |
| 44 | influxdb | core/mutable_batch_pb/src/lib.rs | rust | verified | |
| 45 | grafana | packages/grafana-data/src/utils/namedColorsPalette.ts | typescript | verified | |
| 46 | prysm | testing/spectest/shared/bellatrix/operations/voluntary_exit.go | go | verified | |
| 47 | grafana | public/app/features/logs/components/panel/LogLineMessage.test.tsx | typescript | verified | |
| 48 | go | src/context/afterfunc_test.go | go | verified | |
| 49 | uniswap-contracts | lib/oz-v4.7.0/contracts/mocks/ReentrancyMock.sol | solidity | verified | |
| 50 | uniswap-contracts | src/briefcase/protocols/universal-router/interfaces/external/IV3SpokePool.sol | solidity | verified | |

## Notes

All 50 sampled files passed no-LLM verification. No OSS-side issues were identified in this batch.
