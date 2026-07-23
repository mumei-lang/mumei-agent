# Target OSS no-LLM dogfooding audit — continuation 405 (batch 406)

Run: 2026-07-23T00:51:15.159335+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/test/cgo_unix_test.go` | verified |  |
| go | `src/cmd/internal/obj/pass.go` | verified |  |
| go | `src/fmt/stringer_example_test.go` | verified |  |
| go | `src/internal/runtime/atomic/atomic_mips64x.go` | verified |  |
| go | `src/internal/testlog/exit.go` | verified |  |
| go | `src/io/fs/readlink.go` | verified |  |
| go | `src/math/abs.go` | verified |  |
| go | `src/runtime/defs_aix_ppc64.go` | verified |  |
| go | `src/runtime/fastlog2table.go` | verified |  |
| go | `test/codegen/issue25378.go` | verified |  |
| go | `test/fixedbugs/bug458.go` | verified |  |
| go | `test/fixedbugs/issue14553.go` | verified |  |
| go | `test/fixedbugs/issue14652.go` | verified |  |
| go | `test/fixedbugs/issue4452.go` | verified |  |
| go | `test/fixedbugs/issue47087.go` | verified |  |
| go | `test/fixedbugs/issue48835.go` | verified |  |
| go | `test/maymorestack.go` | verified |  |
| go | `test/typeparam/issue52241.go` | verified |  |
| grafana | `apps/advisor/pkg/app/checks/configchecks/security_config_step.go` | verified |  |
| grafana | `apps/secret/pkg/apis/secret/v1beta1/keeper_status_gen.go` | verified |  |
| grafana | `packages/grafana-api-clients/src/index.ts` | verified |  |
| grafana | `packages/grafana-data/src/dataframe/ArrayDataFrame.ts` | verified |  |
| grafana | `packages/grafana-data/src/valueFormats/valueFormats.ts` | verified |  |
| grafana | `packages/grafana-sql/src/utils/logging.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/TableNG/constants.ts` | verified |  |
| grafana | `pkg/expr/ml/outlier.go` | verified |  |
| grafana | `pkg/generated/applyconfiguration/service/v0alpha1/externalnamespec.go` | verified |  |
| grafana | `pkg/registry/apis/collections/register.go` | verified |  |
| grafana | `pkg/registry/apis/iam/resourcepermission/templates_test.go` | verified |  |
| grafana | `pkg/services/accesscontrol/cacheutils_test.go` | verified |  |
| grafana | `pkg/services/ngalert/provisioning/notification_policies_test.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/folder_mig.go` | verified |  |
| grafana | `pkg/storage/unified/federated/stats.go` | verified |  |
| grafana | `pkg/storage/unified/resource/path_extract.go` | verified |  |
| grafana | `pkg/tests/api/correlations/correlations_update_test.go` | verified |  |
| grafana | `pkg/tsdb/azuremonitor/loganalytics/azure-log-analytics-datasource_test.go` | verified |  |
| grafana | `pkg/util/strings_test.go` | verified |  |
| grafana | `public/app/api/clients/correlations/v0alpha1/index.ts` | verified |  |
| grafana | `public/app/core/services/ResponseQueue.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/Well.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/util.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-viewer/tabs/Query/PrometheusQueryPreview.tsx` | verified |  |
| grafana | `public/app/features/auth-config/ProviderConfigForm.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/variables/editors/DataSourceVariableEditor.tsx` | verified |  |
| grafana | `public/app/features/dashboard/components/TransformationsEditor/TransformationEditor.tsx` | verified |  |
| grafana | `public/app/features/explore/hooks/useExplorePageContext.ts` | verified |  |
| grafana | `public/app/features/panel/panellinks/linkSuppliers.ts` | verified |  |
| grafana | `public/app/features/provisioning/components/utils/url.ts` | verified |  |
| grafana | `public/app/plugins/datasource/mysql/sqlUtil.ts` | verified |  |
| grafana | `public/app/plugins/panel/state-timeline/StateTimelineTooltip.tsx` | verified |  |
