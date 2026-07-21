# Target OSS no-LLM dogfooding audit — continuation 50 (batch 51)

Run: 2026-07-21T13:05:53.763354+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All 50 sampled files passed no-LLM verification.

## Tool-side fixes in this batch

- Go: recognize `if i >= 0 && i < len(arr)` / `if 0 <= i && int(i) < len(arr)` bounds guards and suppress false-positive index safety issues for guarded indices.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `test/fixedbugs/issue6403.go` | verified | |
| go | `src/go/types/recording.go` | verified | |
| go | `src/cmd/nm/doc.go` | verified | |
| grafana | `pkg/tsdb/grafana-postgresql-datasource/macros_test.go` | verified | |
| influxdb | `core/iox_system_tables/src/system_tables.rs` | verified | |
| prysm | `encoding/ssz/query/generalized_index_test.go` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/ContextMock.sol` | verified | |
| influxdb | `influxdb3_shutdown/src/tests.rs` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/proxy/Clones.sol` | verified | |
| grafana | `public/app/features/variables/datasource/actions.ts` | verified | |
| prysm | `api/server/middleware/middleware_test.go` | verified | |
| influxdb | `core/influxdb_influxql_parser/src/test_util.rs` | verified | |
| go | `src/go/doc/synopsis_test.go` | verified | |
| prysm | `testing/spectest/minimal/fulu__epoch_processing__pending_deposits_updates_test.go` | verified | |
| go | `test/fixedbugs/issue80004.go` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/BitmapMock.sol` | verified | |
| prysm | `beacon-chain/state/state-native/setters_proposer_lookahead.go` | verified | |
| grafana | `scripts/openapi3/openapi3conv.go` | verified | |
| influxdb | `core/iox_query/src/exec/metrics.rs` | verified | |
| grafana | `public/app/core/hooks/useQueryParams.ts` | verified | |
| prysm | `encoding/bytesutil/bits.go` | verified | |
| influxdb | `influxdb3_catalog/src/catalog/versions/v3/deletes.rs` | verified | |
| influxdb | `influxdb3_commands/src/debug/catalog/render.rs` | verified | |
| prysm | `beacon-chain/sync/error_test.go` | verified | |
| uniswap-contracts | `src/briefcase/deployers/v3-periphery/NonfungibleTokenPositionDescriptorDeployer.sol` | verified | |
| go | `src/net/tcpsockopt_plan9.go` | verified | |
| go | `src/cmd/link/testdata/linkname/ok.go` | verified | |
| grafana | `pkg/services/apiserver/auth/authorizer/resource_test.go` | verified | |
| grafana | `pkg/storage/unified/migrations/registry_test.go` | verified | |
| grafana | `pkg/services/provisioning/utils/utils_test.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/uniswapx/interfaces/IReactor.sol` | verified | |
| influxdb | `core/iox_query/src/frontend/sql.rs` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v2-periphery/interfaces/IUniswapV2Router02.sol` | verified | |
| uniswap-contracts | `src/briefcase/protocols/calibur/lib/account-abstraction/interfaces/PackedUserOperation.sol` | verified | |
| uniswap-contracts | `script/cli/src/util/chain_config.rs` | verified | |
| go | `src/log/slog/value.go` | verified | |
| go | `test/escape_unsafe.go` | verified | |
| influxdb | `influxdb3_catalog/src/error/enterprise.rs` | verified | |
| go | `src/cmd/compile/internal/typecheck/typecheck.go` | verified | |
| grafana | `public/app/plugins/datasource/azuremonitor/components/TracesQueryEditor/TracesQueryEditor.tsx` | verified | |
| prysm | `validator/client/aggregator_selector_test.go` | verified | |
| prysm | `beacon-chain/sync/service.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/calibur/interfaces/IERC7201.sol` | verified | |
| influxdb | `core/ingester_query_grpc/build.rs` | verified | |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/rules.alerting/v0alpha1/index.ts` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v4-core/libraries/FullMath.sol` | verified | |
| grafana | `pkg/services/accesscontrol/resourcepermissions/options.go` | verified | |
| influxdb | `core/influxdb2_client/tests/setup.rs` | verified | |
| prysm | `cmd/helpers.go` | verified | |
| prysm | `beacon-chain/rpc/prysm/v1alpha1/validator/proposer_bid_test.go` | verified | |
