# Target OSS no-LLM dogfooding audit — continuation 455 (batch 456)

Run: 2026-07-23T03:33:24.851406+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/test/issue9026/issue9026.go` | verified |  |
| go | `src/crypto/internal/fips140/sha512/sha512block_amd64.go` | verified |  |
| go | `src/debug/gosym/pclntab.go` | verified |  |
| go | `src/image/draw/bench_test.go` | verified |  |
| go | `src/internal/poll/export_posix_test.go` | verified |  |
| go | `src/internal/strconv/decimal.go` | verified |  |
| go | `src/internal/syscall/unix/getrandom.go` | verified |  |
| go | `src/net/sockopt_bsd.go` | verified |  |
| go | `src/simd/archsimd/internal/simd_test/unary_amd64_test.go` | verified |  |
| go | `src/sync/atomic/value_test.go` | verified |  |
| go | `src/syscall/js/js.go` | verified |  |
| go | `test/fixedbugs/bug107.go` | verified |  |
| go | `test/fixedbugs/bug390.go` | verified |  |
| go | `test/fixedbugs/issue19764.go` | verified |  |
| go | `test/fixedbugs/issue20415.go` | verified |  |
| go | `test/fixedbugs/issue21687.go` | verified |  |
| go | `test/fixedbugs/issue21770.go` | verified |  |
| go | `test/fixedbugs/issue48033.go` | verified |  |
| go | `test/fixedbugs/issue63489b.go` | verified |  |
| go | `test/fixedbugs/issue65893.go` | verified |  |
| go | `test/typecheck.go` | verified |  |
| go | `test/typeparam/mdempsky/1.go` | verified |  |
| grafana | `apps/alerting/rules/pkg/app/alertrule/mutator.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v1beta1/register.go` | verified |  |
| grafana | `e2e-playwright/test-plugins/grafana-extensionstest-app/plugins/grafana-extensionexample2-app/components/App/index.tsx` | verified |  |
| grafana | `packages/grafana-schema/src/raw/composable/gauge/panelcfg/x/types.gen.ts` | verified |  |
| grafana | `packages/grafana-ui/.storybook/preview.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/DataLinks/DataLinkEditor.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/VizTooltip/VizTooltipWrapper.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/utils/storybook/icons.ts` | verified |  |
| grafana | `packages/grafana-ui/src/utils/storybook/withTheme.tsx` | verified |  |
| grafana | `pkg/infra/metrics/wireset.go` | verified |  |
| grafana | `pkg/services/ngalert/accesscontrol/receivers.go` | verified |  |
| grafana | `pkg/services/ngalert/accesscontrol/rules.go` | verified |  |
| grafana | `pkg/services/ngalert/api/api.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/validation.go` | verified |  |
| grafana | `pkg/storage/unified/resource/lease/metrics_test.go` | verified |  |
| grafana | `pkg/storage/unified/resource/search_server_distributor.go` | verified |  |
| grafana | `public/app/api/clients/provisioning/utils/createOnCacheEntryAdded.ts` | verified |  |
| grafana | `public/app/core/components/SplashScreenModal/SplashScreenSlide.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/api/buildInfo.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/DetailsField.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/styles/pagination.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/types/dashboard.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/annotations/AnnotationSettingsEdit.tsx` | verified |  |
| grafana | `public/app/features/explore/PrometheusListView/ItemLabels.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/utils/span-ancestor-ids.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/useViewRange.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/mocks/cloudwatch-ppl-test-data/newCommandQuery.ts` | verified |  |
| grafana | `public/app/plugins/datasource/influxdb/components/editor/query/influxql/visual/styles.ts` | verified |  |
