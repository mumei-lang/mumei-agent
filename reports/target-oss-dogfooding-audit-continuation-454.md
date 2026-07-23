# Target OSS no-LLM dogfooding audit — continuation 454 (batch 455)

Run: 2026-07-23T03:31:36.363377+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/inline/inlheur/pstate_string.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/_gen/ARM64Ops.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/config.go` | verified |  |
| go | `src/cmd/internal/bio/buf_nommap.go` | verified |  |
| go | `src/cmd/internal/objabi/util.go` | verified |  |
| go | `src/cmd/link/internal/amd64/l.go` | verified |  |
| go | `src/crypto/sha1/example_test.go` | verified |  |
| go | `src/go/internal/gcimporter/support.go` | verified |  |
| go | `src/internal/syscall/unix/pidfd_linux.go` | verified |  |
| go | `src/net/http/transport_default_other.go` | verified |  |
| go | `src/runtime/debug/heapdump_test.go` | verified |  |
| go | `src/runtime/os3_plan9.go` | verified |  |
| go | `src/syscall/js/func.go` | verified |  |
| go | `src/syscall/types_windows_386.go` | verified |  |
| go | `test/fixedbugs/bug181.go` | verified |  |
| go | `test/fixedbugs/bug511.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue12226.go` | verified |  |
| go | `test/fixedbugs/issue13248.go` | verified |  |
| go | `test/fixedbugs/issue25897b.go` | verified |  |
| go | `test/fixedbugs/issue30116.go` | verified |  |
| go | `test/fixedbugs/issue44330.go` | verified |  |
| go | `test/fixedbugs/issue44830.go` | verified |  |
| go | `test/ken/cplx0.go` | verified |  |
| go | `test/switch.go` | verified |  |
| grafana | `apps/logsdrilldown/plugin/src/generated/logsdrilldowndefaults/v1alpha1/types.status.gen.ts` | verified |  |
| grafana | `apps/provisioning/pkg/controller/connection_status_test.go` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/dashboard/v0alpha1/endpoints.gen.ts` | verified |  |
| grafana | `packages/grafana-data/src/transformations/transformers/nulls/nullInsertThreshold.ts` | verified |  |
| grafana | `packages/grafana-runtime/src/services/pluginSettings/refetchPluginSettings.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/BarGauge/BarGauge.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Collapse/CollapsableSection.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Forms/RadioButtonGroup/RadioButton.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Monaco/theme.ts` | verified |  |
| grafana | `pkg/infra/httpclient/httpclientprovider/prometheus_metrics_middleware.go` | verified |  |
| grafana | `pkg/registry/apis/datasource/migrator/migrator.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/resources/clients_mock.go` | verified |  |
| grafana | `pkg/services/dashboards/dashboardaccess/dashboard_access.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/dispatch_timer_test.go` | verified |  |
| grafana | `pkg/services/query/query_service_mock.go` | verified |  |
| grafana | `pkg/services/rendering/rendering_test.go` | verified |  |
| grafana | `pkg/services/supportbundles/bundleregistry/service_test.go` | verified |  |
| grafana | `pkg/storage/unified/search/embed/pending_delete.go` | verified |  |
| grafana | `pkg/storage/unified/search/lock_cdk_backend_options.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/foldermetadata/export_git_test.go` | verified |  |
| grafana | `public/app/core/components/OptionsUI/DashboardPicker.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/version-history/VersionHistoryHeader.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/TraceTimelineViewer/SpanDetail/AccordionCategorizedKeyValues.tsx` | verified |  |
| grafana | `public/app/features/panel/components/PanelPluginError.tsx` | verified |  |
| grafana | `public/app/features/provisioning/hooks/useProvisionedResourceDrawerHandlers.ts` | verified |  |
| grafana | `public/app/plugins/panel/logstable/constants.ts` | verified |  |
