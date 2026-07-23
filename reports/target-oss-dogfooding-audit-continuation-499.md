# Target OSS no-LLM dogfooding audit — continuation 499 (batch 500)

Run: 2026-07-23T07:02:10.379389+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/builtin/builtin.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/loopbce.go` | verified |  |
| go | `src/cmd/compile/internal/types2/unify.go` | verified |  |
| go | `src/cmd/go/internal/gover/toolchain_test.go` | verified |  |
| go | `src/cmd/go/internal/modcmd/why.go` | verified |  |
| go | `src/internal/goarch/goarch_s390x.go` | verified |  |
| go | `src/internal/lazytemplate/lazytemplate.go` | verified |  |
| go | `src/net/http/cookiejar/dummy_publicsuffix_test.go` | verified |  |
| go | `src/net/http/internal/http2/write.go` | verified |  |
| go | `src/net/http/internal/http2/writesched_priority_rfc9218.go` | verified |  |
| go | `src/net/net.go` | verified |  |
| go | `src/net/parse_test.go` | verified |  |
| go | `src/runtime/cgocallback.go` | verified |  |
| go | `src/runtime/mem_wasm.go` | verified |  |
| go | `src/runtime/os_linux_mipsx.go` | verified |  |
| go | `src/runtime/signal_ppc64x.go` | verified |  |
| go | `src/syscall/zsysnum_linux_riscv64.go` | verified |  |
| go | `src/unicode/digit.go` | verified |  |
| go | `test/armimm.go` | verified |  |
| go | `test/fixedbugs/bug501.go` | verified |  |
| go | `test/fixedbugs/issue10607.go` | verified |  |
| go | `test/fixedbugs/issue14331.go` | verified |  |
| go | `test/fixedbugs/issue25322.go` | verified |  |
| go | `test/fixedbugs/issue35586.go` | verified |  |
| go | `test/fixedbugs/issue51531.go` | verified |  |
| go | `test/fixedbugs/issue64715.go` | verified |  |
| go | `test/typeparam/issue47631.go` | verified |  |
| go | `test/typeparam/issue49667.dir/b.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v0alpha1/templategroup_spec_gen.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v0alpha1/snapshot_client_gen.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/conversion/v1_test.go` | verified |  |
| grafana | `apps/dashvalidator/pkg/validator/prometheus/validator.go` | verified |  |
| grafana | `packages/grafana-ui/src/components/DataLinks/DataLinksContextMenu.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/QueryFieldConfig/queryFieldConfig.ts` | verified |  |
| grafana | `pkg/apimachinery/errutil/errors_example_test.go` | verified |  |
| grafana | `pkg/plugins/plugins_test.go` | verified |  |
| grafana | `pkg/registry/apis/dashboard/dashboard_storage.go` | verified |  |
| grafana | `pkg/registry/apis/preferences/utils/authorizer_test.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/resources/client.go` | verified |  |
| grafana | `pkg/registry/apis/query/query.go` | verified |  |
| grafana | `pkg/registry/apps/alerting/rules/alertrule/authorize.go` | verified |  |
| grafana | `pkg/services/serviceaccounts/secretscan/service_test.go` | verified |  |
| grafana | `public/app/features/admin/ldap/LdapUserTeams.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/import-to-gma/ImportToGMA.tsx` | verified |  |
| grafana | `public/app/features/canvas/runtime/element.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/edit-pane/dashboard/DashboardAnnotationsList.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/serialization/transformToV1TypesUtils.ts` | verified |  |
| grafana | `public/app/features/dashboard/components/GenAI/GenAIButton.tsx` | verified |  |
| grafana | `public/app/features/dashboard/dashgrid/DashboardLibrary/CommunityDashboardMappingForm.tsx` | verified |  |
| grafana | `public/app/features/manage-dashboards/import/components/GcomDashboardInfo.tsx` | verified |  |
