# Target OSS no-LLM dogfooding audit — continuation 397 (batch 398)

Run: 2026-07-23T00:30:41.963306+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/arena/arena.go` | verified |  |
| go | `src/cmd/compile/internal/amd64/versions_test.go` | verified |  |
| go | `src/cmd/compile/internal/devirtualize/pgo_test.go` | verified |  |
| go | `src/cmd/compile/internal/test/constFold_test.go` | verified |  |
| go | `src/cmd/compile/internal/types2/typeparam.go` | verified |  |
| go | `src/cmd/internal/goobj/mkbuiltin.go` | verified |  |
| go | `src/cmd/internal/obj/x86/a.out.go` | verified |  |
| go | `src/go/types/main_test.go` | verified |  |
| go | `src/internal/syscall/unix/fcntl_unix.go` | verified |  |
| go | `src/net/error_plan9.go` | verified |  |
| go | `src/runtime/mem_linux.go` | verified |  |
| go | `src/runtime/synctest_test.go` | verified |  |
| go | `src/runtime/syscall_solaris.go` | verified |  |
| go | `src/syscall/syscall_ptrace_test.go` | verified |  |
| go | `test/abi/more_intstar_input.go` | verified |  |
| go | `test/fixedbugs/bug463.go` | verified |  |
| go | `test/fixedbugs/issue12536.go` | verified |  |
| go | `test/fixedbugs/issue18655.go` | verified |  |
| go | `test/fixedbugs/issue22941.dir/main.go` | verified |  |
| go | `test/fixedbugs/issue29504.go` | verified |  |
| go | `test/fixedbugs/issue31915.go` | verified |  |
| go | `test/fixedbugs/issue63436.go` | verified |  |
| go | `test/typeparam/shape1.go` | verified |  |
| grafana | `apps/dashvalidator/pkg/validator/variables_test.go` | verified |  |
| grafana | `apps/logsdrilldown/pkg/apis/logsdrilldown/v1alpha1/logsdrilldown_object_gen.go` | verified |  |
| grafana | `apps/playlist/pkg/app/conversion.go` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/provisioning/v0alpha1/index.ts` | verified |  |
| grafana | `packages/grafana-sql/src/types.ts` | verified |  |
| grafana | `packages/grafana-test-utils/src/handlers/apis/scope.grafana.app/v0alpha1/handlers.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/TabbedContainer/TabbedContainer.tsx` | verified |  |
| grafana | `pkg/cmd/grafana-cli/runner/runner.go` | verified |  |
| grafana | `pkg/infra/tracing/tracing_test.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/history_test.go` | verified |  |
| grafana | `pkg/services/cloudmigration/gmsclient/gms_client_test.go` | verified |  |
| grafana | `pkg/services/ldap/service/fake.go` | verified |  |
| grafana | `pkg/services/ngalert/writer/prom.go` | verified |  |
| grafana | `pkg/services/org/org.go` | verified |  |
| grafana | `pkg/services/provisioning/dashboards/types.go` | verified |  |
| grafana | `pkg/services/quota/quota.go` | verified |  |
| grafana | `pkg/storage/unified/search/embed/embedder/vertex/embed_dense_test.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/middleware_test.go` | verified |  |
| grafana | `pkg/tsdb/influxdb/influxql/influxql_test.go` | verified |  |
| grafana | `public/app/features/actions/ParamsEditor.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/notificaton-preview/ConnectionLine.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/triage/scene/SummaryStats.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/ControlActionsPopover.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/solo/SoloPanelContext.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/TracePageHeader/SpanGraph/Scrubber.tsx` | verified |  |
| grafana | `public/app/features/transformers/regression/utils.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/dataquery.gen.ts` | verified |  |
