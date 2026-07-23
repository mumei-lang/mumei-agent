# Target OSS no-LLM dogfooding audit — continuation 410 (batch 411)

Run: 2026-07-23T01:08:53.819332+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/bytes/reader_test.go` | verified |  |
| go | `src/cmd/compile/internal/noder/linker.go` | verified |  |
| go | `src/cmd/compile/internal/types/pkg.go` | verified |  |
| go | `src/cmd/compile/internal/types2/stdlib_test.go` | verified |  |
| go | `src/cmd/internal/obj/x86/avx_optabs.go` | verified |  |
| go | `src/crypto/dsa/dsa_test.go` | verified |  |
| go | `src/crypto/internal/fips140/nistec/nistec.go` | verified |  |
| go | `src/encoding/json/v2/fold_test.go` | verified |  |
| go | `src/os/user/user_windows_test.go` | verified |  |
| go | `src/runtime/netpoll.go` | verified |  |
| go | `test/codegen/zerosize.go` | verified |  |
| go | `test/fixedbugs/bug156.go` | verified |  |
| go | `test/fixedbugs/bug215.go` | verified |  |
| go | `test/fixedbugs/issue15602.go` | verified |  |
| go | `test/fixedbugs/issue31959.go` | verified |  |
| go | `test/fixedbugs/issue44344.go` | verified |  |
| go | `test/fixedbugs/issue4545.go` | verified |  |
| go | `test/fixedbugs/issue9862.go` | verified |  |
| go | `test/funcdup.go` | verified |  |
| go | `test/typeparam/setsimp.dir/a.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v0alpha1/dashboard_client_gen.go` | verified |  |
| grafana | `apps/folder/pkg/apis/folder/v1/zz_generated.openapi.go` | verified |  |
| grafana | `packages/grafana-sql/src/components/SqlComponents.testHelpers.ts` | verified |  |
| grafana | `pkg/cmd/grafana-server/commands/target.go` | verified |  |
| grafana | `pkg/expr/sql/parser_test.go` | verified |  |
| grafana | `pkg/registry/apis/secret/validator/secure_value_test.go` | verified |  |
| grafana | `pkg/services/apiserver/options/extra.go` | verified |  |
| grafana | `pkg/services/ldap/testing.go` | verified |  |
| grafana | `pkg/services/ngalert/accesscontrol/inhibition_rules.go` | verified |  |
| grafana | `pkg/services/ngalert/models/instance_annotations.go` | verified |  |
| grafana | `pkg/services/ngalert/schedule/alerts_sender_mock.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/licensing/licensing_test.go` | verified |  |
| grafana | `pkg/services/query/query_test.go` | verified |  |
| grafana | `pkg/services/signingkeys/signingkeystore/fake.go` | verified |  |
| grafana | `pkg/storage/unified/resource/bulk_test.go` | verified |  |
| grafana | `pkg/tests/testinfra/metrics.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/log_anomalies_query.go` | verified |  |
| grafana | `pkg/util/errhttp/writer_test.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/import-to-gma/Wizard/useImportMethod.ts` | verified |  |
| grafana | `public/app/features/connections/hooks/useDatasourceAdvisorChecks.tsx` | verified |  |
| grafana | `public/app/features/connections/routes.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/conditional-rendering/object.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelOptionsPane.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/new-toolbar/actions/BackToDashboardButton.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/AnnotationsEditView.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/sharing/components/ImagePreview.tsx` | verified |  |
| grafana | `public/app/features/home/DashboardTabs/RecentDashboardsTab.tsx` | verified |  |
| grafana | `public/app/features/transformers/editors/EnumMappingRow.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/influxdb/components/editor/config-v2/UrlAndAuthenticationSection.tsx` | verified |  |
| grafana | `public/app/plugins/panel/timeseries/plugins/annotations/getAnnotationTooltip.tsx` | verified |  |
