# Target OSS no-LLM dogfooding audit — continuation 400 (batch 401)

Run: 2026-07-23T00:39:23.575344+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ssagen/pgen.go` | verified |  |
| go | `src/cmd/internal/browser/browser.go` | verified |  |
| go | `src/crypto/internal/fips140/edwards25519/field/fe_test.go` | verified |  |
| go | `src/internal/runtime/cgroup/cgroup.go` | verified |  |
| go | `src/internal/strconv/ftoa.go` | verified |  |
| go | `src/math/rand/rand.go` | verified |  |
| go | `src/os/user/cgo_user_test.go` | verified |  |
| go | `src/runtime/cgo/iscgo.go` | verified |  |
| go | `src/runtime/nonwindows_stub.go` | verified |  |
| go | `src/runtime/proc_test.go` | verified |  |
| go | `test/fixedbugs/bug467.dir/p2.go` | verified |  |
| go | `test/fixedbugs/gcc78763.go` | verified |  |
| go | `test/fixedbugs/issue46720.go` | verified |  |
| go | `test/fixedbugs/issue63333.go` | verified |  |
| go | `test/fixedbugs/issue65593.go` | verified |  |
| go | `test/fixedbugs/issue9432.go` | verified |  |
| go | `test/float_lit2.go` | verified |  |
| go | `test/nilptr3.go` | verified |  |
| go | `test/typeparam/issue50002.go` | verified |  |
| grafana | `apps/advisor/pkg/app/utils_test.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v0alpha1/inhibitionrule_codec_gen.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/app/config_validator_test.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v0alpha1/dashboard_spec_gen.go` | verified |  |
| grafana | `e2e-playwright/test-plugins/grafana-test-datasource/i18next.config.ts` | verified |  |
| grafana | `packages/grafana-data/src/themes/createComponents.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Monaco/utils.ts` | verified |  |
| grafana | `pkg/api/pluginproxy/token_provider_gce.go` | verified |  |
| grafana | `pkg/infra/nats/discovery_test.go` | verified |  |
| grafana | `pkg/middleware/testing.go` | verified |  |
| grafana | `pkg/plugins/repo/client.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/timeout.go` | verified |  |
| grafana | `pkg/registry/apis/secret/decrypt/authorizer.go` | verified |  |
| grafana | `pkg/registry/apps/annotation/storage.go` | verified |  |
| grafana | `pkg/storage/unified/sql/rvmanager/rv_manager_test.go` | verified |  |
| grafana | `pkg/tsdb/azuremonitor/sql_test.go` | verified |  |
| grafana | `pkg/util/md5_test.go` | verified |  |
| grafana | `public/app/features/admin/UserAdminPage.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/alert-groups/MatcherFilter.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rules/ActionIcon.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/utils/notification-policies.ts` | verified |  |
| grafana | `public/app/features/auth-config/FieldRenderer.tsx` | verified |  |
| grafana | `public/app/features/browse-dashboards/hooks/useNavModel.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/UnconfiguredPanel.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/new-toolbar/Actions.tsx` | verified |  |
| grafana | `public/app/features/dashboard/api/publicDashboardApi.ts` | verified |  |
| grafana | `public/app/features/datasources/components/DataSourceTestingStatus.tsx` | verified |  |
| grafana | `public/app/features/users/UsersExternalButton.tsx` | verified |  |
| grafana | `public/app/features/variables/adhoc/picker/AdHocFilterBuilder.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/graphite/components/GraphiteVariableEditor.tsx` | verified |  |
| grafana | `public/app/plugins/panel/logstable/logsTableFieldConfig.ts` | verified |  |
