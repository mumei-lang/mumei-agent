# Target OSS no-LLM dogfooding audit — continuation 446 (batch 447)

Run: 2026-07-23T02:52:54.743390+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/api/boring_test.go` | verified |  |
| go | `src/cmd/cgo/internal/test/issue8756/issue8756.go` | verified |  |
| go | `src/cmd/compile/internal/riscv64/ggen.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/html.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/rewriteAMD64splitload.go` | verified |  |
| go | `src/cmd/compile/internal/walk/compare.go` | verified |  |
| go | `src/cmd/link/internal/mips/l.go` | verified |  |
| go | `src/crypto/internal/boring/rsa.go` | verified |  |
| go | `src/crypto/rand/text_test.go` | verified |  |
| go | `src/go/types/resolver_test.go` | verified |  |
| go | `src/internal/goos/zgoos_illumos.go` | verified |  |
| go | `src/internal/poll/sockopt_windows.go` | verified |  |
| go | `src/log/slog/example_wrap_test.go` | verified |  |
| go | `src/runtime/runtime_mmap_test.go` | verified |  |
| go | `src/runtime/security_linux.go` | verified |  |
| go | `test/closure2.go` | verified |  |
| go | `test/codegen/generics.go` | verified |  |
| go | `test/fixedbugs/bug258.go` | verified |  |
| go | `test/fixedbugs/issue22198.go` | verified |  |
| go | `test/fixedbugs/issue30243.go` | verified |  |
| go | `test/interface/embed1.dir/embed1.go` | verified |  |
| go | `test/typeparam/issue47901.go` | verified |  |
| go | `test/typeparam/structinit.go` | verified |  |
| go | `test/typeparam/value.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v0alpha1/receiver_codec_gen.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v1/dashboard_schema_gen.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/globalrole_codec_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/applyconfiguration/provisioning/v0alpha1/bitbucketrepositoryconfig.go` | verified |  |
| grafana | `apps/quotas/pkg/apis/quotas/v0alpha1/getusage_request_params_object_gen.go` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/logsdrilldown/v1alpha1/baseAPI.ts` | verified |  |
| grafana | `pkg/apis/userstorage/v0alpha1/zz_generated.deepcopy.go` | verified |  |
| grafana | `pkg/models/theme.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/repository_fields_test.go` | verified |  |
| grafana | `pkg/registry/apps/alerting/notifications/inhibitionrule/conversions.go` | verified |  |
| grafana | `pkg/services/auth/authtest/external_session_store_mock.go` | verified |  |
| grafana | `pkg/services/authn/clients/password_test.go` | verified |  |
| grafana | `pkg/services/dashboardversion/model.go` | verified |  |
| grafana | `pkg/services/live/telemetry/telegraf/convert_test.go` | verified |  |
| grafana | `pkg/tests/apis/iam/user/user_test.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/folder-actions/FolderActionsButton.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/receivers/grafanaAppReceivers/onCall/useOnCallIntegration.tsx` | verified |  |
| grafana | `public/app/features/commandPalette/actions/useExtensionActions.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/VizPanelHeaderActions.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/utils/dashboardDsRefs.ts` | verified |  |
| grafana | `public/app/features/dashboard/dashgrid/DashboardEmpty/DashboardEmptyHooks.ts` | verified |  |
| grafana | `public/app/features/logs/components/useAttributesExtensionLinks.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/language/monarch/linkedTokenBuilder.ts` | verified |  |
| grafana | `public/app/plugins/panel/candlestick/module.tsx` | verified |  |
| grafana | `public/app/plugins/panel/candlestick/utils.ts` | verified |  |
| grafana | `public/app/plugins/panel/geomap/style/markers.ts` | verified |  |
