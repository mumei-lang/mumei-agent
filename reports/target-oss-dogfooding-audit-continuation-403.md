# Target OSS no-LLM dogfooding audit — continuation 403 (batch 404)

Run: 2026-07-23T00:47:48.843316+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/go/internal/cfg/cfg.go` | verified |  |
| go | `src/cmd/go/internal/doc/doc.go` | verified |  |
| go | `src/cmd/go/internal/modindex/index_test.go` | verified |  |
| go | `src/cmd/internal/obj/go.go` | verified |  |
| go | `src/cmd/link/doc.go` | verified |  |
| go | `src/crypto/internal/fips140/nistec/generate.go` | verified |  |
| go | `src/internal/abi/rangefuncconsts.go` | verified |  |
| go | `src/net/net_test.go` | verified |  |
| go | `src/net/pipe.go` | verified |  |
| go | `src/runtime/pprof/pe.go` | verified |  |
| go | `src/runtime/race/race_unix_test.go` | verified |  |
| go | `src/simd/archsimd/slicepart_128.go` | verified |  |
| go | `src/syscall/zsyscall_freebsd_arm64.go` | verified |  |
| go | `test/fixedbugs/bug013.go` | verified |  |
| go | `test/fixedbugs/issue18419.dir/test.go` | verified |  |
| go | `test/fixedbugs/issue30862.dir/a/a.go` | verified |  |
| go | `test/fixedbugs/issue49016.dir/e.go` | verified |  |
| go | `test/fixedbugs/issue5614.dir/rethinkgo.go` | verified |  |
| go | `test/fixedbugs/issue77635b.go` | verified |  |
| go | `test/typeparam/issue47514c.go` | verified |  |
| go | `test/typeparam/mincheck.dir/main.go` | verified |  |
| go | `test/typeparam/stringerimp.dir/a.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v0alpha1/templategroup_ext.go` | verified |  |
| grafana | `packages/grafana-flamegraph/src/index.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/SecretInput/SecretInput.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/VizLayout/VizLayout.tsx` | verified |  |
| grafana | `pkg/api/dtos/plugins.go` | verified |  |
| grafana | `pkg/api/quota.go` | verified |  |
| grafana | `pkg/registry/apis/iam/display/search.go` | verified |  |
| grafana | `pkg/services/cloudmigration/gmsclient/gms_client.go` | verified |  |
| grafana | `pkg/services/ngalert/remote/crypto.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/pluginsettings/service/service_test.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/nats_discovery_mig.go` | verified |  |
| grafana | `pkg/storage/unified/resource/usagestats/metrics.go` | verified |  |
| grafana | `pkg/tests/apis/iam/teambinding/team_binding_integration_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/jobs/exportjob_test.go` | verified |  |
| grafana | `pkg/tsdb/grafana-postgresql-datasource/testutil_test.go` | verified |  |
| grafana | `pkg/tsdb/mysql/macros_test.go` | verified |  |
| grafana | `public/app/core/hooks/useBusEvent.ts` | verified |  |
| grafana | `public/app/core/utils/dag.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/receivers/editor/definition.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/labels/LabelsField.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-list/extensions/EnrichmentDrawerExtension.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/state/actions.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/utils/notifier-types.ts` | verified |  |
| grafana | `public/app/features/dashboard/components/SaveDashboard/SaveDashboardDrawer.tsx` | verified |  |
| grafana | `public/app/features/dashboard/components/ShareModal/SharePublicDashboard/CreatePublicDashboard/AcknowledgeCheckboxes.tsx` | verified |  |
| grafana | `public/app/features/datasources/api.ts` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/TraceTimelineViewer/SpanDetail/ShareSpanButton.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/LogsQueryBuilder/OrderBySection.tsx` | verified |  |
