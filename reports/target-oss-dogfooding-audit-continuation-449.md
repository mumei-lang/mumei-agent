# Target OSS no-LLM dogfooding audit — continuation 449 (batch 450)

Run: 2026-07-23T03:15:11.707408+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/test/eq_test.go` | verified |  |
| go | `src/cmd/compile/internal/typecheck/builtin_test.go` | verified |  |
| go | `src/cmd/compile/internal/types/identity.go` | verified |  |
| go | `src/cmd/compile/internal/types2/version.go` | verified |  |
| go | `src/cmd/internal/obj/x86/asm6.go` | verified |  |
| go | `src/compress/gzip/fuzz_test.go` | verified |  |
| go | `src/encoding/xml/example_test.go` | verified |  |
| go | `src/internal/filepathlite/path_nonwindows.go` | verified |  |
| go | `src/internal/poll/sock_cloexec_solaris.go` | verified |  |
| go | `src/internal/strconv/ctoa_test.go` | verified |  |
| go | `src/math/rand/rand_test.go` | verified |  |
| go | `src/runtime/cgo/linux.go` | verified |  |
| go | `src/runtime/defs_freebsd_riscv64.go` | verified |  |
| go | `test/fixedbugs/bug106.dir/bug0.go` | verified |  |
| go | `test/fixedbugs/bug396.go` | verified |  |
| go | `test/fixedbugs/bug412.go` | verified |  |
| go | `test/fixedbugs/issue28601.go` | verified |  |
| go | `test/fixedbugs/issue29562.go` | verified |  |
| go | `test/fixedbugs/issue47068.go` | verified |  |
| go | `test/fixedbugs/issue54912.dir/main.go` | verified |  |
| go | `test/fixedbugs/issue58339.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue77303.go` | verified |  |
| go | `test/ken/modconst.go` | verified |  |
| go | `test/range4.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v0alpha1/getintegrationtypeschemas_response_types_gen.go` | verified |  |
| grafana | `apps/dashvalidator/pkg/validator/prometheus/fetcher_test.go` | verified |  |
| grafana | `apps/example/pkg/apis/example/v1alpha1/example_schema_gen.go` | verified |  |
| grafana | `packages/grafana-data/src/panel/suggestions/getPanelDataSummary.ts` | verified |  |
| grafana | `packages/grafana-test-utils/src/handlers/all-handlers.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/DateTimePickers/TimeRangePicker/mapper.ts` | verified |  |
| grafana | `pkg/api/org.go` | verified |  |
| grafana | `pkg/apiserver/endpoints/request/accept.go` | verified |  |
| grafana | `pkg/expr/mathexp/funcs.go` | verified |  |
| grafana | `pkg/infra/usagestats/service/api.go` | verified |  |
| grafana | `pkg/registry/apis/datasource/queryconvert.go` | verified |  |
| grafana | `pkg/registry/apis/secret/register.go` | verified |  |
| grafana | `pkg/registry/apps/annotation/custom_route_response.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/compat.go` | verified |  |
| grafana | `pkg/services/ngalert/schedule/registry_bench_test.go` | verified |  |
| grafana | `pkg/services/ngalert/state/historian/loki.go` | verified |  |
| grafana | `pkg/storage/secret/encryption/data_key_store_test.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/mocks/cloudwatch_metric_api.go` | verified |  |
| grafana | `public/app/core/utils/urlToken.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/Sidebar/useBulkActions.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/dashboard-filters-overview/DashboardFiltersOverviewPane.tsx` | verified |  |
| grafana | `public/app/features/dashboard/components/AddPanelButton/AddPanelButton.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/loki/components/AnnotationsQueryEditor.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/loki/querybuilder/components/LabelBrowserModal.tsx` | verified |  |
| grafana | `public/app/plugins/panel/xychart/scatter.ts` | verified |  |
| grafana | `scripts/webpack/webpack.stats.ts` | verified |  |
