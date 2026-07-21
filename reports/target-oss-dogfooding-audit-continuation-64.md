# Target OSS no-LLM dogfooding audit — continuation 64 (batch 65)

Run: 2026-07-21T14:15:46.462928+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All 50 sampled files passed no-LLM verification.

## Tool-side fixes in this batch

- Go: treat ``*FooV1`` provisioning DTO receivers as non-nil (e.g. Grafana ``MuteTimeV1.mapToModel``).

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| uniswap-contracts | `src/briefcase/protocols/v4-periphery/libraries/Locker.sol` | verified | |
| influxdb | `influxdb3_client/src/lib.rs` | verified | |
| grafana | `pkg/services/provisioning/alerting/mute_times_types.go` | verified | |
| grafana | `packages/grafana-ui/src/components/Tooltip/PopoverController.tsx` | verified | |
| influxdb | `core/influxdb_influxql_parser/src/show_retention_policies.rs` | verified | |
| prysm | `beacon-chain/db/kv/schema.go` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/PausableMock.sol` | verified | |
| prysm | `beacon-chain/db/slasherkv/migrate.go` | verified | |
| prysm | `validator/client/duties_test.go` | verified | |
| grafana | `apps/annotation/pkg/apis/annotation/v0alpha1/creategraphite_request_body_types_gen.go` | verified | |
| go | `src/net/hook_plan9.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v3-core/libraries/LowGasSafeMath.sol` | verified | |
| grafana | `apps/alerting/rules/plugin/src/generated/rulesequence/v0alpha1/rulesequence_object_gen.ts` | verified | |
| grafana | `pkg/services/authz/token_auth.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v2-periphery/libraries/UniswapV2Library.sol` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/utils/Address.sol` | verified | |
| go | `test/fixedbugs/issue27695.go` | verified | |
| go | `test/fixedbugs/bug083.dir/bug0.go` | verified | |
| prysm | `beacon-chain/blockchain/log.go` | verified | |
| go | `src/runtime/testdata/testprogcgo/sigpanic.go` | verified | |
| influxdb | `core/iox_query/src/physical_optimizer/dedup/mod.rs` | verified | |
| uniswap-contracts | `test/Dummy.t.sol` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/GovernorTimelockCompoundMock.sol` | verified | |
| prysm | `testing/mock/beacon_validator_client_mock.go` | verified | |
| grafana | `pkg/tsdb/cloudwatch/features/features.go` | verified | |
| go | `src/internal/goarch/zgoarch_ppc64.go` | verified | |
| go | `test/fixedbugs/issue27232.go` | verified | |
| grafana | `public/app/features/query/components/QueryActionComponent.ts` | verified | |
| prysm | `testing/spectest/shared/gloas/epoch_processing/participation_flag_updates.go` | verified | |
| go | `src/encoding/json/jsontext/pools.go` | verified | |
| influxdb | `influxdb3_catalog/src/catalog/versions/v2/enterprise.rs` | verified | |
| prysm | `testing/spectest/minimal/capella__light_client__update_ranking_test.go` | verified | |
| grafana | `pkg/services/pluginsintegration/cachekvstore/cachekvstore_test.go` | verified | |
| influxdb | `core/influxdb_iox_client/src/client/write.rs` | verified | |
| influxdb | `core/partition/src/lib.rs` | verified | |
| prysm | `testing/spectest/minimal/gloas__epoch_processing__effective_balance_updates_test.go` | verified | |
| go | `src/cmd/cgo/internal/testsanitizers/cshared_test.go` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/ERC777SenderRecipientMock.sol` | verified | |
| influxdb | `influxdb3/src/commands/show.rs` | verified | |
| go | `test/fixedbugs/issue19359.go` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/ERC1155ReceiverMock.sol` | verified | |
| influxdb | `object_store_utils/src/lib.rs` | verified | |
| grafana | `public/app/features/dashboard-scene/settings/links/DashboardLinksSet.tsx` | verified | |
| grafana | `packages/grafana-ui/src/components/Forms/Legacy/Input/Input.tsx` | verified | |
| influxdb | `core/test_helpers_authz/src/lib.rs` | verified | |
| influxdb | `core/linear_buffer/src/allocation.rs` | verified | |
| prysm | `cmd/validator/accounts/exit_test.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/mixed-quoter/libraries/Constants.sol` | verified | |
| go | `src/cmd/compile/internal/ssa/branchelim.go` | verified | |
| prysm | `beacon-chain/sync/backfill/fulu_transition.go` | verified | |
