# Target OSS no-LLM dogfooding audit — continuation 383 (batch 384)

Run: 2026-07-22T23:43:27.103334+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ssa/looprotate.go` | verified |  |
| go | `src/cmd/internal/pkgpattern/pkgpattern.go` | verified |  |
| go | `src/internal/pkgbits/reloc.go` | verified |  |
| go | `src/internal/testhash/hash.go` | verified |  |
| go | `src/net/http/routing_index_test.go` | verified |  |
| go | `src/net/splice_linux_test.go` | verified |  |
| go | `src/runtime/cgo/handle_test.go` | verified |  |
| go | `src/runtime/mem_plan9.go` | verified |  |
| go | `src/simd/archsimd/_gen/unify/unify.go` | verified |  |
| go | `test/convlit1.go` | verified |  |
| go | `test/fixedbugs/bug054.go` | verified |  |
| go | `test/fixedbugs/bug083.dir/bug1.go` | verified |  |
| go | `test/fixedbugs/issue13266.go` | verified |  |
| go | `test/fixedbugs/issue43633.dir/main.go` | verified |  |
| go | `test/fixedbugs/issue6671.go` | verified |  |
| go | `test/gcgort.go` | verified |  |
| go | `test/index0.go` | verified |  |
| go | `test/rotate2.go` | verified |  |
| go | `test/typeparam/issue48185a.dir/p_test.go` | verified |  |
| grafana | `apps/plugins/plugin/src/generated/meta/v0alpha1/types.metadata.gen.ts` | verified |  |
| grafana | `packages/grafana-alerting/src/grafana/api/notifications/v0alpha1/mocks/fakes/Receivers.ts` | verified |  |
| grafana | `packages/grafana-data/src/utils/labels.ts` | verified |  |
| grafana | `packages/grafana-sql/src/components/query-editor-raw/QueryToolbox.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/InteractiveTable/Expander/index.tsx` | verified |  |
| grafana | `pkg/api/dataproxy.go` | verified |  |
| grafana | `pkg/api/folder_bench_test.go` | verified |  |
| grafana | `pkg/expr/mathexp/types_test.go` | verified |  |
| grafana | `pkg/infra/features/baggage_test.go` | verified |  |
| grafana | `pkg/plugins/pluginscdn/url_constructor.go` | verified |  |
| grafana | `pkg/registry/apis/datasource/connections.go` | verified |  |
| grafana | `pkg/services/accesscontrol/acimpl/basic_role_db_seed_test.go` | verified |  |
| grafana | `pkg/services/ldap/ldap_test.go` | verified |  |
| grafana | `pkg/services/ngalert/api/hcl/hcl.go` | verified |  |
| grafana | `pkg/services/screenshot/screenshot_test.go` | verified |  |
| grafana | `pkg/setting/setting_feature_toggles_test.go` | verified |  |
| grafana | `pkg/storage/unified/sql/db/dbimpl/dbimpl_test.go` | verified |  |
| grafana | `pkg/tests/apis/dashboard/variables_test.go` | verified |  |
| grafana | `pkg/tsdb/grafana-testdata-datasource/scenarios.go` | verified |  |
| grafana | `pkg/tsdb/influxdb/models/query.go` | verified |  |
| grafana | `pkg/tsdb/loki/loki_bench_test.go` | verified |  |
| grafana | `public/app/core/components/NestedFolderPicker/NestedFolderList.tsx` | verified |  |
| grafana | `public/app/core/components/RolePicker/RoleMenuGroupsSection.tsx` | verified |  |
| grafana | `public/app/core/components/RolePicker/api.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/notifications/NotificationDetailActions.tsx` | verified |  |
| grafana | `public/app/features/invites/state/reducers.ts` | verified |  |
| grafana | `public/app/features/logs/components/panel/processing.ts` | verified |  |
| grafana | `public/app/features/plugins/importPanelPlugin.ts` | verified |  |
| grafana | `public/app/plugins/datasource/influxdb/datasource.ts` | verified |  |
| grafana | `public/app/plugins/datasource/mixed/MixedDataSource.ts` | verified |  |
| grafana | `public/app/plugins/panel/timeseries/plugins/annotations/useAnnotations.tsx` | verified |  |
