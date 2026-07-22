# Target OSS no-LLM dogfooding audit — continuation 266 (batch 267)

Run: 2026-07-22T15:43:29.061702+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/bytes/example_test.go` | verified |  |
| go | `src/cmd/api/main_test.go` | verified |  |
| go | `src/cmd/trace/tasks.go` | verified |  |
| go | `src/internal/cpu/cpu_test.go` | verified |  |
| go | `src/internal/syscall/unix/tcsetpgrp_linux.go` | verified |  |
| go | `src/net/tcpconn_keepalive_test.go` | verified |  |
| go | `src/runtime/sys_mipsx.go` | verified |  |
| go | `test/fixedbugs/bug002.go` | verified |  |
| go | `test/fixedbugs/bug283.go` | verified |  |
| go | `test/fixedbugs/bug476.go` | verified |  |
| go | `test/fixedbugs/issue36516.go` | verified |  |
| go | `test/fixedbugs/issue70156.go` | verified |  |
| go | `test/fixedbugs/issue7083.go` | verified |  |
| go | `test/fixedbugs/issue8074.go` | verified |  |
| grafana | `.github/workflows/scripts/levitate/json-file-to-job-output.js` | verified |  |
| grafana | `apps/plugins/pkg/apis/plugins/v0alpha1/meta_metadata_gen.go` | verified |  |
| grafana | `apps/plugins/pkg/app/meta/core.go` | verified |  |
| grafana | `packages/grafana-flamegraph/src/FlameGraph/FlameGraphContextMenu.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Select/MultiValue.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/options/builder/legend.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/utils/storybook/ThemedDocsContainer.tsx` | verified |  |
| grafana | `pkg/cmd/grafana-cli/commands/reset_password_command_test.go` | verified |  |
| grafana | `pkg/expr/mathexp/exp_series_test.go` | verified |  |
| grafana | `pkg/kinds/dashboard/dashboard_metadata_gen.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/controller/mocks/HealthCheckerInterface.go` | verified |  |
| grafana | `pkg/storage/unified/resource/kv.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/repository/repository_test.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/silences/SilencedAlertsTable.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/sharing/ShareButton/share-externally/PublicShare/CreatePublicSharing.tsx` | verified |  |
| grafana | `public/app/features/datasources/components/DataSourceDashboards.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/constants/default-config.ts` | verified |  |
| grafana | `public/app/features/plugins/loader/utils.ts` | verified |  |
| grafana | `public/app/features/scopes/selector/scopesTreeUtils.ts` | verified |  |
| grafana | `public/app/features/transformers/FilterByValueTransformer/ValueMatchers/BasicMatcherEditor.tsx` | verified |  |
| grafana | `public/app/features/variables/utils.ts` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/azureMetadata/resourceTypes.ts` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/resourcePicker/resourcePickerData.ts` | verified |  |
| grafana | `public/app/plugins/datasource/graphite/module.ts` | verified |  |
| grafana | `public/app/plugins/datasource/loki/querybuilder/components/QueryPattern.tsx` | verified |  |
| grafana | `public/app/plugins/panel/annolist/panelcfg.gen.ts` | verified |  |
| prysm | `api/server/structs/conversions_state.go` | verified |  |
| prysm | `api/server/structs/endpoints_beacon.go` | verified |  |
| prysm | `beacon-chain/core/electra/registry_updates.go` | verified |  |
| prysm | `beacon-chain/state/stategen/epoch_boundary_state_cache.go` | verified |  |
| prysm | `testing/spectest/mainnet/bellatrix__epoch_processing__eth1_data_reset_test.go` | verified |  |
| prysm | `testing/spectest/mainnet/capella__epoch_processing__slashings_test.go` | verified |  |
| prysm | `testing/spectest/mainnet/electra__sanity__blocks_test.go` | verified |  |
| prysm | `testing/spectest/shared/capella/epoch_processing/effective_balance_updates.go` | verified |  |
| prysm | `testing/spectest/shared/deneb/operations/attester_slashing.go` | verified |  |
| prysm | `tools/analyzers/gocognit/analyzer.go` | verified |  |
