# Target OSS no-LLM dogfooding audit — continuation 479 (batch 480)

Run: 2026-07-23T05:34:08.334579+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ir/cfg.go` | verified |  |
| go | `src/cmd/go/internal/base/base.go` | verified |  |
| go | `src/flag/example_value_test.go` | verified |  |
| go | `src/go/token/position.go` | verified |  |
| go | `src/net/http/transfer_test.go` | verified |  |
| go | `src/os/sys_windows.go` | verified |  |
| go | `src/runtime/defs_openbsd_386.go` | verified |  |
| go | `src/runtime/signal_netbsd_386.go` | verified |  |
| go | `src/runtime/sys_libc.go` | verified |  |
| go | `test/fixedbugs/bug331.go` | verified |  |
| go | `test/fixedbugs/bug437.dir/one.go` | verified |  |
| go | `test/fixedbugs/issue16870.go` | verified |  |
| go | `test/fixedbugs/issue35518.go` | verified |  |
| go | `test/fixedbugs/issue52953.go` | verified |  |
| go | `test/typeparam/issue48337b.dir/main.go` | verified |  |
| go | `test/typeparam/issue48454.dir/main.go` | verified |  |
| go | `test/typeparam/issue49049.go` | verified |  |
| go | `test/typeparam/issue54302.dir/main.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v1/zz_generated.deepcopy.go` | verified |  |
| grafana | `apps/dashvalidator/pkg/generated/dashboardcompatibilityscore/v1alpha1/dashboardcompatibilityscore_client_gen.go` | verified |  |
| grafana | `apps/example/pkg/app/config.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/clientset/versioned/typed/provisioning/v0alpha1/fake/fake_job.go` | verified |  |
| grafana | `apps/quotas/pkg/apis/quotas_manifest.go` | verified |  |
| grafana | `packages/grafana-runtime/src/services/pluginMeta/types/plugin/plugin_object_gen.ts` | verified |  |
| grafana | `packages/grafana-schema/src/schema/dashboard/v0alpha1/types.status.gen.ts` | verified |  |
| grafana | `packages/grafana-ui/src/utils/scrollbar.ts` | verified |  |
| grafana | `pkg/api/dtos/frontend_settings.go` | verified |  |
| grafana | `pkg/mocks/mock_s3ifaces/mocks.go` | verified |  |
| grafana | `pkg/registry/apis/secret/secure_value_client.go` | verified |  |
| grafana | `pkg/services/annotations/annotationsimpl/composite_store_test.go` | verified |  |
| grafana | `pkg/services/ngalert/store/alert_rule_labels.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/angularpatternsstore/store_test.go` | verified |  |
| grafana | `pkg/services/user/password_test.go` | verified |  |
| grafana | `pkg/storage/unified/search/embed/embedder/azure/embed_dense_test.go` | verified |  |
| grafana | `pkg/tsdb/jaeger/standalone/main.go` | verified |  |
| grafana | `public/app/core/components/ForgottenPassword/ForgottenPassword.tsx` | verified |  |
| grafana | `public/app/dev-utils.ts` | verified |  |
| grafana | `public/app/features/admin/UserListPublicDashboardPage/DashboardsListModalButton.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/reducers/ruler/ruleGroups.ts` | verified |  |
| grafana | `public/app/features/connections/pages/NewDataSourcePage.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/ManagedDashboardNavBarBadge.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/variables/VariablesUnknownTable.tsx` | verified |  |
| grafana | `public/app/features/datasources/components/DataSourcePluginState.tsx` | verified |  |
| grafana | `public/app/features/manage-dashboards/import/components/ImportDashboardFormV2.tsx` | verified |  |
| grafana | `public/app/features/plugins/admin/components/Badges/PluginDisabledBadge.tsx` | verified |  |
| grafana | `public/app/features/provisioning/components/Folders/MissingFolderMetadataBanner.tsx` | verified |  |
| grafana | `public/app/features/provisioning/hooks/useBranchTemplate.ts` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/ResourcePicker/NestedEntry.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/mocks/cloudwatch-logs-test-data/diffQuery.ts` | verified |  |
| grafana | `public/app/plugins/panel/logstable/props/getInitialRowIndex.ts` | verified |  |
