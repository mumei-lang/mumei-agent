# Target OSS no-LLM dogfooding audit — continuation 367 (batch 368)

Run: 2026-07-22T22:06:01.591421+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/addr2line/addr2line_test.go` | verified |  |
| go | `src/compress/bzip2/bzip2_test.go` | verified |  |
| go | `src/internal/poll/fd_mutex.go` | verified |  |
| go | `src/internal/profilerecord/profilerecord.go` | verified |  |
| go | `src/internal/strconv/atof.go` | verified |  |
| go | `src/net/http/httputil/httputil.go` | verified |  |
| go | `src/os/tempfile_test.go` | verified |  |
| go | `src/runtime/mkpreempt.go` | verified |  |
| go | `src/runtime/security_test.go` | verified |  |
| go | `test/fixedbugs/bug383.go` | verified |  |
| go | `test/fixedbugs/issue33308.go` | verified |  |
| go | `test/fixedbugs/issue34577.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue53635.go` | verified |  |
| go | `test/fixedbugs/issue5957.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue6703f.go` | verified |  |
| go | `test/typeparam/issue48094b.go` | verified |  |
| go | `test/typeparam/issue50121.dir/a.go` | verified |  |
| go | `test/typeswitch2.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v2alpha1/doc.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/externalgroupmapping_client_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/applyconfiguration/provisioning/v0alpha1/job.go` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/notifications.alerting/v0alpha1/endpoints.gen.ts` | verified |  |
| grafana | `packages/grafana-o11y-ds-frontend/src/NodeGraph/NodeGraphSettings.tsx` | verified |  |
| grafana | `packages/grafana-sql/src/components/ConfirmModal.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/internal/index.ts` | verified |  |
| grafana | `pkg/apimachinery/validation/validation_test.go` | verified |  |
| grafana | `pkg/components/loki/logproto/timestamp.go` | verified |  |
| grafana | `pkg/expr/ml_test.go` | verified |  |
| grafana | `pkg/infra/tracing/tracing_config_test.go` | verified |  |
| grafana | `pkg/registry/apis/preferences/legacy/migrator.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/webhooks/render.go` | verified |  |
| grafana | `pkg/services/apiserver/service.go` | verified |  |
| grafana | `pkg/services/live/telemetry/telegraf/convert.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/alert_broadcast.go` | verified |  |
| grafana | `pkg/services/secrets/manager/metrics.go` | verified |  |
| grafana | `pkg/services/ssosettings/ssosettings.go` | verified |  |
| grafana | `pkg/storage/unified/resource/client_mock.go` | verified |  |
| grafana | `pkg/storage/unified/resource/hooks.go` | verified |  |
| grafana | `pkg/storage/unified/sql/sqltemplate/dialect_postgresql.go` | verified |  |
| grafana | `public/app/core/components/OptionsUI/registry.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/notification-policies/components/Modals.tsx` | verified |  |
| grafana | `public/app/features/connections/tabs/ConnectData/NoAccessModal/NoAccessModal.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelDataPane/EmptyTransformationsMessage.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/StackedEditor/StackedItem.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/types/DashboardLayoutItem.ts` | verified |  |
| grafana | `public/app/features/explore/RichHistory/RichHistoryAddToLibrary.tsx` | verified |  |
| grafana | `public/app/features/explore/RichHistory/RichHistoryContainer.tsx` | verified |  |
| grafana | `public/app/features/scopes/dashboards/ContextualNavigationPaneToggle.tsx` | verified |  |
| grafana | `public/app/features/support-bundles/state/reducers.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/components/QueryEditor/MetricsQueryEditor/SQLCodeEditor.tsx` | verified |  |
