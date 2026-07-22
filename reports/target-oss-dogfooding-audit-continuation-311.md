# Target OSS no-LLM dogfooding audit — continuation 311 (batch 312)

Run: 2026-07-22T18:49:02.311371+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/inline/inlheur/analyze_func_flags.go` | verified |  |
| go | `src/cmd/compile/internal/inline/inlheur/scoring.go` | verified |  |
| go | `src/go/doc/comment/markdown.go` | verified |  |
| go | `src/internal/poll/errno_windows.go` | verified |  |
| go | `src/internal/runtime/sys/consts_norace.go` | verified |  |
| go | `src/net/interface_linux.go` | verified |  |
| go | `src/net/iprawsock_posix.go` | verified |  |
| go | `src/runtime/map_fast32.go` | verified |  |
| go | `src/runtime/stubs_arm64.go` | verified |  |
| go | `test/abi/part_live_2.go` | verified |  |
| go | `test/fixedbugs/bug244.go` | verified |  |
| go | `test/fixedbugs/bug441.go` | verified |  |
| go | `test/fixedbugs/issue11610.go` | verified |  |
| go | `test/fixedbugs/issue5291.dir/pkg1.go` | verified |  |
| go | `test/fixedbugs/issue8761.go` | verified |  |
| grafana | `apps/advisor/pkg/app/checks/authchecks/list_format_validation.go` | verified |  |
| grafana | `emails/grunt/replace.js` | verified |  |
| grafana | `packages/grafana-data/src/context/plugins/DataSourcePluginContextProvider.tsx` | verified |  |
| grafana | `packages/grafana-data/src/types/dataFrame.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Modal/ModalsContext.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/types/orientation.ts` | verified |  |
| grafana | `pkg/cmd/grafana-server/commands/diagnostics.go` | verified |  |
| grafana | `pkg/infra/log/syslog.go` | verified |  |
| grafana | `pkg/plugins/manager/signature/manifest_test.go` | verified |  |
| grafana | `pkg/registry/apps/playlist/migration_registrar.go` | verified |  |
| grafana | `pkg/services/authz/zanzana/client/noop.go` | verified |  |
| grafana | `pkg/services/live/managedstream/cache_memory.go` | verified |  |
| grafana | `pkg/services/sqlstore/database_wrapper.go` | verified |  |
| grafana | `pkg/storage/unified/search/bleve_mappings.go` | verified |  |
| grafana | `public/app/core/hooks/useStoredBoolean.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/RuleEvaluationIntervalField.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/hooks/abilities/rules/ruleAbilities.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/hooks/useUnifiedAlertingSelector.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/dashboard-filters-overview/DashboardFiltersOverviewSearch.tsx` | verified |  |
| grafana | `public/app/features/dashboard/components/PanelEditor/types.ts` | verified |  |
| grafana | `public/app/features/datasources/state/actions.ts` | verified |  |
| grafana | `public/app/features/home/AlertsIncidents/constants.ts` | verified |  |
| grafana | `public/app/features/migrate-to-cloud/MigrateToCloud.tsx` | verified |  |
| grafana | `public/app/plugins/panel/dashlist/styles.ts` | verified |  |
| grafana | `public/app/plugins/panel/stat/suggestions.ts` | verified |  |
| prysm | `beacon-chain/p2p/encoder/varint_test.go` | verified |  |
| prysm | `beacon-chain/rpc/prysm/v1alpha1/debug/server.go` | verified |  |
| prysm | `cmd/completion_scripts.go` | verified |  |
| prysm | `consensus-types/blocks/signed_execution_bid.go` | verified |  |
| prysm | `genesis/storage.go` | verified |  |
| prysm | `testing/endtoend/helpers/keystore.go` | verified |  |
| prysm | `testing/spectest/minimal/capella__ssz_static__ssz_static_test.go` | verified |  |
| prysm | `testing/spectest/minimal/deneb__random__random_test.go` | verified |  |
| prysm | `testing/spectest/shared/electra/epoch_processing/participation_flag_updates.go` | verified |  |
| prysm | `testing/spectest/shared/fulu/epoch_processing/pending_deposit_updates.go` | verified |  |
