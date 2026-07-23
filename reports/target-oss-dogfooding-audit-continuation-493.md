# Target OSS no-LLM dogfooding audit — continuation 493 (batch 494)

Run: 2026-07-23T06:30:58.495377+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/test/sigprocmask.go` | verified |  |
| go | `src/cmd/go/internal/cache/cache.go` | verified |  |
| go | `src/cmd/internal/obj/arm64/inst_gen.go` | verified |  |
| go | `src/context/example_test.go` | verified |  |
| go | `src/crypto/internal/rand/rand_fips140v1.26.go` | verified |  |
| go | `src/crypto/rc4/rc4_test.go` | verified |  |
| go | `src/crypto/x509/example_test.go` | verified |  |
| go | `src/internal/poll/fd_opendir_darwin.go` | verified |  |
| go | `src/internal/poll/file_plan9.go` | verified |  |
| go | `src/math/hypot_noasm.go` | verified |  |
| go | `src/math/rand/regress_test.go` | verified |  |
| go | `src/os/pidfd_linux_test.go` | verified |  |
| go | `test/fixedbugs/bug133.go` | verified |  |
| go | `test/fixedbugs/bug160.dir/y.go` | verified |  |
| go | `test/fixedbugs/bug160.go` | verified |  |
| go | `test/fixedbugs/bug250.go` | verified |  |
| go | `test/fixedbugs/issue10441.go` | verified |  |
| go | `test/fixedbugs/issue41247.go` | verified |  |
| go | `test/interface/convert.go` | verified |  |
| go | `test/mapclear.go` | verified |  |
| go | `test/slice3err.go` | verified |  |
| grafana | `apps/advisor/pkg/app/checks/instancechecks/pinned_version_step.go` | verified |  |
| grafana | `apps/example/plugin/src/generated/examplekind/v1alpha1/types.metadata.gen.ts` | verified |  |
| grafana | `apps/live/pkg/apis/live/v1alpha1/getsomething_request_params_types_gen.go` | verified |  |
| grafana | `packages/grafana-data/src/types/datasource.ts` | verified |  |
| grafana | `packages/grafana-schema/src/veneer/librarypanel.types.ts` | verified |  |
| grafana | `pkg/registry/apis/dashboard/legacy/types.go` | verified |  |
| grafana | `pkg/registry/apis/iam/models.go` | verified |  |
| grafana | `pkg/registry/apps/alerting/rules/alertrule/storage.go` | verified |  |
| grafana | `pkg/services/ldap/ldap.go` | verified |  |
| grafana | `pkg/services/ngalert/api/prometheus/api_prometheus_test.go` | verified |  |
| grafana | `pkg/services/ngalert/folder_consumer_test.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/test_helper.go` | verified |  |
| grafana | `pkg/storage/legacysql/dualwrite/storage_service.go` | verified |  |
| grafana | `pkg/storage/unified/apistore/managed.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/models/cloudwatch_query_test.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/models/logs_query.go` | verified |  |
| grafana | `public/app/core/components/Form/Form.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/receivers/form/util.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/NotificationsStep.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rules/state-history/ErrorMessageRow.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/mutation-api/commands/removeTab.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/sharing/ExportButton/ExportButton.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/keyboard-shortcuts.tsx` | verified |  |
| grafana | `public/app/features/home/DashboardTabs/StarredDashboardsTab.tsx` | verified |  |
| grafana | `public/app/features/plugins/extensions/usePluginComponent.tsx` | verified |  |
| grafana | `public/app/features/provisioning/Connection/ConnectionStatusBadge.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/components/shared/DataSources/Search.tsx` | verified |  |
| grafana | `public/app/plugins/panel/table/cells/MarkdownCellOptionsEditor.tsx` | verified |  |
| grafana | `public/app/plugins/panel/timeseries/plugins/annotations/AnnotationTooltipHeaderCloseIcon.tsx` | verified |  |
