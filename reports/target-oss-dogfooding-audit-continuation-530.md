# Target OSS no-LLM dogfooding audit — continuation 530 (batch 531)

Run: 2026-07-23T08:45:06.711349+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/test/issue30527/b.go` | verified |  |
| go | `src/cmd/compile/internal/types2/api.go` | verified |  |
| go | `src/cmd/go/internal/telemetrystats/telemetrystats.go` | verified |  |
| go | `src/cmd/link/internal/ld/symtab.go` | verified |  |
| go | `src/encoding/json/jsontext/doc.go` | verified |  |
| go | `src/math/cmplx/exp.go` | verified |  |
| go | `src/runtime/time_nofake.go` | verified |  |
| go | `src/simd/archsimd/_gen/sgutil/merge_generic_ops.go` | verified |  |
| go | `src/syscall/ztypes_linux_arm64.go` | verified |  |
| go | `src/testing/helperfuncs_test.go` | verified |  |
| go | `src/testing/iotest/logger.go` | verified |  |
| go | `src/unique/handle_bench_test.go` | verified |  |
| go | `test/codegen/memops_bigoffset.go` | verified |  |
| go | `test/divmod.go` | verified |  |
| go | `test/fixedbugs/bug069.go` | verified |  |
| go | `test/fixedbugs/issue24761.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue29919.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue32778.go` | verified |  |
| go | `test/fixedbugs/issue40954.go` | verified |  |
| go | `test/fixedbugs/issue49368.go` | verified |  |
| go | `test/fixedbugs/issue79182.go` | verified |  |
| go | `test/fixedbugs/issue80196.go` | verified |  |
| go | `test/typeparam/issue45817.go` | verified |  |
| go | `test/typeparam/issue47775b.go` | verified |  |
| go | `test/typeparam/mdempsky/14.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/github/extra.go` | verified |  |
| grafana | `packages/grafana-schema/src/schema/dashboard/v1beta1/dashboard_object_gen.ts` | verified |  |
| grafana | `pkg/expr/service.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/sync/incremental_hierarchical_test.go` | verified |  |
| grafana | `pkg/services/apiserver/builder/openapi.go` | verified |  |
| grafana | `pkg/services/authn/clients/api_key.go` | verified |  |
| grafana | `pkg/services/live/pipeline/pattern/pattern_test.go` | verified |  |
| grafana | `pkg/services/ngalert/remote/remote_secondary_forked_alertmanager.go` | verified |  |
| grafana | `pkg/services/tag/tagimpl/store.go` | verified |  |
| grafana | `pkg/storage/unified/search/embed/backfill/cursor.go` | verified |  |
| grafana | `pkg/storage/unified/search/vector/pgvector.go` | verified |  |
| grafana | `pkg/storage/unified/testing/storage_backend.go` | verified |  |
| grafana | `pkg/tests/apis/iam/user/user_integration_test.go` | verified |  |
| grafana | `pkg/tsdb/grafana-testdata-datasource/usa_stats.go` | verified |  |
| grafana | `public/app/core/components/TimeSeries/TimeSeries.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/MenuItemPauseRule.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/contact-points/constants.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/insights/grafana/Active.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/layout-rows/RowItems.tsx` | verified |  |
| grafana | `public/app/features/datasources/state/selectors.ts` | verified |  |
| grafana | `public/app/features/provisioning/components/Shared/OrphanedResourceBanner.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/QueryEditor/usePreparedQuery.ts` | verified |  |
| grafana | `public/app/plugins/panel/status-history/utils.ts` | verified |  |
| grafana | `public/test/mocks/workers.ts` | verified |  |
| grafana | `scripts/webpack/plugins/CorsWorkerPlugin.ts` | verified |  |
