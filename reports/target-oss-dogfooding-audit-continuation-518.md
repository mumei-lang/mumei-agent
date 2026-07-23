# Target OSS no-LLM dogfooding audit — continuation 518 (batch 519)

Run: 2026-07-23T07:49:02.340006+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/dwarfgen/dwinl.go` | verified |  |
| go | `src/cmd/go/internal/modload/mvs.go` | verified |  |
| go | `src/crypto/internal/fips140/edwards25519/scalar_alias_test.go` | verified |  |
| go | `src/crypto/sha256/sha256.go` | verified |  |
| go | `src/debug/macho/file_test.go` | verified |  |
| go | `src/encoding/base32/example_test.go` | verified |  |
| go | `src/flag/example_flagset_test.go` | verified |  |
| go | `src/image/draw/clip_test.go` | verified |  |
| go | `src/internal/runtime/syscall/windows/defs_windows_386.go` | verified |  |
| go | `src/internal/testenv/noopt.go` | verified |  |
| go | `src/regexp/find_test.go` | verified |  |
| go | `src/runtime/preempt_xreg.go` | verified |  |
| go | `src/simd/midway_wasm.go` | verified |  |
| go | `src/syscall/syscall_darwin_amd64.go` | verified |  |
| go | `test/codegen/spills.go` | verified |  |
| go | `test/fixedbugs/bug308.go` | verified |  |
| go | `test/fixedbugs/issue15141.go` | verified |  |
| go | `test/fixedbugs/issue28078.go` | verified |  |
| go | `test/fixedbugs/issue30659.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue49611.go` | verified |  |
| go | `test/fixedbugs/issue51475.go` | verified |  |
| go | `test/fixedbugs/issue7366.go` | verified |  |
| go | `test/ken/strvar.go` | verified |  |
| go | `test/typeparam/issue47258.go` | verified |  |
| go | `test/typeparam/issue49241.dir/main.go` | verified |  |
| go | `test/typeparam/sliceimp.dir/main.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v1beta1/templategroup_ext.go` | verified |  |
| grafana | `pkg/registry/apis/appplugin/register_test.go` | verified |  |
| grafana | `pkg/registry/apis/preferences/validate_test.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/informer/informer.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/store_mock.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/timeout_test.go` | verified |  |
| grafana | `pkg/services/accesscontrol/cacheutils.go` | verified |  |
| grafana | `pkg/services/accesscontrol/database/database_test.go` | verified |  |
| grafana | `pkg/services/ngalert/eval/eval_bench_test.go` | verified |  |
| grafana | `pkg/services/publicdashboards/internal/commands/generate_datasources/generate.go` | verified |  |
| grafana | `pkg/storage/unified/search/bleve_snapshot_observability_test.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/notification-policies/RoutesMatchingFiltersContext.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/GrafanaEvaluationBehavior.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/variables/utils.ts` | verified |  |
| grafana | `public/app/features/dashboard/utils/appendExtensionsToPanelMenu.ts` | verified |  |
| grafana | `public/app/features/dimensions/editors/ResourceDimensionEditor.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/TracePageHeader/mocks.ts` | verified |  |
| grafana | `public/app/features/logs/components/LogLabels.tsx` | verified |  |
| grafana | `public/app/features/panel/components/VizTypePicker/VizTypePicker.tsx` | verified |  |
| grafana | `public/app/features/templating/dataMacros.ts` | verified |  |
| grafana | `public/app/features/visualization/data-hover/DataHoverTabs.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/mysql/mySqlMetaQuery.ts` | verified |  |
| grafana | `public/app/plugins/panel/geomap/suggestions.ts` | verified |  |
| grafana | `public/test/mocks/datasource_srv.ts` | verified |  |
