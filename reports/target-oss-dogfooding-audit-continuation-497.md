# Target OSS no-LLM dogfooding audit — continuation 497 (batch 498)

Run: 2026-07-23T06:38:28.535353+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ssa/licm_test.go` | verified |  |
| go | `src/cmd/go/internal/trace/trace.go` | verified |  |
| go | `src/cmd/link/internal/loadpe/ldpe.go` | verified |  |
| go | `src/compress/flate/level1.go` | verified |  |
| go | `src/crypto/internal/cryptotest/wycheproof/wycheproof.go` | verified |  |
| go | `src/encoding/json/v2/bench_test.go` | verified |  |
| go | `src/encoding/xml/atom_test.go` | verified |  |
| go | `src/hash/crc32/crc32_s390x.go` | verified |  |
| go | `src/net/http/internal/http2/pipe.go` | verified |  |
| go | `src/os/env.go` | verified |  |
| go | `src/runtime/mgcmark_nogreenteagc.go` | verified |  |
| go | `src/runtime/print_quoted_test.go` | verified |  |
| go | `src/runtime/sigqueue.go` | verified |  |
| go | `src/runtime/valgrind.go` | verified |  |
| go | `src/simd/archsimd/_gen/sgutil/asbits.go` | verified |  |
| go | `src/syscall/zsysnum_freebsd_arm64.go` | verified |  |
| go | `test/finprofiled.go` | verified |  |
| go | `test/fixedbugs/bug063.go` | verified |  |
| go | `test/fixedbugs/bug093.go` | verified |  |
| go | `test/fixedbugs/issue15175.go` | verified |  |
| go | `test/fixedbugs/issue20813.go` | verified |  |
| go | `test/fixedbugs/issue51733.go` | verified |  |
| go | `test/ken/cplx5.go` | verified |  |
| go | `test/typeparam/issue48280.dir/a.go` | verified |  |
| grafana | `apps/alerting/rules/pkg/app/alertrule/validator.go` | verified |  |
| grafana | `apps/dashvalidator/pkg/generated/dashboardcompatibilityscore/v1alpha1/constants.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/github/webhook.go` | verified |  |
| grafana | `apps/secret/pkg/apis/secret/v1beta1/exposed_secure_value_test.go` | verified |  |
| grafana | `packages/grafana-data/src/utils/withLoadingIndicator.ts` | verified |  |
| grafana | `pkg/services/authz/rbac/mapper_test.go` | verified |  |
| grafana | `pkg/services/ngalert/accesscontrol/routes.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/legacy_storage/v1/compat.go` | verified |  |
| grafana | `pkg/storage/unified/search/builders/alertingrules.go` | verified |  |
| grafana | `pkg/tsdb/azuremonitor/loganalytics/consts.go` | verified |  |
| grafana | `public/app/core/components/OptionsUI/stats.tsx` | verified |  |
| grafana | `public/app/dev.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/import-to-gma/useCanImportToGMA.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/notification-policies/PolicyPage.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-viewer/RuleContext.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/utils/receiver-form.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/layout-default/DashboardGridItemEditor.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/new-toolbar/actions/PlayListNextButton.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/utils/dashboardSceneGraph.ts` | verified |  |
| grafana | `public/app/features/dimensions/scale.ts` | verified |  |
| grafana | `public/app/features/provisioning/Wizard/ProvisioningWizard.tsx` | verified |  |
| grafana | `public/app/features/transformers/calculateHeatmap/heatmap.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/language/logs/completion/CompletionItemProvider.ts` | verified |  |
| grafana | `public/app/plugins/datasource/influxdb/components/editor/query/influxql/visual/OrderByTimeSection.tsx` | verified |  |
| grafana | `public/app/plugins/panel/timeseries/plugins/annotations/AnnotationEditor.tsx` | verified |  |
| grafana | `public/app/plugins/panel/xychart/utils.ts` | verified |  |
