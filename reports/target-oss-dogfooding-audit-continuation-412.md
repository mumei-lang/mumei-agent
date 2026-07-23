# Target OSS no-LLM dogfooding audit — continuation 412 (batch 413)

Run: 2026-07-23T01:14:58.015374+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ssa/_gen/allocators.go` | verified |  |
| go | `src/cmd/compile/internal/types2/conversions.go` | verified |  |
| go | `src/cmd/link/internal/ld/execarchive_noexec.go` | verified |  |
| go | `src/crypto/internal/fips140/aes/gcm/cmac.go` | verified |  |
| go | `src/crypto/internal/fips140/aes/gcm/ctrkdf.go` | verified |  |
| go | `src/go/types/resolver.go` | verified |  |
| go | `src/hash/example_test.go` | verified |  |
| go | `src/internal/runtime/gc/scan/mkasm.go` | verified |  |
| go | `src/internal/syscall/unix/getrandom_linux.go` | verified |  |
| go | `src/runtime/cgroup_stubs.go` | verified |  |
| go | `src/runtime/defs_netbsd.go` | verified |  |
| go | `src/sync/map_bench_test.go` | verified |  |
| go | `test/codegen/bits.go` | verified |  |
| go | `test/fixedbugs/bug274.go` | verified |  |
| go | `test/fixedbugs/issue19246.go` | verified |  |
| go | `test/fixedbugs/issue26426.go` | verified |  |
| go | `test/fixedbugs/issue31987.go` | verified |  |
| go | `test/fixedbugs/issue52862.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue5957.go` | verified |  |
| go | `test/interface/assertinline.go` | verified |  |
| go | `test/typeparam/issue48094.go` | verified |  |
| go | `test/typeparam/issue51219b.dir/a.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v2beta1/doc.go` | verified |  |
| grafana | `e2e-playwright/test-plugins/frontend-sandbox-app-test/module.js` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| grafana | `packages/grafana-data/src/valueFormats/symbolFormatters.ts` | verified |  |
| grafana | `packages/grafana-runtime/src/analytics/plugins/usePluginInteractionReporter.ts` | verified |  |
| grafana | `packages/grafana-runtime/src/services/pluginMeta/test-fixtures/config.panels.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/TableNG/Cells/AutoCell.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/uPlot/Plot.tsx` | verified |  |
| grafana | `pkg/expr/mathexp/reduce_test.go` | verified |  |
| grafana | `pkg/expr/ml/model.go` | verified |  |
| grafana | `pkg/services/navtree/models.go` | verified |  |
| grafana | `pkg/services/ngalert/api/api_alertmanager_test.go` | verified |  |
| grafana | `pkg/services/preference/prefimpl/xorm_store_test.go` | verified |  |
| grafana | `pkg/services/ssosettings/ssosettingsimpl/mtsettings_client_test.go` | verified |  |
| grafana | `pkg/storage/legacysql/dualwrite/dualwriter_mode3_test.go` | verified |  |
| grafana | `public/app/core/components/RolePicker/RolePickerSubMenu.tsx` | verified |  |
| grafana | `public/app/core/services/echo/backends/analytics/RudderstackBackend.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/mocks/server/handlers/k8s/integrationTypeSchemas.k8s.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/reducers/alertmanager/notificationPolicyRoutes.ts` | verified |  |
| grafana | `public/app/features/connections/Connections.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/conditional-rendering/conditions/ConditionalRenderingData.tsx` | verified |  |
| grafana | `public/app/features/dashboard/state/utils.ts` | verified |  |
| grafana | `public/app/features/explore/RecentQueries/RecentQueriesLayout.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/TraceTimelineViewer/index.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/language/metric-math/completion/statementPosition.ts` | verified |  |
| grafana | `public/app/plugins/panel/alertlist/types.ts` | verified |  |
| grafana | `public/app/plugins/panel/canvas/editor/element/PlacementEditor.tsx` | verified |  |
| grafana | `public/app/plugins/panel/logstable/fields/defaultLogLevelColumnConfig.ts` | verified |  |
| grafana | `public/test/log-reporter.js` | verified |  |
