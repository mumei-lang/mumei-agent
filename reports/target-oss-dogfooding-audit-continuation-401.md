# Target OSS no-LLM dogfooding audit — continuation 401 (batch 402)

Run: 2026-07-23T00:44:11.631355+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/asm/doc.go` | verified |  |
| go | `src/cmd/compile/internal/escape/expr.go` | verified |  |
| go | `src/cmd/compile/internal/loong64/ggen.go` | verified |  |
| go | `src/cmd/go/scriptcmds_test.go` | verified |  |
| go | `src/cmd/internal/dwarf/dwarf_test.go` | verified |  |
| go | `src/cmd/internal/obj/mips/a.out.go` | verified |  |
| go | `src/compress/gzip/gunzip_test.go` | verified |  |
| go | `src/internal/poll/fd_poll_runtime.go` | verified |  |
| go | `src/net/net_fake.go` | verified |  |
| go | `src/runtime/mgcpacer.go` | verified |  |
| go | `test/codegen/issue60324.go` | verified |  |
| go | `test/convlit.go` | verified |  |
| go | `test/fixedbugs/bug119.go` | verified |  |
| go | `test/fixedbugs/bug230.go` | verified |  |
| go | `test/fixedbugs/bug369.go` | verified |  |
| go | `test/fixedbugs/bug424.dir/lib.go` | verified |  |
| go | `test/fixedbugs/bug518.go` | verified |  |
| go | `test/fixedbugs/issue17710.go` | verified |  |
| go | `test/fixedbugs/issue6703a.go` | verified |  |
| go | `test/typeparam/issue47740.go` | verified |  |
| grafana | `apps/alerting/rules/pkg/apis/alerting/v0alpha1/recordingrule_spec_gen.go` | verified |  |
| grafana | `apps/dashvalidator/pkg/apis/dashvalidator/v1alpha1/dashboardcompatibilityscore_schema_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/connection/github/mutator_test.go` | verified |  |
| grafana | `packages/grafana-runtime/src/services/pluginSettings/utils.ts` | verified |  |
| grafana | `pkg/api/folder_permission_test.go` | verified |  |
| grafana | `pkg/middleware/validate_action_url_test.go` | verified |  |
| grafana | `pkg/middleware/validate_host.go` | verified |  |
| grafana | `pkg/registry/apis/appplugin/authorizer.go` | verified |  |
| grafana | `pkg/registry/apis/iam/register.go` | verified |  |
| grafana | `pkg/registry/apis/iam/user_org_hooks_test.go` | verified |  |
| grafana | `pkg/registry/apis/ofrep/helpers_test.go` | verified |  |
| grafana | `pkg/registry/apis/preferences/register.go` | verified |  |
| grafana | `pkg/services/folder/store_fake.go` | verified |  |
| grafana | `pkg/services/login/model.go` | verified |  |
| grafana | `pkg/services/ngalert/remote/client/alertmanager_state.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/migrations.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/ualert/alert_rule_keep_firing_for.go` | verified |  |
| grafana | `pkg/services/star/api/client.go` | verified |  |
| grafana | `pkg/services/store/validate.go` | verified |  |
| grafana | `pkg/storage/unified/apistore/permissions_test.go` | verified |  |
| grafana | `pkg/storage/unified/apistore/secure_test.go` | verified |  |
| grafana | `pkg/tests/api/dashboards/api_dashboards_test.go` | verified |  |
| grafana | `pkg/tsdb/grafana-postgresql-datasource/sqleng/handler_checkhealth_test.go` | verified |  |
| grafana | `playwright.storybook.config.ts` | verified |  |
| grafana | `public/app/core/context/GrafanaContext.ts` | verified |  |
| grafana | `public/app/features/admin/AdminSettingsTable.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/saving/DashboardPrompt.tsx` | verified |  |
| grafana | `public/app/features/provisioning/hooks/useIsProvisionedNG.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/components/shared/Dimensions/FilterItem.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/language/cloudwatch-sql/completion/statementPosition.ts` | verified |  |
