# Target OSS Dogfooding Audit - Continuation 22 (Batch 23)

## Summary

- **Date**: 2026-07-20
- **Method**: no-LLM batch sampling
- **Sample size**: 50 files
- **Result**: **50 verified / 0 refuted / 0 unverifiable**

## Tool improvement in this batch

### Go return expressions with string concatenation and unknown function calls

`go/src/net/lookup_plan9.go` (`queryCS`/`queryDNS`) returns a call to `query(...)` whose arguments contain string-literal concatenation:

```go
return query(ctx, netdir+"/cs", net+"!"+host+"!"+service, 128)
```

This expression was being emitted as a Mumei `ensures` clause and failed with `Expected int` / `spec_lowering_failed` because:
- `+` on strings is concatenation, not arithmetic.
- `query(...)` is a call to an unknown function and cannot be lowered into a Mumei contract equality.

`_is_expression_lowerable` now rejects:
1. Any expression containing `+` adjacent to a string literal.
2. Any unknown bare identifier used as a function call.

This causes `_ensures_for_return_expression` to fall back to `true` for such return expressions, eliminating the false `spec_lowering_failed` verdict.

## Per-file results

| # | repo | file | language | status | notes |
|---|------|------|----------|--------|-------|
| 1 | influxdb | influxdb3_catalog/src/catalog/versions/v3/schema/node.rs | rust | verified | |
| 2 | grafana | public/app/plugins/panel/canvas/editor/inline/InlineEdit.tsx | typescript | verified | |
| 3 | uniswap-contracts | src/briefcase/protocols/v4-periphery/interfaces/IERC721Permit_v4.sol | solidity | verified | |
| 4 | influxdb | core/iox_query/src/provider.rs | rust | verified | |
| 5 | go | src/go/types/stmt.go | go | verified | |
| 6 | prysm | testing/bls/verify_test.go | go | verified | |
| 7 | grafana | packages/grafana-ui/src/graveyard/TimeSeries/utils.ts | typescript | verified | |
| 8 | influxdb | core/influxdb2_client/src/models/ast/property_key.rs | rust | verified | |
| 9 | uniswap-contracts | src/briefcase/deployers/universal-router/UnsupportedProtocolDeployer.sol | solidity | verified | |
| 10 | prysm | beacon-chain/p2p/options_test.go | go | verified | |
| 11 | grafana | packages/grafana-data/src/types/data.ts | typescript | verified | |
| 12 | uniswap-contracts | src/briefcase/protocols/universal-router-2_0/libraries/Commands.sol | solidity | verified | |
| 13 | go | src/cmd/go/internal/modload/load.go | go | verified | |
| 14 | influxdb | influxdb3_query_executor/src/query_planner.rs | rust | verified | |
| 15 | go | src/syscall/zerrors_openbsd_arm64.go | go | verified | |
| 16 | go | src/cmd/compile/internal/ssa/cpufeatures.go | go | verified | |
| 17 | grafana | pkg/storage/unified/informer/cachelessperiodicinformer.go | go | verified | |
| 18 | uniswap-contracts | lib/oz-v3.4-solc-0.7/contracts/introspection/IERC165.sol | solidity | verified | |
| 19 | prysm | testing/spectest/shared/altair/epoch_processing/participation_flag_updates.go | go | verified | |
| 20 | prysm | beacon-chain/operations/attestations/kv/metrics.go | go | verified | |
| 21 | influxdb | core/iox_v1_query_api/src/types.rs | rust | verified | |
| 22 | grafana | public/app/features/inspector/types.ts | typescript | verified | |
| 23 | go | src/net/lookup_plan9.go | go | verified | |
| 24 | grafana | pkg/middleware/request_metadata_test.go | go | verified | |
| 25 | influxdb | influxdb3_catalog/src/log/enterprise.rs | rust | verified | |
| 26 | prysm | beacon-chain/sync/backfill/columns.go | go | verified | |
| 27 | uniswap-contracts | lib/oz-v4.7.0/contracts/utils/math/SignedMath.sol | solidity | verified | |
| 28 | prysm | tools/cmd/fetch-testdata/main.go | go | verified | |
| 29 | uniswap-contracts | src/briefcase/protocols/v4-hooks-public/aggregator-hooks/implementations/StableSwapNG/interfaces/ICurveStableSwapNG.sol | solidity | verified | |
| 30 | go | src/net/sock_posix.go | go | verified | |
| 31 | grafana | pkg/services/store/service.go | go | verified | |
| 32 | influxdb | influxdb3/tests/server/packages.rs | rust | verified | |
| 33 | go | src/go/types/union.go | go | verified | |
| 34 | prysm | config/params/testnet_holesky_config_test.go | go | verified | |
| 35 | grafana | pkg/registry/apis/provisioning/resources/parser.go | go | verified | |
| 36 | prysm | beacon-chain/state/state-native/getters_payload_header.go | go | verified | |
| 37 | prysm | beacon-chain/p2p/testing/mock_broadcaster.go | go | verified | |
| 38 | prysm | beacon-chain/db/filesystem/blob.go | go | verified | |
| 39 | uniswap-contracts | lib/oz-v4.7.0/contracts/proxy/beacon/UpgradeableBeacon.sol | solidity | verified | |
| 40 | go | src/crypto/internal/fips140test/cmac_wycheproof_test.go | go | verified | |
| 41 | influxdb | core/trace_http/src/ctx.rs | rust | verified | |
| 42 | grafana | public/app/features/live/data/utils.ts | typescript | verified | |
| 43 | influxdb | influxdb3_catalog/src/enterprise/format/records/mod.rs | rust | verified | |
| 44 | uniswap-contracts | src/briefcase/protocols/lib-external/oz-v3.4-solc-0.7/contracts/math/SafeMath.sol | solidity | verified | |
| 45 | go | src/cmd/compile/internal/ir/abi.go | go | verified | |
| 46 | go | src/cmd/cgo/internal/teststdio/stdio_test.go | go | verified | |
| 47 | uniswap-contracts | lib/oz-v4.7.0/contracts/crosschain/arbitrum/LibArbitrumL1.sol | solidity | verified | |
| 48 | uniswap-contracts | lib/oz-v4.7.0/contracts/mocks/InitializableMock.sol | solidity | verified | |
| 49 | grafana | packages/grafana-data/src/events/EventBus.test.ts | typescript | verified | |
| 50 | influxdb | core/iox_query/src/exec/gapfill/algo.rs | rust | verified | |

## Notes

All 50 sampled files passed no-LLM verification. No OSS-side issues were identified in this batch.
