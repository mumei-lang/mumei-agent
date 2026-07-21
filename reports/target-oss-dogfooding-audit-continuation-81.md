# Target OSS no-LLM dogfooding audit — continuation 81 (batch 82)

Run: 2026-07-21T22:41:38.993348+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification after fixing `go/src/math/big/floatconv.go` and `go/src/cmd/go/internal/work/action.go`.

## Tool-side fixes in this batch

- Go: treat unsigned integer indices (`uint64` etc.) as non-negative, dropping the lower-bound contract.
- Go: recognize `const m = len(arr) - 1; if n <= m { arr[n] }` as a valid upper-bound guard and treat `m` as a safe last index.
- Go: recognize `Actor.Act` interface implementations (`Act(*Builder, context.Context, *Action) error`) and suppress nil-receiver false positives for `*Builder`/`*Action` parameters.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| influxdb | `influxdb3_types/src/database_name.rs` | verified |  |
| prysm | `beacon-chain/operations/slashings/doc.go` | verified |  |
| prysm | `beacon-chain/p2p/pubsub_fuzz_test.go` | verified |  |
| prysm | `proto/prysm/v1alpha1/beacon_block.go` | verified |  |
| influxdb | `core/influxdb2_client/src/models/links.rs` | verified |  |
| prysm | `testing/spectest/minimal/deneb__epoch_processing__historical_summaries_update_test.go` | verified |  |
| grafana | `pkg/services/ngalert/state/state_test.go` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/utils/Checkpoints.sol` | verified |  |
| go | `src/runtime/race/doc.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v3-periphery/libraries/OracleLibrary.sol` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/DashboardAnnotationsDataLayer.ts` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/lib-external/base64/base64.sol` | verified |  |
| influxdb | `influxdb3/tests/server/write.rs` | verified |  |
| prysm | `monitoring/clientstats/interfaces.go` | verified |  |
| grafana | `public/app/features/plugins/sandbox/sandboxPluginLoader.ts` | verified |  |
| go | `test/fixedbugs/bug131.go` | verified |  |
| go | `src/syscall/zsysnum_openbsd_riscv64.go` | verified |  |
| prysm | `beacon-chain/p2p/addr_factory.go` | verified |  |
| uniswap-contracts | `script/cli/src/screens/verify_contract/verify_contract_screen.rs` | verified |  |
| uniswap-contracts | `script/cli/src/screens/types/text_display.rs` | verified |  |
| influxdb | `influxdb3_cache/src/last_cache/table_function.rs` | verified |  |
| influxdb | `core/influxdb2_client/src/api/write.rs` | verified |  |
| grafana | `pkg/registry/apis/dashboard/snapshot/migrator/migrator.go` | verified |  |
| uniswap-contracts | `src/briefcase/deployers/util-contracts/ERC7914DetectorDeployer.sol` | verified |  |
| grafana | `apps/provisioning/pkg/apis/auth/access_checker_mock.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v3-core/interfaces/pool/IUniswapV3PoolEvents.sol` | verified |  |
| grafana | `pkg/services/ngalert/accesscontrol/roles.go` | verified |  |
| grafana | `pkg/tests/apis/iam/serviceaccount/service_account_integration_test.go` | verified |  |
| influxdb | `core/influxdb_influxql_parser/src/expression/arithmetic.rs` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/ssosettings/migrations.go` | verified |  |
| grafana | `pkg/services/store/kind/dashboard/reference.go` | verified |  |
| go | `src/math/big/floatconv.go` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/ERC721Mock.sol` | verified |  |
| grafana | `packages/grafana-data/src/types/orgs.ts` | verified |  |
| influxdb | `core/iox_query_influxql/src/show_databases.rs` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/permit2/interfaces/IPermit2.sol` | verified |  |
| influxdb | `core/query_functions/src/group_by.rs` | verified |  |
| prysm | `testing/spectest/mainnet/fulu__fork_transition__transition_test.go` | verified |  |
| go | `src/go/types/termlist.go` | verified |  |
| influxdb | `influxdb3_load_generator/src/commands/common.rs` | verified |  |
| go | `src/runtime/signal_loong64.go` | verified |  |
| prysm | `consensus-types/blocks/partialdatacolumn.go` | verified |  |
| go | `src/cmd/cgo/internal/test/issue8517.go` | verified |  |
| go | `src/cmd/go/internal/work/action.go` | verified |  |
| go | `src/runtime/mstats.go` | verified |  |
| go | `src/cmd/go/internal/vcweb/dir.go` | verified |  |
| prysm | `proto/prysm/v1alpha1/validator-client/interface.go` | verified |  |
| influxdb | `.circleci/packages/test_influxdb3-launcher.py` | verified |  |
| prysm | `api/client/client.go` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/token/ERC1155/extensions/ERC1155Supply.sol` | verified |  |
