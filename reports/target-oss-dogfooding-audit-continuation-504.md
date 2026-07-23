# Target OSS no-LLM dogfooding audit — continuation 504 (batch 505)

Run: 2026-07-23T07:12:21.615349+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/base/startheap.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/export_test.go` | verified |  |
| go | `src/cmd/go/internal/version/version.go` | verified |  |
| go | `src/crypto/internal/fips140test/acvp_fips140v1.26_test.go` | verified |  |
| go | `src/database/sql/driver/types.go` | verified |  |
| go | `src/debug/dwarf/dwarf5ranges_test.go` | verified |  |
| go | `src/go/ast/ast_test.go` | verified |  |
| go | `src/internal/syscall/unix/at_sysnum_fstatat64_linux.go` | verified |  |
| go | `src/internal/testpty/pty_cgo.go` | verified |  |
| go | `src/net/dnsconfig_unix_test.go` | verified |  |
| go | `src/net/sock_linux.go` | verified |  |
| go | `src/runtime/align_runtime_test.go` | verified |  |
| go | `src/syscall/exec_aix_test.go` | verified |  |
| go | `test/fixedbugs/bug228.go` | verified |  |
| go | `test/fixedbugs/issue15514.dir/c.go` | verified |  |
| go | `test/fixedbugs/issue29304.go` | verified |  |
| go | `test/fixedbugs/issue59709.dir/aconfig.go` | verified |  |
| go | `test/fixedbugs/issue6703p.go` | verified |  |
| go | `test/typeparam/issue50598.dir/a2.go` | verified |  |
| go | `test/typeparam/mdempsky/1.dir/b.go` | verified |  |
| go | `test/typeparam/settable.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/user_spec_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/controller/labels_test.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/informers/externalversions/factory.go` | verified |  |
| grafana | `e2e-playwright/utils/axe-a11y/reporter.ts` | verified |  |
| grafana | `packages/grafana-data/src/field/fieldDisplay.ts` | verified |  |
| grafana | `packages/grafana-data/src/types/exposedComponentProps.ts` | verified |  |
| grafana | `packages/grafana-i18n/rollup.config.ts` | verified |  |
| grafana | `packages/grafana-ui/src/graveyard/GraphNG/types.ts` | verified |  |
| grafana | `pkg/registry/apis/secret/xkube/errors.go` | verified |  |
| grafana | `pkg/services/authz/zanzana/server/server_list.go` | verified |  |
| grafana | `pkg/services/datasourceproxy/datasourceproxy.go` | verified |  |
| grafana | `pkg/services/ngalert/api/api_ruler_history.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/accesscontrol/team_membership.go` | verified |  |
| grafana | `pkg/storage/unified/resource/gc_gate_test.go` | verified |  |
| grafana | `pkg/storage/unified/resource/tenant_watcher.go` | verified |  |
| grafana | `pkg/storage/unified/sql/db/mocks/Tx.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/models/resources/log_group_fields_resource_request.go` | verified |  |
| grafana | `pkg/util/debouncer/queue.go` | verified |  |
| grafana | `public/app/core/components/AppChrome/ReturnToPrevious/ReturnToPrevious.tsx` | verified |  |
| grafana | `public/app/features/browse-dashboards/components/customFlexTableLayout.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/splitter/useSnappingSplitter.ts` | verified |  |
| grafana | `public/app/features/logs/components/fieldSelector/EmptyFields.tsx` | verified |  |
| grafana | `public/app/features/search/service/deletedDashboardsCache.ts` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/azure_monitor/azure_monitor_datasource.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/components/QueryEditor/MetricsQueryEditor/MathExpressionQueryField.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/language/cloudwatch-ppl/completion/PPLCompletionItemProvider.ts` | verified |  |
| grafana | `public/app/plugins/datasource/graphite/components/helpers.ts` | verified |  |
| grafana | `public/app/plugins/panel/logstable/fields/supports.ts` | verified |  |
| grafana | `public/app/types/organization.ts` | verified |  |
