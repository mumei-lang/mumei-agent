# Target OSS no-LLM dogfooding audit — continuation 90 (batch 91)

Run: 2026-07-21T23:06:55.465987+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification after fixing a tree-sitter regression.

- Rust/Go: `_strip_go_rust_literals_and_comments` now masks comment contents fully while preserving string/char literal quote delimiters. This prevents `//` comments from leaking `/` characters into the regex fallback and avoids false-positive `divide by s` reports.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| influxdb | `core/iox_query/src/analyzer/handle_gapfill.rs` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/token/ERC721/IERC721.sol` | verified |  |
| grafana | `pkg/tests/apis/provisioning/foldermetadata/github_urls_test.go` | verified |  |
| influxdb | `influxdb3_catalog/src/catalog/versions/v2/update/enterprise.rs` | verified |  |
| go | `src/os/os_windows_test.go` | verified |  |
| go | `src/cmd/compile/internal/types2/issues_test.go` | verified |  |
| prysm | `beacon-chain/operations/attestations/kv/aggregated.go` | verified |  |
| go | `src/cmd/cgo/internal/testerrors/badsym_test.go` | verified |  |
| prysm | `testing/spectest/minimal/deneb__operations__voluntary_exit_test.go` | verified |  |
| influxdb | `influxdb3_server/src/http.rs` | verified |  |
| grafana | `pkg/plugins/backendplugin/grpcplugin/grpc_plugin.go` | verified |  |
| prysm | `beacon-chain/sync/backfill/verify_column_test.go` | verified |  |
| prysm | `beacon-chain/sync/initial-sync/testing/mock.go` | verified |  |
| influxdb | `influxdb3_system_tables/src/tables.rs` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v37.go` | verified |  |
| uniswap-contracts | `src/briefcase/deployers/v3-periphery/TickLensDeployer.sol` | verified |  |
| go | `src/runtime/race0.go` | verified |  |
| prysm | `beacon-chain/state/state-native/gloas.go` | verified |  |
| influxdb | `core/query_functions/src/derivative.rs` | verified |  |
| grafana | `apps/provisioning/pkg/connection/delete_validator_test.go` | verified |  |
| prysm | `beacon-chain/state/state-native/custom-types/block_roots_test.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/mixed-quoter/libraries/Path.sol` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/swap-router-contracts/interfaces/IImmutableState.sol` | verified |  |
| grafana | `public/app/features/dashboard-scene/edit-pane/MultiSelectedVizPanelsEditableElement.tsx` | verified |  |
| go | `src/net/http/readrequest_test.go` | verified |  |
| prysm | `testing/spectest/shared/fulu/rewards/rewards_penalties.go` | verified |  |
| go | `src/cmd/compile/internal/test/conditionalCmpConst_test.go` | verified |  |
| prysm | `tools/analyzers/logruswitherror/analyzer_test.go` | verified |  |
| influxdb | `core/object_store_mem_cache/src/cache_system/hook/limit.rs` | verified |  |
| go | `src/crypto/x509/sec1_test.go` | verified |  |
| grafana | `pkg/registry/apps/alerting/rules/alertrule/compat.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/lib-external/solady/src/utils/LibBytes.sol` | verified |  |
| influxdb | `influxdb3_write/src/table_index_cache.rs` | verified |  |
| grafana | `public/app/features/dashboard/dashgrid/DashboardLibrary/utils/templateDashboardHelpers.ts` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v2-core/interfaces/IERC20.sol` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v3-core/interfaces/pool/IUniswapV3PoolDerivedState.sol` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/universal-router/libraries/Commands.sol` | verified |  |
| influxdb | `core/iox_query/src/exec/query_tracing.rs` | verified |  |
| prysm | `testing/spectest/shared/electra/epoch_processing/pending_deposit_updates.go` | verified |  |
| influxdb | `influxdb3_cache/src/last_cache/metrics.rs` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/variables/components/AdHocOriginFiltersEditor.tsx` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v3-periphery/interfaces/external/IERC20PermitAllowed.sol` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications_manifest.go` | verified |  |
| go | `test/fixedbugs/issue23521.go` | verified |  |
| go | `test/typeparam/issue50121b.dir/c.go` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/MultipleInheritanceInitializableMocks.sol` | verified |  |
| prysm | `network/httputil/reader.go` | verified |  |
| influxdb | `core/trace/src/span.rs` | verified |  |
| grafana | `apps/provisioning/pkg/generated/applyconfiguration/provisioning/v0alpha1/gitlabrepositoryconfig.go` | verified |  |
| go | `src/go/types/scope2.go` | verified |  |
