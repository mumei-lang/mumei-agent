# Target OSS no-LLM dogfooding audit — continuation 474 (batch 475)

Run: 2026-07-23T04:50:50.423318+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/test/issue26743.go` | verified |  |
| go | `src/cmd/compile/internal/arm64/simdssa.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/uses.go` | verified |  |
| go | `src/cmd/link/elf_test.go` | verified |  |
| go | `src/debug/dwarf/type.go` | verified |  |
| go | `src/go/types/pointer.go` | verified |  |
| go | `src/internal/sysinfo/cpuinfo_stub.go` | verified |  |
| go | `src/net/hook_unix.go` | verified |  |
| go | `src/net/internal/socktest/main_test.go` | verified |  |
| go | `src/runtime/os_linux_novdso.go` | verified |  |
| go | `src/strconv/import_test.go` | verified |  |
| go | `src/syscall/syscall_dragonfly.go` | verified |  |
| go | `test/ddd2.go` | verified |  |
| go | `test/fixedbugs/bug057.go` | verified |  |
| go | `test/fixedbugs/bug163.go` | verified |  |
| go | `test/fixedbugs/bug183.go` | verified |  |
| go | `test/fixedbugs/bug474.go` | verified |  |
| go | `test/fixedbugs/issue10700.dir/other.go` | verified |  |
| go | `test/fixedbugs/issue19658.go` | verified |  |
| go | `test/fixedbugs/issue32901.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue4326.dir/p2.go` | verified |  |
| go | `test/fixedbugs/issue4370.go` | verified |  |
| go | `test/fixedbugs/issue44330.dir/a.go` | verified |  |
| go | `test/typeparam/issue51219.dir/a.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/teambinding_schema_gen.go` | verified |  |
| grafana | `packages/grafana-data/src/types/linkTarget.ts` | verified |  |
| grafana | `packages/grafana-schema/src/veneer/dashboard.types.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Link/TextLink.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/utils/typeahead.ts` | verified |  |
| grafana | `pkg/plugins/codegen/pfs/decl.go` | verified |  |
| grafana | `pkg/registry/apis/secret/encryption/manager/manager_test.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/merge/merge_test.go` | verified |  |
| grafana | `pkg/services/query/models.go` | verified |  |
| grafana | `pkg/services/queryhistory/queryhistory_unstar_test.go` | verified |  |
| grafana | `pkg/services/queryhistory/writers.go` | verified |  |
| grafana | `pkg/services/store/storage_sql.go` | verified |  |
| grafana | `pkg/services/store/system_users_mock.go` | verified |  |
| grafana | `pkg/storage/unified/sql/db/migrations/deletion_markers.go` | verified |  |
| grafana | `pkg/tests/apis/alerting/notifications/routingtree/imported_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/nats/helpers_test.go` | verified |  |
| grafana | `public/app/core/components/OwnerReferences/OwnerReference.tsx` | verified |  |
| grafana | `public/app/core/components/Signup/SignupPage.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/edit-pane/ElementEditPane.tsx` | verified |  |
| grafana | `public/app/features/datasources/components/CloudInfoBox.tsx` | verified |  |
| grafana | `public/app/features/logs/components/panel/LogLineMessage.tsx` | verified |  |
| grafana | `public/app/features/provisioning/hooks/useGetRepositoryFolders.ts` | verified |  |
| grafana | `public/app/features/query/state/mocks/mockDataSource.ts` | verified |  |
| grafana | `public/app/features/transformers/timeSeriesTable/timeSeriesTableTransformer.ts` | verified |  |
| grafana | `public/app/plugins/datasource/grafana-testdata-datasource/components/SimulationSchemaForm.tsx` | verified |  |
| grafana | `public/app/plugins/panel/canvas/module.tsx` | verified |  |
