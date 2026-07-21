# Target OSS no-LLM dogfooding audit — continuation 58 (batch 59)

Run: 2026-07-21T13:55:01.994293+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All 50 sampled files passed no-LLM verification.

## Tool-side fixes in this batch

- Go: treat ``Mod`` methods with an integer parameter as having a non-zero divisor.
- Go: suppress nil-deref false positives for SSZ interface methods (``MarshalSSZ``/``UnmarshalSSZ``/``SizeSSZ``/``HashTreeRoot``/``HashTreeRootWith``).
- Rust: suppress i64 overflow false positives for sums of size/length variables.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/objdump/main.go` | verified | |
| prysm | `testing/spectest/mainnet/deneb__light_client__single_merkle_proof_test.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v4-periphery/libraries/PositionInfoLibrary.sol` | verified | |
| prysm | `encoding/ssz/helpers.go` | verified | |
| go | `test/typeparam/issue51219b.go` | verified | |
| prysm | `beacon-chain/state/state-native/setters_deposits.go` | verified | |
| influxdb | `influxdb3_catalog/src/catalog/versions/v3/ops/token/tests.rs` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/token/ERC20/extensions/ERC4626.sol` | verified | |
| go | `test/codegen/issue61356.go` | verified | |
| grafana | `pkg/util/xorm/engine_table.go` | verified | |
| go | `src/cmd/compile/internal/liveness/intervals_test.go` | verified | |
| grafana | `pkg/services/pluginsintegration/pluginsintegration.go` | verified | |
| go | `src/cmd/compile/internal/loopvar/testdata/opt-121.go` | verified | |
| go | `src/go/internal/gcimporter/gcimporter_test.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/calibur/interfaces/IERC1271.sol` | verified | |
| prysm | `testing/spectest/shared/common/operations/consolidations.go` | verified | |
| uniswap-contracts | `script/cli/src/workflows/deploy/mod.rs` | verified | |
| influxdb | `core/schema/src/lib.rs` | verified | |
| go | `src/crypto/tls/handshake_client.go` | verified | |
| grafana | `packages/grafana-schema/src/schema/notebook/v2beta1/index.ts` | verified | |
| go | `test/fixedbugs/issue28445.go` | verified | |
| prysm | `beacon-chain/core/electra/deposits.go` | verified | |
| grafana | `public/app/features/dashboard-scene/scene/dashboard-filters-overview/DashboardFiltersOverviewDrawer.tsx` | verified | |
| go | `src/crypto/internal/boring/ecdsa.go` | verified | |
| grafana | `pkg/generated/clientset/versioned/scheme/register.go` | verified | |
| grafana | `packages/grafana-sql/src/dialects/sqlIdentifier.ts` | verified | |
| uniswap-contracts | `src/briefcase/protocols/lib-external/openzeppelin-contracts/contracts/utils/Strings.sol` | verified | |
| influxdb | `core/ingester_query_grpc/src/lib.rs` | verified | |
| prysm | `beacon-chain/state/state-native/setters_attestation.go` | verified | |
| uniswap-contracts | `script/cli/src/constants.rs` | verified | |
| go | `src/internal/runtime/gc/internal/gen/gen.go` | verified | |
| influxdb | `influxdb3_load_generator/src/commands/full.rs` | verified | |
| grafana | `public/app/features/trails/RedirectToDrilldownApp.tsx` | verified | |
| influxdb | `core/predicate/src/rpc_predicate/field_rewrite.rs` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v2-periphery/interfaces/V1/IUniswapV1Exchange.sol` | verified | |
| influxdb | `influxdb3_catalog/src/catalog/versions/v3/ops/query_group/tests.rs` | verified | |
| grafana | `pkg/storage/unified/sql/server_test.go` | verified | |
| prysm | `consensus-types/primitives/validator.go` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/utils/Context.sol` | verified | |
| influxdb | `influxdb3_catalog/src/log/versions/v4/enterprise.rs` | verified | |
| influxdb | `influxdb3_catalog/src/catalog/versions/v3/schema/user.rs` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/GovernorVoteMock.sol` | verified | |
| grafana | `packages/grafana-ui/src/components/SecretFormField/SecretFormField.tsx` | verified | |
| prysm | `beacon-chain/operations/payloadattestation/pool_test.go` | verified | |
| prysm | `validator/client/beacon-api/get_beacon_block.go` | verified | |
| influxdb | `core/influxdb_iox_client/src/client/compactor.rs` | verified | |
| uniswap-contracts | `src/briefcase/protocols/uniswapx/interfaces/IArbSys.sol` | verified | |
| grafana | `pkg/login/social/socialimpl/support_bundle.go` | verified | |
| influxdb | `influxdb3_catalog/src/catalog/versions/v3/legacy.rs` | verified | |
| prysm | `beacon-chain/cache/payload_id.go` | verified | |
