# Target OSS no-LLM dogfooding audit — continuation 494 (batch 495)

Run: 2026-07-23T06:32:46.103318+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/compare/compare.go` | verified |  |
| go | `src/cmd/compile/internal/walk/select.go` | verified |  |
| go | `src/cmd/go/internal/base/error_notunix.go` | verified |  |
| go | `src/crypto/md5/md5.go` | verified |  |
| go | `src/image/png/reader_test.go` | verified |  |
| go | `src/internal/cgrouptest/cgrouptest_linux_test.go` | verified |  |
| go | `src/internal/trace/tracev2/events_test.go` | verified |  |
| go | `src/mime/grammar.go` | verified |  |
| go | `src/net/http/method.go` | verified |  |
| go | `src/net/http/request_test.go` | verified |  |
| go | `src/net/packetconn_test.go` | verified |  |
| go | `src/os/stat_js.go` | verified |  |
| go | `src/os/user/user.go` | verified |  |
| go | `src/runtime/syscall_test.go` | verified |  |
| go | `src/syscall/zsyscall_plan9_386.go` | verified |  |
| go | `src/syscall/zsysnum_openbsd_amd64.go` | verified |  |
| go | `test/escape_sync_atomic.go` | verified |  |
| go | `test/fixedbugs/bug225.go` | verified |  |
| go | `test/fixedbugs/bug377.dir/one.go` | verified |  |
| go | `test/fixedbugs/issue18393.go` | verified |  |
| go | `test/fixedbugs/issue29870.go` | verified |  |
| go | `test/fixedbugs/issue32680b.go` | verified |  |
| go | `test/typeparam/issue51250a.dir/a.go` | verified |  |
| grafana | `apps/dashboard/tshack/variable_v2beta1_spec_gen.ts` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/team_getteammembers_response_object_types_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/clientset/versioned/typed/provisioning/v0alpha1/connection.go` | verified |  |
| grafana | `apps/scope/pkg/apis/scope/v0alpha1/register.go` | verified |  |
| grafana | `packages/grafana-runtime/src/services/logging/registry.ts` | verified |  |
| grafana | `pkg/api/dashboard_permission.go` | verified |  |
| grafana | `pkg/registry/backgroundsvcs/adapter/manager_test.go` | verified |  |
| grafana | `pkg/services/cloudmigration/cloudmigrationimpl/xorm_store.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/legacy_storage/v1/model_test.go` | verified |  |
| grafana | `pkg/services/ngalert/state/historian/prometheus.go` | verified |  |
| grafana | `pkg/services/provisioning/alerting/contact_point_types_test.go` | verified |  |
| grafana | `pkg/services/ssosettings/ssosettingsimpl/service_test.go` | verified |  |
| grafana | `pkg/tests/apis/alerting/notifications/timeinterval/timeinterval_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/foldermetadata/folder_permissions_test.go` | verified |  |
| grafana | `public/app/core/components/AppNotifications/AppNotificationItem.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/notification-policies/AlertGroupsSummary.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/saved-searches/SavedSearchItem.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/settings/extensions.ts` | verified |  |
| grafana | `public/app/features/canvas/elements/ellipse.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/sharing/ShareExportTab.tsx` | verified |  |
| grafana | `public/app/features/explore/ShortLinkButtonMenu.tsx` | verified |  |
| grafana | `public/app/features/logs/components/panel/LogLineDetailsDisplayedFields.tsx` | verified |  |
| grafana | `public/app/features/plugins/admin/components/GetStartedWithPlugin/GetStartedWithDataSource.tsx` | verified |  |
| grafana | `public/app/features/theme-playground/ThemePlayground.tsx` | verified |  |
| grafana | `public/app/features/variables/inspect/VariablesUnknownTable.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/hooks.ts` | verified |  |
| grafana | `public/app/plugins/panel/geomap/layers/data/heatMap.tsx` | verified |  |
