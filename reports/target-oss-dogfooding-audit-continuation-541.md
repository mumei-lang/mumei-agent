# Target OSS no-LLM dogfooding audit — continuation 541 (batch 542)

Run: 2026-07-23T09:45:19.127316+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/test/abiutilsaux_test.go` | verified |  |
| go | `src/cmd/compile/internal/types2/compiler_internal.go` | verified |  |
| go | `src/cmd/internal/script/state.go` | verified |  |
| go | `src/hash/maphash/maphash.go` | verified |  |
| go | `src/io/fs/walk.go` | verified |  |
| go | `src/math/bits/example_test.go` | verified |  |
| go | `src/net/http/example_filesystem_test.go` | verified |  |
| go | `src/net/rawconn_windows_test.go` | verified |  |
| go | `src/net/tcpsock_plan9.go` | verified |  |
| go | `src/os/exec/example_test.go` | verified |  |
| go | `src/reflect/badlinkname.go` | verified |  |
| go | `src/runtime/arena_test.go` | verified |  |
| go | `src/runtime/tracebackx_test.go` | verified |  |
| go | `src/syscall/syscall_solarisonly.go` | verified |  |
| go | `test/closure1.go` | verified |  |
| go | `test/escape_make_non_const.go` | verified |  |
| go | `test/fixedbugs/bug135.go` | verified |  |
| go | `test/fixedbugs/bug144.go` | verified |  |
| go | `test/fixedbugs/bug495.go` | verified |  |
| go | `test/fixedbugs/bug511.go` | verified |  |
| go | `test/fixedbugs/issue15609.go` | verified |  |
| go | `test/fixedbugs/issue17758.go` | verified |  |
| go | `test/fixedbugs/issue20739.go` | verified |  |
| go | `test/fixedbugs/issue36723.go` | verified |  |
| go | `test/fixedbugs/issue43292.go` | verified |  |
| go | `test/fixedbugs/issue49094.dir/p.go` | verified |  |
| go | `test/fixedbugs/issue78408.go` | verified |  |
| go | `test/fixedbugs/issue80096.go` | verified |  |
| go | `test/typeparam/issue48962.dir/a.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/applyconfiguration/provisioning/v0alpha1/syncjoboptions.go` | verified |  |
| grafana | `apps/provisioning/pkg/quotas/tracker.go` | verified |  |
| grafana | `apps/shorturl/pkg/apis/shorturl/v1beta1/shorturl_schema_gen.go` | verified |  |
| grafana | `packages/grafana-alerting/src/grafana/api/notifications/v0alpha1/mocks/handlers/ReceiverHandlers/replaceReceiverHandler.ts` | verified |  |
| grafana | `packages/grafana-data/src/themes/createColors.ts` | verified |  |
| grafana | `pkg/apis/appplugin/v0alpha1/register.go` | verified |  |
| grafana | `pkg/codegen/jenny_gofmt.go` | verified |  |
| grafana | `pkg/infra/nats/integration_test.go` | verified |  |
| grafana | `pkg/infra/usagestats/noop.go` | verified |  |
| grafana | `pkg/plugins/manager/pipeline/bootstrap/doc.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/ualert/alert_rule_version_guid_mig.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/git/commit_author_test.go` | verified |  |
| grafana | `public/app/features/alerting/unified/mocks/server/handlers/alertmanagers.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/rule-list/components/DataSourceIcon.tsx` | verified |  |
| grafana | `public/app/features/commandPalette/inputMode.ts` | verified |  |
| grafana | `public/app/features/correlations/components/Wizard/types.ts` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/TraceTimelineViewer/TimelineHeaderRow/TimelineViewingLayer.tsx` | verified |  |
| grafana | `public/app/features/expressions/components/SqlExpressions/SqlEditor/SqlEditor.tsx` | verified |  |
| grafana | `public/app/features/query/components/QueryGroup.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/influxdb/components/editor/query/influxql/utils/wrapper.ts` | verified |  |
| grafana | `public/app/plugins/panel/geomap/layers/data/photosLayer.tsx` | verified |  |
