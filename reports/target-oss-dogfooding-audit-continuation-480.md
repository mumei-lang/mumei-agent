# Target OSS no-LLM dogfooding audit — continuation 480 (batch 481)

Run: 2026-07-23T05:38:55.555294+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/reflectdata/alg.go` | verified |  |
| go | `src/cmd/compile/internal/test/moveload_test.go` | verified |  |
| go | `src/cmd/go/internal/auth/userauth.go` | verified |  |
| go | `src/image/png/reader.go` | verified |  |
| go | `src/internal/runtime/sys/intrinsics.go` | verified |  |
| go | `src/internal/trace/base.go` | verified |  |
| go | `src/log/slog/value_access_benchmark_test.go` | verified |  |
| go | `src/net/netip/netip_pkg_test.go` | verified |  |
| go | `src/net/sys_cloexec.go` | verified |  |
| go | `src/os/exec_test.go` | verified |  |
| go | `src/runtime/plugin.go` | verified |  |
| go | `src/runtime/sys_openbsd.go` | verified |  |
| go | `test/assign.go` | verified |  |
| go | `test/fixedbugs/bug180.go` | verified |  |
| go | `test/fixedbugs/bug196.go` | verified |  |
| go | `test/fixedbugs/bug328.go` | verified |  |
| go | `test/fixedbugs/issue4232.go` | verified |  |
| go | `test/fixedbugs/issue4458.go` | verified |  |
| go | `test/fixedbugs/issue53018.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v1beta1/receiver_schema_gen.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/conversion/v0_test.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/cache_test.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/serviceaccount_getserviceaccounttoken_response_body_types_gen.go` | verified |  |
| grafana | `apps/logsdrilldown/plugin/src/generated/logsdrilldowndefaults/v1alpha1/types.metadata.gen.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Layout/Grid/Grid.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/reducer.ts` | verified |  |
| grafana | `pkg/apis/userstorage/v0alpha1/register.go` | verified |  |
| grafana | `pkg/registry/apis/datasource/sub_resource.go` | verified |  |
| grafana | `pkg/registry/apps/alerting/rules/recordingrule/compat.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/legacy_storage/receivers_test.go` | verified |  |
| grafana | `pkg/services/notifications/models.go` | verified |  |
| grafana | `pkg/services/rendering/auth_test.go` | verified |  |
| grafana | `pkg/setting/setting_k8s_dashboard_cleanup.go` | verified |  |
| grafana | `pkg/storage/unified/sql/service_test.go` | verified |  |
| grafana | `pkg/tsdb/azuremonitor/metrics/url-builder.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/models/query_error.go` | verified |  |
| grafana | `public/app/features/admin/ldap/LdapDrawer.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/import-to-gma/steps/Step1AlertmanagerResources.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/mute-timings/NewMuteTiming.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rules/central-state-history/utils.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/rule-list/hooks/useFilteredRulesIterator.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/layout-notebook/cells/CodeCell.tsx` | verified |  |
| grafana | `public/app/features/dashboard/containers/NewDashboardWithDS.tsx` | verified |  |
| grafana | `public/app/features/geo/format/geohash.ts` | verified |  |
| grafana | `public/app/features/home/DashboardTabs/types.ts` | verified |  |
| grafana | `public/app/features/logs/components/otel/formats.ts` | verified |  |
| grafana | `public/app/features/transformers/editors/HistogramTransformerEditor.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/loki/components/monaco-query-field/MonacoQueryField.tsx` | verified |  |
| grafana | `public/app/plugins/panel/geomap/components/MeasureVectorLayer.ts` | verified |  |
| grafana | `public/app/plugins/panel/timeseries/plugins/AnnotationsPlugin.tsx` | verified |  |
