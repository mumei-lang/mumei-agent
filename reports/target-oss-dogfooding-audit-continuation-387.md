# Target OSS no-LLM dogfooding audit — continuation 387 (batch 388)

Run: 2026-07-22T23:56:39.111517+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ssa/poset.go` | verified |  |
| go | `src/cmd/go/export_test.go` | verified |  |
| go | `src/cmd/go/internal/modindex/write.go` | verified |  |
| go | `src/cmd/go/internal/work/build_test.go` | verified |  |
| go | `src/database/sql/driver/types_test.go` | verified |  |
| go | `src/debug/gosym/pclntab_test.go` | verified |  |
| go | `src/internal/goexperiment/exp_sizespecializedmalloc_off.go` | verified |  |
| go | `src/internal/routebsd/address_darwin_test.go` | verified |  |
| go | `src/internal/runtime/gc/scan/expand_reference.go` | verified |  |
| go | `src/internal/runtime/gc/scan/scan_amd64.go` | verified |  |
| go | `src/net/cgo_netbsd.go` | verified |  |
| go | `src/net/http/internal/testcert/testcert.go` | verified |  |
| go | `src/runtime/os_freebsd.go` | verified |  |
| go | `src/syscall/env_windows.go` | verified |  |
| go | `src/unique/canonmap.go` | verified |  |
| go | `test/fixedbugs/issue33013.dir/d.go` | verified |  |
| go | `test/fixedbugs/issue45947.go` | verified |  |
| go | `test/fixedbugs/issue65957.dir/main.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/datasource_utils.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/globalrolebinding_object_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/connection/github/extra.go` | verified |  |
| grafana | `apps/secret/pkg/apis/secret/v1beta1/keeper_client_gen.go` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/provisioning/v0alpha1/endpoints.gen.ts` | verified |  |
| grafana | `packages/grafana-data/src/transformations/transformers.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/TableRT/RowsList.tsx` | verified |  |
| grafana | `pkg/expr/classic/classic.go` | verified |  |
| grafana | `pkg/expr/sql/dummy_arm.go` | verified |  |
| grafana | `pkg/plugins/backendplugin/chunked/writer.go` | verified |  |
| grafana | `pkg/registry/apps/alerting/notifications/routingtree/legacy_storage.go` | verified |  |
| grafana | `pkg/registry/apps/annotation/sql_adapter.go` | verified |  |
| grafana | `pkg/services/authz/rbac_settings.go` | verified |  |
| grafana | `pkg/services/authz/zanzana/server/server_mutate_org_role.go` | verified |  |
| grafana | `pkg/services/ngalert/sender/notifier_test.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrator/migrations.go` | verified |  |
| grafana | `pkg/storage/unified/informer/cachelessperiodicinformer_test.go` | verified |  |
| grafana | `pkg/storage/unified/migrations/testcases/playlists_mig.go` | verified |  |
| grafana | `pkg/tests/apis/alerting/rules/compat/alertrule_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/folderapiversion/folder_api_version_test.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/services/hardcoded_metrics.go` | verified |  |
| grafana | `pkg/util/xorm/dialect_sqlite3.go` | verified |  |
| grafana | `public/app/features/dashboard-scene/mutation-api/commands/listPanels.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelDataPane/types.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/Sidebar/QueriesAndTransformationsView.tsx` | verified |  |
| grafana | `public/app/features/dashboard/containers/DashboardPageProxy.tsx` | verified |  |
| grafana | `public/app/features/home/analytics/main.ts` | verified |  |
| grafana | `public/app/features/logs/components/panel/export.ts` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/ResourcePicker/AdvancedMulti.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/mocks/datasourceSettings.ts` | verified |  |
| grafana | `public/app/plugins/panel/alertlist/util.ts` | verified |  |
| grafana | `public/app/types/dashboard.ts` | verified |  |
