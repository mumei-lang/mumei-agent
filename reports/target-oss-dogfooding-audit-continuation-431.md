# Target OSS no-LLM dogfooding audit — continuation 431 (batch 432)

Run: 2026-07-23T02:02:39.475308+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/archive/zip/register.go` | verified |  |
| go | `src/cmd/compile/internal/types2/initorder.go` | verified |  |
| go | `src/cmd/go/internal/imports/read_test.go` | verified |  |
| go | `src/cmd/go/internal/modload/modfile.go` | verified |  |
| go | `src/cmd/go/internal/modload/query.go` | verified |  |
| go | `src/crypto/internal/cryptotest/blockmode.go` | verified |  |
| go | `src/internal/goexperiment/exp_boringcrypto_on.go` | verified |  |
| go | `src/internal/goexperiment/exp_regabiwrappers_on.go` | verified |  |
| go | `src/net/fd_plan9.go` | verified |  |
| go | `src/os/wait_wait6.go` | verified |  |
| go | `src/runtime/os_only_solaris.go` | verified |  |
| go | `src/simd/archsimd/internal/simd_test/compare_helpers_wider_test.go` | verified |  |
| go | `src/simd/archsimd/internal/simd_test/comparemasked_helpers_test.go` | verified |  |
| go | `src/sync/mutex.go` | verified |  |
| go | `src/syscall/syscall_openbsd_arm64.go` | verified |  |
| go | `test/fixedbugs/issue20014.dir/main.go` | verified |  |
| go | `test/fixedbugs/issue30908.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue79274a.dir/b.go` | verified |  |
| go | `test/typeparam/issue47716.go` | verified |  |
| go | `test/typeparam/issue48838.go` | verified |  |
| go | `test/typeparam/issue50437.dir/a.go` | verified |  |
| go | `test/typeparam/maps.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v35.go` | verified |  |
| grafana | `apps/dashvalidator/pkg/validator/prometheus/parser_test.go` | verified |  |
| grafana | `apps/logsdrilldown/pkg/apis/logsdrilldown/v1alpha1/replacedefaultfields_request_body_types_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/github/repository.go` | verified |  |
| grafana | `apps/quotas/pkg/apis/quotas/v0alpha1/client_gen.go` | verified |  |
| grafana | `apps/secret/pkg/decrypt/contracts.go` | verified |  |
| grafana | `packages/grafana-ui/src/components/Layout/Stack/Stack.tsx` | verified |  |
| grafana | `pkg/api/frontendsettings/frontendsettings.go` | verified |  |
| grafana | `pkg/cmd/grafana-cli/commands/datamigrations/encrypt_datasource_passwords.go` | verified |  |
| grafana | `pkg/cmd/grafana-cli/utils/command_line.go` | verified |  |
| grafana | `pkg/components/simplejson/simplejson.go` | verified |  |
| grafana | `pkg/infra/log/syslog_windows.go` | verified |  |
| grafana | `pkg/middleware/quota_test.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/releaseresources/worker_test.go` | verified |  |
| grafana | `pkg/services/apiserver/appinstaller/resourceconfig.go` | verified |  |
| grafana | `pkg/services/dashboardimport/dashboardimport.go` | verified |  |
| grafana | `pkg/services/ldap/ldap_groups.go` | verified |  |
| grafana | `pkg/services/search/service_test.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/accesscontrol/action_migrator.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/star_mig.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/team_mig.go` | verified |  |
| grafana | `pkg/storage/unified/search/open_index_list_test.go` | verified |  |
| grafana | `pkg/storage/unified/sql/test/integration_test.go` | verified |  |
| grafana | `pkg/tests/apis/correlations/correlations_test.go` | verified |  |
| grafana | `pkg/tsdb/azuremonitor/loganalytics/azure-response-table-frame.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rules/RuleDetailsAnnotations.tsx` | verified |  |
| grafana | `public/app/features/scopes/selector/ScopesTreeItemList.tsx` | verified |  |
| grafana | `public/app/plugins/panel/logstable/links/copyDashboardUrl.ts` | verified |  |
