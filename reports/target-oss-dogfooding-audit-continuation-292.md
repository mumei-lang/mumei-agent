# Target OSS no-LLM dogfooding audit — continuation 292 (batch 293)

Run: 2026-07-22T17:32:34.799419+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/escape/alias.go` | verified |  |
| go | `src/cmd/compile/internal/ir/func_test.go` | verified |  |
| go | `src/crypto/x509/parser_test.go` | verified |  |
| go | `src/encoding/xml/read_test.go` | verified |  |
| go | `src/internal/profile/proto_test.go` | verified |  |
| go | `src/net/ip.go` | verified |  |
| go | `src/runtime/metrics/description_test.go` | verified |  |
| go | `test/codegen/issue59297.go` | verified |  |
| go | `test/dwarf/dwarf.dir/z2.go` | verified |  |
| go | `test/fixedbugs/bug168.go` | verified |  |
| go | `test/fixedbugs/issue23545.go` | verified |  |
| go | `test/fixedbugs/issue43164.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue52128.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue72090.go` | verified |  |
| grafana | `apps/advisor/pkg/apis/advisor/v0alpha1/check_status_gen.go` | verified |  |
| grafana | `apps/correlations/pkg/apis/correlation/v0alpha1/correlation_client_gen.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v9.go` | verified |  |
| grafana | `apps/playlist/pkg/apis/playlist/v1/playlist_object_gen.go` | verified |  |
| grafana | `packages/grafana-runtime/src/services/pluginSettings/types.ts` | verified |  |
| grafana | `packages/grafana-test-utils/src/jsdom.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/Cells/FooterCell.tsx` | verified |  |
| grafana | `pkg/services/dashboards/models_test.go` | verified |  |
| grafana | `pkg/services/live/pipeline/frame_output_threshold_mock.go` | verified |  |
| grafana | `pkg/services/publicdashboards/internal/database/database_test.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/quota_mig.go` | verified |  |
| grafana | `pkg/storage/unified/migrations/testcases/shorturls.go` | verified |  |
| grafana | `pkg/tests/alertmanager/postgres.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/folderscope/helper_test.go` | verified |  |
| grafana | `pkg/tests/testinfra/testinfra.go` | verified |  |
| grafana | `pkg/tests/testsuite/testsuite.go` | verified |  |
| grafana | `public/app/core/components/PluginHelp/PluginHelp.tsx` | verified |  |
| grafana | `public/app/features/browse-dashboards/components/DashboardsTree.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/mutation-api/commands/addRow.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/saving/getDashboardChanges.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/variables/components/CustomVariableForm.tsx` | verified |  |
| grafana | `public/app/features/dashboard/components/PanelEditor/OptionsPaneCategory.tsx` | verified |  |
| grafana | `public/app/features/dashboard/dashgrid/DashboardLibrary/types.ts` | verified |  |
| grafana | `public/app/features/plugins/sandbox/sandboxPluginLoaderRegistry.ts` | verified |  |
| grafana | `public/app/features/scopes/tests/utils/mockData.ts` | verified |  |
| grafana | `public/app/features/variables/pickers/shared/VariableLink.tsx` | verified |  |
| prysm | `beacon-chain/core/transition/skip_slot_cache_test.go` | verified |  |
| prysm | `beacon-chain/db/kv/deposit_contract.go` | verified |  |
| prysm | `beacon-chain/db/kv/genesis.go` | verified |  |
| prysm | `beacon-chain/execution/jsonrpc_error_test.go` | verified |  |
| prysm | `beacon-chain/sync/validate_data_column.go` | verified |  |
| prysm | `cmd/beacon-chain/das/flags/flags.go` | verified |  |
| prysm | `consensus-types/helpers/comparisons_test.go` | verified |  |
| prysm | `consensus-types/interfaces/utils_test.go` | verified |  |
| prysm | `testing/spectest/mainnet/electra__epoch_processing__inactivity_updates_test.go` | verified |  |
| prysm | `testing/spectest/shared/altair/epoch_processing/inactivity_updates.go` | verified |  |
