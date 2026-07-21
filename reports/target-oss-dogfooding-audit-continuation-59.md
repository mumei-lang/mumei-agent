# Target OSS no-LLM dogfooding audit — continuation 59 (batch 60)

Run: 2026-07-21T13:59:33.224562+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All 50 sampled files passed no-LLM verification.

## Tool-side fixes in this batch

- Solidity: extend Uniswap-V3 sqrt-price parameter detection to include ``sqrtPX96`` style names.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `test/abi/defer_aggregate.go` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/ERC20SnapshotMock.sol` | verified | |
| influxdb | `influxdb3_authz/src/tests.rs` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/governance/extensions/GovernorTimelockControl.sol` | verified | |
| grafana | `pkg/generated/informers/externalversions/generic.go` | verified | |
| prysm | `cmd/beacon-chain/flags/config_test.go` | verified | |
| grafana | `apps/dashboard/pkg/apis/dashboard/v1/dashboard_object_gen.go` | verified | |
| grafana | `public/app/features/panel/suggestions/getAllSuggestions.ts` | verified | |
| prysm | `encoding/ssz/query/ssz_type.go` | verified | |
| uniswap-contracts | `script/cli/build.rs` | verified | |
| go | `src/math/acosh.go` | verified | |
| prysm | `validator/client/beacon-api/sync_committee_selections.go` | verified | |
| influxdb | `core/influxdb_influxql_parser/src/literal.rs` | verified | |
| influxdb | `influxdb3_catalog/src/catalog/versions/mod.rs` | verified | |
| grafana | `e2e-playwright/test-plugins/grafana-test-panel/types.ts` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/ERC20WrapperMock.sol` | verified | |
| grafana | `apps/live/pkg/app/routes.go` | verified | |
| prysm | `io/logs/hook.go` | verified | |
| grafana | `packages/grafana-ui/src/components/Combobox/useMultiInputAutoSize.tsx` | verified | |
| grafana | `packages/grafana-ui/src/components/MatchersUI/FieldNamePicker.tsx` | verified | |
| influxdb | `influxdb3_catalog/src/catalog/versions/v3/ops/user.rs` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v3-core/libraries/SqrtPriceMath.sol` | verified | |
| grafana | `pkg/services/preference/prefimpl/store_test.go` | verified | |
| go | `src/cmd/compile/internal/ssa/testdata/i22558.go` | verified | |
| prysm | `cmd/validator/flags/flags.go` | verified | |
| go | `test/fixedbugs/issue56768.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/calibur/interfaces/INonceManager.sol` | verified | |
| influxdb | `influxdb3_write/src/persister/tests.rs` | verified | |
| influxdb | `core/iox_query/src/provider/deduplicate.rs` | verified | |
| go | `test/maplinear.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/view-quoter-v3/libraries/PoolTickBitmap.sol` | verified | |
| uniswap-contracts | `src/briefcase/protocols/lib-external/openzeppelin-contracts/contracts/utils/cryptography/MessageHashUtils.sol` | verified | |
| prysm | `testing/spectest/shared/altair/fork/transition.go` | verified | |
| influxdb | `core/influxdb2_client/src/models/user.rs` | verified | |
| go | `test/fixedbugs/bug187.go` | verified | |
| go | `test/fixedbugs/issue10047.go` | verified | |
| prysm | `proto/ssz_query/testing/test_containers.pb.go` | verified | |
| grafana | `public/app/features/alerting/unified/components/AlertingPageWrapper.tsx` | verified | |
| influxdb | `influxdb3_catalog/src/error.rs` | verified | |
| go | `test/fixedbugs/issue78262.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v4-periphery/interfaces/IPositionDescriptor.sol` | verified | |
| go | `src/log/slog/handler.go` | verified | |
| prysm | `testing/spectest/shared/electra/operations/consolidations.go` | verified | |
| go | `test/fixedbugs/issue16317.go` | verified | |
| prysm | `testing/spectest/shared/fulu/epoch_processing/justification_and_finalization.go` | verified | |
| influxdb | `influxdb3_catalog/src/format/mod.rs` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/utils/cryptography/draft-EIP712.sol` | verified | |
| prysm | `beacon-chain/core/gloas/parent_payload.go` | verified | |
| influxdb | `core/influxdb2_client/src/models/ast/import_declaration.rs` | verified | |
| grafana | `public/app/plugins/datasource/influxdb/components/editor/query/influxql/utils/filterTags.ts` | verified | |
