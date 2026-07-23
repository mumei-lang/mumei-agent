# Target OSS no-LLM dogfooding audit — continuation 402 (batch 403)

Run: 2026-07-23T00:45:59.891341+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/gofmt/gofmt_test.go` | verified |  |
| go | `src/cmd/link/internal/arm/obj.go` | verified |  |
| go | `src/go/types/exprstring_test.go` | verified |  |
| go | `src/go/types/signature.go` | verified |  |
| go | `src/math/big/ratconv.go` | verified |  |
| go | `src/net/tcpconn_keepalive_conf_unix_test.go` | verified |  |
| go | `src/runtime/os_dragonfly.go` | verified |  |
| go | `src/text/template/examplefiles_test.go` | verified |  |
| go | `test/abi/f_ret_z_not.go` | verified |  |
| go | `test/fixedbugs/bug403.go` | verified |  |
| go | `test/fixedbugs/issue24547.go` | verified |  |
| go | `test/fixedbugs/issue44370.go` | verified |  |
| go | `test/fixedbugs/issue5291.go` | verified |  |
| go | `test/fixedbugs/issue5856.go` | verified |  |
| go | `test/fixedbugs/issue7995b.dir/x1.go` | verified |  |
| go | `test/interface/private.dir/prog.go` | verified |  |
| grafana | `apps/advisor/pkg/app/checks/plugincheck/twinmaker_sceneviewer_step.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/applyconfiguration/provisioning/v0alpha1/webhookconfig.go` | verified |  |
| grafana | `packages/grafana-schema/src/index.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/FilterPill/FilterPill.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Forms/FieldArray.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/utils/useDelayedSwitch.ts` | verified |  |
| grafana | `pkg/api/alerting.go` | verified |  |
| grafana | `pkg/api/pluginproxy/pluginproxy_test.go` | verified |  |
| grafana | `pkg/components/satokengen/tokengen.go` | verified |  |
| grafana | `pkg/expr/mathexp/parse/lex_test.go` | verified |  |
| grafana | `pkg/infra/filestorage/filter.go` | verified |  |
| grafana | `pkg/plugins/backendplugin/coreplugin/core_plugin.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/informer/job.go` | verified |  |
| grafana | `pkg/services/featuremgmt/static_evaluator_typed_test.go` | verified |  |
| grafana | `pkg/services/live/model/model.go` | verified |  |
| grafana | `pkg/services/ngalert/metrics/api.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/pipeline/steps.go` | verified |  |
| grafana | `pkg/storage/unified/migrations/migrator_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/foldermetadata/full_sync_move_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/foldermetadata/sync_folder_metadata_test.go` | verified |  |
| grafana | `pkg/tsdb/grafana-postgresql-datasource/postgres_snapshot_test.go` | verified |  |
| grafana | `pkg/tsdb/loki/api_test.go` | verified |  |
| grafana | `public/app/features/alerting/unified/integration/AlertRulesDrawerContent.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/navigation/useDeletedRulesNav.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/DashboardScene.tsx` | verified |  |
| grafana | `public/app/features/dashboard/components/ShareModal/utils.ts` | verified |  |
| grafana | `public/app/features/datasources/components/DataSourcesListCard.tsx` | verified |  |
| grafana | `public/app/features/manage-dashboards/import/components/ImportOverview.tsx` | verified |  |
| grafana | `public/app/features/panel/table/PaginationEditor.tsx` | verified |  |
| grafana | `public/app/features/plugins/utils.ts` | verified |  |
| grafana | `public/app/features/provisioning/Migrate/MigrateDrawer.tsx` | verified |  |
| grafana | `public/app/features/variables/constant/reducer.ts` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/datasource.ts` | verified |  |
| grafana | `public/app/plugins/datasource/grafana-testdata-datasource/components/SimulationQueryEditor.tsx` | verified |  |
