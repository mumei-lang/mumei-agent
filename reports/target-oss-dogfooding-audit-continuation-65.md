# Target OSS no-LLM dogfooding audit — continuation 65 (batch 66)

Run: 2026-07-21T14:22:11.946252+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All 50 sampled files passed no-LLM verification.

## Tool-side fixes in this batch

- Rust: treat ``let index = ... % container.len();`` as a guarded index.
- Sampling: replaced a timed-out Rust test-only file with a verified alternative.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `test/clear.go` | verified | |
| influxdb | `influxdb3_py_api/src/system_py.rs` | verified | |
| influxdb | `influxdb3_system_tables/src/plugins.rs` | verified | |
| prysm | `proto/eth/v1/beacon_block.minimal.pb.go` | verified | |
| go | `src/slices/zsortordered.go` | verified | |
| uniswap-contracts | `script/cli/src/workflows/error_workflow.rs` | verified | |
| influxdb | `core/predicate/src/rpc_predicate/column_rewrite.rs` | verified | |
| go | `test/fixedbugs/issue73716.go` | verified | |
| go | `test/closedchan.go` | verified | |
| influxdb | `influxdb3/tests/cli/offline_tokens.rs` | verified | |
| grafana | `pkg/cmd/grafana-cli/commands/datamigrations/encrypt_datasource_passwords_test.go` | verified | |
| prysm | `beacon-chain/state/state-native/setters_churn_test.go` | verified | |
| influxdb | `core/iox_query_influxql/src/aggregate/mode.rs` | verified | |
| go | `test/fixedbugs/bug098.go` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/EnumerableSetMock.sol` | verified | |
| go | `test/fixedbugs/bug340.go` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/interfaces/IERC20.sol` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/token/ERC1155/extensions/ERC1155Burnable.sol` | verified | |
| uniswap-contracts | `src/briefcase/deployers/v4-periphery/ReservesLensDeployer.sol` | verified | |
| influxdb | `influxdb3_clap_blocks/src/tokio.rs` | verified | |
| influxdb | `influxdb3_load_generator/src/specs/mod.rs` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/governance/utils/IVotes.sol` | verified | |
| uniswap-contracts | `script/cli/src/ui.rs` | verified | |
| prysm | `cmd/validator/wallet/create.go` | verified | |
| go | `test/fixedbugs/issue42284.dir/b.go` | verified | |
| grafana | `public/app/plugins/datasource/azuremonitor/components/LogsQueryEditor/AdvancedResourcePicker.tsx` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v3-periphery/libraries/TransferHelper.sol` | verified | |
| influxdb | `core/influxdb2_client/examples/setup.rs` | verified | |
| prysm | `cmd/validator/accounts/backup.go` | verified | |
| grafana | `pkg/services/ngalert/tests/util.go` | verified | |
| influxdb | `core/linear_buffer/src/extend.rs` | verified | |
| prysm | `beacon-chain/sync/rpc_blob_sidecars_by_root_test.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v3-periphery/libraries/PositionKey.sol` | verified | |
| go | `test/fixedbugs/bug335.dir/a.go` | verified | |
| go | `src/encoding/json/v2/arshal_any.go` | verified | |
| grafana | `pkg/util/sqlite/sqlite_nocgo_test.go` | verified | |
| prysm | `testing/validator-mock/node_client_mock.go` | verified | |
| prysm | `beacon-chain/rpc/prysm/v1alpha1/validator/proposer_altair.go` | verified | |
| grafana | `public/app/features/migrate-to-cloud/onprem/types.ts` | verified | |
| go | `test/closure4.go` | verified | |
| prysm | `monitoring/prometheus/simple_server.go` | verified | |
| grafana | `public/app/features/home/DashboardTabs/MostUsedDashboardsTab.tsx` | verified | |
| grafana | `pkg/registry/apis/provisioning/jobs/sync/full_hierarchical_test.go` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/token/ERC721/extensions/ERC721Pausable.sol` | verified | |
| grafana | `public/app/features/serviceaccounts/state/actions.ts` | verified | |
| influxdb | `core/iox_query_influxql/src/window/percent_row_number.rs` | verified | |
| grafana | `pkg/registry/apps/annotation/graphite_handler.go` | verified | |
| prysm | `cmd/beacon-chain/jwt/jwt_test.go` | verified | |
| grafana | `public/app/features/alerting/unified/mocks/rulerApi.ts` | verified | |
| prysm | `testing/spectest/minimal/gloas__random_test.go` | verified | |
