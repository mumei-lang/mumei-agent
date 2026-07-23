# Target OSS no-LLM dogfooding audit — continuation 492 (batch 493)

Run: 2026-07-23T06:29:09.283383+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ssa/lca.go` | verified |  |
| go | `src/cmd/compile/internal/test/float_test.go` | verified |  |
| go | `src/cmd/compile/internal/test/issue71943_test.go` | verified |  |
| go | `src/cmd/compile/internal/types2/signature.go` | verified |  |
| go | `src/cmd/go/internal/modcmd/vendor.go` | verified |  |
| go | `src/cmd/internal/obj/arm64/list7.go` | verified |  |
| go | `src/html/escape.go` | verified |  |
| go | `src/internal/goarch/zgoarch_armbe.go` | verified |  |
| go | `src/internal/unsafeheader/unsafeheader_test.go` | verified |  |
| go | `src/io/fs/fs.go` | verified |  |
| go | `src/net/http/pprof/pprof_test.go` | verified |  |
| go | `src/regexp/example_test.go` | verified |  |
| go | `src/strings/builder_test.go` | verified |  |
| go | `src/syscall/zsyscall_plan9_amd64.go` | verified |  |
| go | `test/directive.go` | verified |  |
| go | `test/fixedbugs/bug050.go` | verified |  |
| go | `test/fixedbugs/bug173.go` | verified |  |
| go | `test/fixedbugs/bug238.go` | verified |  |
| go | `test/fixedbugs/bug507.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue44325.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue47185.go` | verified |  |
| go | `test/fixedbugs/issue52020.go` | verified |  |
| go | `test/ken/litfun.go` | verified |  |
| go | `test/typeparam/issue48253.go` | verified |  |
| go | `test/typeparam/issue48317.go` | verified |  |
| go | `test/typeparam/issue49241.dir/a.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v2alpha1/conversion.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v11.go` | verified |  |
| grafana | `apps/provisioning/pkg/controller/job.go` | verified |  |
| grafana | `apps/scope/pkg/apis/scope/v0alpha1/zz_generated.defaults.go` | verified |  |
| grafana | `packages/grafana-runtime/src/utils/migrationHandler.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/DateTimePickers/TimeRangeContext.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/slate-plugins/braces.ts` | verified |  |
| grafana | `packages/grafana-ui/src/utils/usePointerDistance.ts` | verified |  |
| grafana | `pkg/apis/userstorage/v0alpha1/zz_generated.defaults.go` | verified |  |
| grafana | `pkg/plugins/pluginassets/ifaces.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/sync/full.go` | verified |  |
| grafana | `pkg/server/search_server_distributor_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/jobs/helpers_test.go` | verified |  |
| grafana | `pkg/tsdb/grafana-postgresql-datasource/tlsmanager.go` | verified |  |
| grafana | `pkg/tsdb/influxdb/influxql/converter/converter.go` | verified |  |
| grafana | `public/app/AppWrapper.tsx` | verified |  |
| grafana | `public/app/core/utils/fetch.ts` | verified |  |
| grafana | `public/app/features/admin/Users/AnonUsersTable.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/triage/scene/AlertRuleInstances.tsx` | verified |  |
| grafana | `public/app/features/canvas/types.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/QueryEditorRenderer.tsx` | verified |  |
| grafana | `public/app/features/logs/components/panel/LogDetailsContext.tsx` | verified |  |
| grafana | `public/app/features/transformers/calculateHeatmap/HeatmapTransformerEditor.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/influxdb/components/editor/config/trackingv1.ts` | verified |  |
