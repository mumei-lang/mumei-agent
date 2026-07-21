# Target OSS no-LLM dogfooding audit — continuation 27 (batch 28)

Run: 2026-07-21T03:11:23.745825Z

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All 50 sampled files passed no-LLM verification in this batch.

## Tool-side fixes (batch 28)

1. **Go float division false positive**
   - `_go_float_variables` tracks local variables initialized with `float64`/`float32` casts or float literals.
   - `_division_safety_issue` now skips divisors that are provably `float64`/`float32` variables, because Go float division by zero produces `+/-Inf` (not a panic).
   - Rep: `prysm/beacon-chain/p2p/gossip_scoring_params.go` (`topicWeight` in `InvalidMessageDeliveriesWeight`).

2. **Go top-level nonzero float constants**
   - `_go_nonzero_constants` now recognizes top-level `const` declarations with non-zero float literals (e.g. `aggregateWeight = 0.5`) so they are not modeled as free integers that can be zero.

3. **Solidity named return parameters treated as state writes**
   - `_solidity_named_return_params` parses `returns (...)` names.
   - `_solidity_ordered_op_trace` skips assignments to named return parameters, because they are local variables, not storage writes.
   - Rep: `uniswap-contracts/src/briefcase/deployers/v4-periphery/ReservesLensDeployer.sol` (`reservesLens = address(...)` after `CREATE2_FACTORY.call`).

4. **Rust `#[tokio::test]` skipped for contract inference**
   - `_rust_attribute_identifiers` recursively collects attribute identifiers, so `#[tokio::test]` is recognized as a test attribute.
   - `_has_rust_test_attribute` now matches path-style attributes (`#[tokio::test]`, `#[tokio::test(flavor = ...)]`).
   - Rep: `influxdb/influxdb3/tests/server/auth.rs` (`v1_password_parameter`).

5. **Go `case`/`default` return-expression boundary (from PR #417)**
   - Left word-boundary check added so identifiers ending in `case` or `default` (`lowercase`, `snake_case`, `is_default`) are not truncated.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/internal/obj/arm64/inst_test.go` | verified |  |
| go | `src/cmd/link/internal/sym/compilation_unit.go` | verified |  |
| go | `src/math/floor_noasm.go` | verified |  |
| go | `src/internal/poll/fd_windows.go` | verified |  |
| go | `src/internal/godebug/godebug.go` | verified |  |
| go | `src/runtime/signal_dragonfly.go` | verified |  |
| go | `src/crypto/internal/fips140/aes/gcm/gcm_asm.go` | verified |  |
| go | `src/net/sockaddr_posix.go` | verified |  |
| go | `src/syscall/zsyscall_netbsd_amd64.go` | verified |  |
| go | `src/internal/poll/errno_unix.go` | verified |  |
| prysm | `encoding/ssz/helpers_test.go` | verified | No Mumei atoms |
| prysm | `consensus-types/payload-attribute/getters.go` | verified |  |
| prysm | `beacon-chain/rpc/prysm/v1alpha1/debug/p2p.go` | verified |  |
| prysm | `beacon-chain/p2p/gossip_scoring_params.go` | verified |  |
| prysm | `cmd/validator/log.go` | verified |  |
| prysm | `validator/db/filesystem/import.go` | verified |  |
| prysm | `api/client/options.go` | verified |  |
| prysm | `testing/spectest/shared/altair/epoch_processing/eth1_data_reset.go` | verified |  |
| prysm | `beacon-chain/slasher/params.go` | verified |  |
| prysm | `tools/analyzers/httpwriter/analyzer.go` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/mocks/errors.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/testSetup/plugins.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/api/util.test.ts` | verified |  |
| grafana | `e2e-playwright/dashboards-suite/dashboard-export-image.spec.ts` | verified |  |
| grafana | `public/app/features/teams/mocks/teamMocks.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/mocks/cloudwatch-logs-test-data/sortQuery.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Tooltip/types.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/DateTimePickers/options.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/pages/utils.ts` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/createBaseQuery.ts` | verified |  |
| influxdb | `influxdb3_system_tables/src/lib.rs` | verified |  |
| influxdb | `influxdb3_catalog/src/object_store/versions/mod.rs` | verified |  |
| influxdb | `influxdb3_catalog/src/object_store/versions/v2/tests.rs` | verified | No Mumei atoms |
| influxdb | `core/test_helpers/src/lib.rs` | verified |  |
| influxdb | `influxdb3_catalog/src/catalog/versions/v3/deletes.rs` | verified |  |
| influxdb | `influxdb3/tests/server/auth.rs` | verified | No Mumei atoms |
| influxdb | `core/iox_query/src/statistics/schema_bound.rs` | verified |  |
| influxdb | `influxdb3_catalog/src/format/records/conversions.rs` | verified |  |
| influxdb | `core/mutable_batch/tests/extend.rs` | verified | No Mumei atoms |
| influxdb | `influxdb3_catalog/src/snapshot/versions/mod.rs` | verified |  |
| uniswap-contracts | `src/briefcase/deployers/v4-periphery/PositionManagerDeployer.sol` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/utils/Address.sol` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v2-core/libraries/UQ112x112.sol` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/ERC721URIStorageMock.sol` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/interfaces/IERC1155Receiver.sol` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v3-core/interfaces/callback/IUniswapV3SwapCallback.sol` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/view-quoter-v3/libraries/PoolTickBitmap.sol` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/proxy/ERC1967/ERC1967Upgrade.sol` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/swap-router-contracts/libraries/PoolTicksCounter.sol` | verified |  |
| uniswap-contracts | `src/briefcase/deployers/v4-periphery/ReservesLensDeployer.sol` | verified |  |
