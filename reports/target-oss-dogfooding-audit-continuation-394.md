# Target OSS no-LLM dogfooding audit — continuation 394 (batch 395)

Run: 2026-07-23T00:25:20.755334+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/test/setgid2_linux.go` | verified |  |
| go | `src/cmd/cgo/internal/test/test26213.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/branchelim_test.go` | verified |  |
| go | `src/cmd/internal/obj/arm64/asm_arm64_test.go` | verified |  |
| go | `src/embed/embed.go` | verified |  |
| go | `src/internal/abi/map.go` | verified |  |
| go | `src/internal/cpu/cpu_x86_test.go` | verified |  |
| go | `src/internal/strconv/uscale.go` | verified |  |
| go | `src/math/cmplx/huge_test.go` | verified |  |
| go | `src/net/cgo_linux.go` | verified |  |
| go | `src/runtime/export_mmap_test.go` | verified |  |
| go | `src/syscall/route_bsd.go` | verified |  |
| go | `src/text/template/parse/lex.go` | verified |  |
| go | `test/cannotassign.go` | verified |  |
| go | `test/convert3.go` | verified |  |
| go | `test/escape_unique.go` | verified |  |
| go | `test/fixedbugs/bug467.dir/p3.go` | verified |  |
| go | `test/fixedbugs/issue29919.dir/main.go` | verified |  |
| go | `test/fixedbugs/issue4517a.go` | verified |  |
| go | `test/fixedbugs/issue52278.go` | verified |  |
| go | `test/fixedbugs/issue6406.go` | verified |  |
| go | `test/fixedbugs/issue8047b.go` | verified |  |
| go | `test/typeparam/issue54225.go` | verified |  |
| go | `test/typeparam/mdempsky/12.dir/main.go` | verified |  |
| grafana | `apps/alerting/rules/pkg/apis/alerting/v0alpha1/createsearchrules_request_body_types_gen.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v1/register.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v26_test.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v7_test.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/client_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/connection/extra_mock.go` | verified |  |
| grafana | `packages/grafana-runtime/src/services/pluginExtensions/getObservablePluginLinks.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/PluginSignatureBadge/PluginSignatureBadge.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Sidebar/useSidebarClickAway.ts` | verified |  |
| grafana | `pkg/api/login_oauth_test.go` | verified |  |
| grafana | `pkg/apimachinery/errutil/template.go` | verified |  |
| grafana | `pkg/cmd/grafana-cli/commands/commandstest/fake_ioutil.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/webhooks/pullrequest/blobstore_client_mock.go` | verified |  |
| grafana | `pkg/services/secrets/migrator/migrator.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/db_file_storage.go` | verified |  |
| grafana | `pkg/storage/unified/migrations/enterprise_testcases_test.go` | verified |  |
| grafana | `pkg/storage/unified/sql/list_iterator_test.go` | verified |  |
| grafana | `pkg/util/xorm/session_cols.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rules/RuleStats.tsx` | verified |  |
| grafana | `public/app/features/canvas/elements/icon.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/sharing/ShareSnapshotTab.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/TraceTimelineViewer/SpanDetail/index.tsx` | verified |  |
| grafana | `public/app/features/explore/mocks/makeLogs.ts` | verified |  |
| grafana | `public/app/features/provisioning/File/FileStatusPage.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/components/QueryEditor/LogsQueryEditor/code-editors/SQLCodeEditor.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/components/shared/DataSources/DataSourcesSelector.tsx` | verified |  |
