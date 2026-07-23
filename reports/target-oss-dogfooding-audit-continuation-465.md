# Target OSS no-LLM dogfooding audit — continuation 465 (batch 466)

Run: 2026-07-23T04:11:35.003286+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/link/internal/ld/pe.go` | verified |  |
| go | `src/go/internal/gccgoimporter/gccgoinstallation.go` | verified |  |
| go | `src/internal/abi/iface.go` | verified |  |
| go | `src/internal/goexperiment/exp_newinliner_on.go` | verified |  |
| go | `src/internal/runtime/syscall/windows/syscall_windows.go` | verified |  |
| go | `src/net/http/cgi/integration_test.go` | verified |  |
| go | `src/net/netip/uint128_test.go` | verified |  |
| go | `src/os/signal/signal_windows_test.go` | verified |  |
| go | `src/runtime/pprof/runtime.go` | verified |  |
| go | `src/runtime/wincallback.go` | verified |  |
| go | `src/sync/export_test.go` | verified |  |
| go | `src/testing/iotest/reader.go` | verified |  |
| go | `test/fixedbugs/bug055.go` | verified |  |
| go | `test/fixedbugs/issue19467.dir/mysync.go` | verified |  |
| go | `test/fixedbugs/issue33062.go` | verified |  |
| go | `test/fixedbugs/issue34503.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue4085a.go` | verified |  |
| go | `test/fixedbugs/issue44330.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue54220.go` | verified |  |
| go | `test/newexpr.go` | verified |  |
| go | `test/typeparam/issue48191.go` | verified |  |
| go | `test/typeparam/issue50598.dir/a0.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/conversion/conversion_data_loss_detection_test.go` | verified |  |
| grafana | `apps/dashvalidator/pkg/apis/dashvalidator/v1alpha1/createcheck_response_body_types_gen.go` | verified |  |
| grafana | `apps/example/pkg/apis/example/v1alpha1/getother_response_types_gen.go` | verified |  |
| grafana | `packages/grafana-alerting/src/grafana/notificationPolicies/utils.ts` | verified |  |
| grafana | `packages/grafana-alerting/src/grafana/rules/utils/labels.ts` | verified |  |
| grafana | `packages/grafana-data/src/transformations/matchers/valueMatchers/numericMatchers.ts` | verified |  |
| grafana | `packages/grafana-runtime/src/services/pluginExtensions/usePluginComponents.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/BigValue/BigValue.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Modal/ModalTabContent.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/TableNG/types.ts` | verified |  |
| grafana | `pkg/generated/clientset/versioned/typed/service/v0alpha1/doc.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/deleteresources/worker.go` | verified |  |
| grafana | `pkg/registry/apps/alerting/notifications/receiver/type.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/routes/service_test.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/pluginsettings/fake.go` | verified |  |
| grafana | `pkg/services/team/teamtest/team.go` | verified |  |
| grafana | `pkg/tsdb/influxdb/fsql/macro.go` | verified |  |
| grafana | `public/app/core/history/richHistoryStorageProvider.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rules/RuleHealth.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/mocks/server/handlers/provisioning.ts` | verified |  |
| grafana | `public/app/features/annotations/executeAnnotationQuery.ts` | verified |  |
| grafana | `public/app/features/browse-dashboards/components/RecentlyDeletedEmptyState.tsx` | verified |  |
| grafana | `public/app/features/canvas/elements/metricValue.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/sharing/ShareLinkTab.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/settings/SpanBarSettings.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/mocks/cloudwatch-sql-test-data/multiLineFullQuery.ts` | verified |  |
| grafana | `public/app/plugins/panel/canvas/editor/layer/layerEditor.tsx` | verified |  |
| grafana | `public/app/plugins/panel/geomap/module.tsx` | verified |  |
