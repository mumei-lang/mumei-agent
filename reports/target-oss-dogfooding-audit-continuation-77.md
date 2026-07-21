# Target OSS no-LLM dogfooding audit — continuation 77 (batch 78)

Run: 2026-07-21T22:06:34.976734+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification after fixing `go/src/log/slog/value_test.go`.

## Tool-side fixes in this batch

- Go: recognize named return values `(name type)` so boolean/string return types are not mapped to `i64`.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `test/typeparam/chansimp.dir/main.go` | verified |  |
| go | `src/cmd/go/internal/work/cover.go` | verified |  |
| influxdb | `core/iox_query_influxql/src/plan/var_ref.rs` | verified |  |
| influxdb | `influxdb3_system_tables/src/influxdb_schema.rs` | verified |  |
| prysm | `beacon-chain/state/state-native/getters_withdrawal_test.go` | verified |  |
| grafana | `pkg/apimachinery/apis/common/v0alpha1/unstructured.go` | verified |  |
| go | `test/fixedbugs/issue52788a.go` | verified |  |
| influxdb | `core/iox_query_influxql/src/plan/planner/union.rs` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/governance/IGovernor.sol` | verified |  |
| influxdb | `core/influxdb2_client/src/models/onboarding.rs` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/lib-external/solidity-lib/contracts/libraries/BitMath.sol` | verified |  |
| prysm | `validator/client/beacon-api/test-helpers/test_helpers.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/controller/connection.go` | verified |  |
| grafana | `pkg/cmd/grafana-cli/commands/remove_command_test.go` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/utils/StorageSlot.sol` | verified |  |
| grafana | `public/app/plugins/datasource/graphite/meta.ts` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/calibur/libraries/Static.sol` | verified |  |
| prysm | `api/grpc/grpc_connection_provider.go` | verified |  |
| influxdb | `core/influxdb2_client/tests/common/server_fixture.rs` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/ERC165/ERC165MissingData.sol` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v4-core/libraries/ProtocolFeeLibrary.sol` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/SignedMathMock.sol` | verified |  |
| influxdb | `core/iox_query/src/provider/adapter.rs` | verified |  |
| grafana | `pkg/storage/unified/resource/secure_test.go` | verified |  |
| influxdb | `influxdb3_catalog/src/catalog/versions/v2.rs` | verified |  |
| prysm | `beacon-chain/db/kv/genesis_test.go` | verified |  |
| grafana | `public/app/types/datasources.ts` | verified |  |
| prysm | `beacon-chain/sync/sync_fuzz_test.go` | verified |  |
| influxdb | `core/influxdb2_client/src/models/retention_rule.rs` | verified |  |
| go | `src/go/types/call.go` | verified |  |
| prysm | `cmd/validator/usage.go` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/governance/TimelockController.sol` | verified |  |
| grafana | `packages/grafana-alerting/src/testing.ts` | verified |  |
| influxdb | `core/schema/src/merge.rs` | verified |  |
| go | `src/log/slog/value_test.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rules/central-state-history/EventListSceneObject.tsx` | verified |  |
| go | `src/cmd/internal/obj/pcln.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/downward_counting_loop.go` | verified |  |
| influxdb | `core/influxdb_iox_client/src/client/flight/mod.rs` | verified |  |
| prysm | `proto/prysm/v1alpha1/attestation/aggregation/maxcover_test.go` | verified |  |
| go | `test/fixedbugs/bug242.go` | verified |  |
| prysm | `beacon-chain/blockchain/checktags_test.go` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/utils/Base64.sol` | verified |  |
| grafana | `apps/folder/pkg/apis/folder/v1/zz_generated.deepcopy.go` | verified |  |
| go | `test/typeparam/adder.go` | verified |  |
| uniswap-contracts | `script/cli/src/workflows/register/register_contract.rs` | verified |  |
| grafana | `public/app/features/provisioning/Shared/CloudInfoBox.tsx` | verified |  |
| prysm | `beacon-chain/db/slasherkv/slasher.go` | verified |  |
| prysm | `validator/client/grpc-api/grpc_validator_client.go` | verified |  |
| go | `test/fixedbugs/issue56778.dir/b.go` | verified |  |
