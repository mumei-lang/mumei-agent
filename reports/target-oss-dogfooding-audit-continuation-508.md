# Target OSS no-LLM dogfooding audit — continuation 508 (batch 509)

Run: 2026-07-23T07:19:34.535480+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/buildid/buildid.go` | verified |  |
| go | `src/cmd/go/internal/gover/mod.go` | verified |  |
| go | `src/cmd/go/internal/vcweb/hg.go` | verified |  |
| go | `src/crypto/internal/fips140/boring.go` | verified |  |
| go | `src/internal/cpu/cpu_arm64_openbsd.go` | verified |  |
| go | `src/math/cmplx/isnan.go` | verified |  |
| go | `src/net/http/internal/http2/export_test.go` | verified |  |
| go | `src/runtime/race/race_windows_test.go` | verified |  |
| go | `src/syscall/rlimit_stub.go` | verified |  |
| go | `src/syscall/syscall_bsd_test.go` | verified |  |
| go | `src/unicode/example_test.go` | verified |  |
| go | `test/char_lit1.go` | verified |  |
| go | `test/fixedbugs/bug485.go` | verified |  |
| go | `test/fixedbugs/issue11370.go` | verified |  |
| go | `test/fixedbugs/issue15572.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue33355.go` | verified |  |
| go | `test/fixedbugs/issue52748.go` | verified |  |
| go | `test/fixedbugs/issue58563.dir/main.go` | verified |  |
| go | `test/funcdup2.go` | verified |  |
| go | `test/runtime.go` | verified |  |
| go | `test/typeparam/issue46461.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v1beta1/templategroup_object_gen.go` | verified |  |
| grafana | `apps/alerting/rules/pkg/app/app_test.go` | verified |  |
| grafana | `apps/alerting/rules/plugin/src/generated/alertrule/v0alpha1/types.metadata.gen.ts` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/globalrolebinding_schema_gen.go` | verified |  |
| grafana | `devenv/docker/blocks/prometheus_high_card/main.go` | verified |  |
| grafana | `packages/grafana-ui/src/components/Spinner/Spinner.tsx` | verified |  |
| grafana | `pkg/api/frontendlogging/source_maps.go` | verified |  |
| grafana | `pkg/cmd/grafana-cli/commands/secretsmigrations/secretsmigrations.go` | verified |  |
| grafana | `pkg/middleware/loggermw/logger.go` | verified |  |
| grafana | `pkg/plugins/backendplugin/chunked/writer_test.go` | verified |  |
| grafana | `pkg/registry/apis/dashboard/dashboard_storage_test.go` | verified |  |
| grafana | `pkg/services/accesscontrol/accesscontrol.go` | verified |  |
| grafana | `pkg/services/ldap/model.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/legacy_storage/compat.go` | verified |  |
| grafana | `pkg/services/ngalert/remote/compat.go` | verified |  |
| grafana | `pkg/services/user/error.go` | verified |  |
| grafana | `pkg/storage/unified/search/bleve_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/maxfilesize/files_max_file_size_test.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/cloudwatch_test.go` | verified |  |
| grafana | `public/app/features/alerting/unified/AlertWarning.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/QueryWrapper.tsx` | verified |  |
| grafana | `public/app/features/browse-dashboards/components/RecentlyViewedDashboards.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/inspect/InspectQueryTab.tsx` | verified |  |
| grafana | `public/app/features/home/DashboardTabs/DashboardTabs.tsx` | verified |  |
| grafana | `public/app/features/users/utils.ts` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/tracking.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/language/cloudwatch-logs-sql/definition.ts` | verified |  |
| grafana | `public/app/plugins/datasource/loki/configuration/DebugSection.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/loki/configuration/DerivedFields.tsx` | verified |  |
