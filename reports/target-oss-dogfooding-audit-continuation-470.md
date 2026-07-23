# Target OSS no-LLM dogfooding audit — continuation 470 (batch 471)

Run: 2026-07-23T04:43:09.987386+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/asm/main.go` | verified |  |
| go | `src/cmd/compile/internal/types2/object.go` | verified |  |
| go | `src/cmd/internal/dwarf/dwarf_defs.go` | verified |  |
| go | `src/crypto/internal/cryptotest/fetchmodule.go` | verified |  |
| go | `src/crypto/rsa/pkcs1v15.go` | verified |  |
| go | `src/crypto/tls/prf_test.go` | verified |  |
| go | `src/encoding/gob/example_encdec_test.go` | verified |  |
| go | `src/encoding/json/tags_test.go` | verified |  |
| go | `src/internal/cpu/cpu_riscv64_linux.go` | verified |  |
| go | `src/net/udpsock.go` | verified |  |
| go | `src/runtime/defs_linux_riscv64.go` | verified |  |
| go | `src/syscall/setuidgid_32_linux.go` | verified |  |
| go | `src/testing/run_example_wasm.go` | verified |  |
| go | `test/convert.go` | verified |  |
| go | `test/fixedbugs/bug275.go` | verified |  |
| go | `test/fixedbugs/bug345.go` | verified |  |
| go | `test/fixedbugs/issue21273.go` | verified |  |
| go | `test/fixedbugs/issue24120.go` | verified |  |
| go | `test/fixedbugs/issue24761.go` | verified |  |
| go | `test/fixedbugs/issue31252.dir/c.go` | verified |  |
| go | `test/fixedbugs/issue52870.go` | verified |  |
| go | `test/fixedbugs/issue7995b.dir/x2.go` | verified |  |
| grafana | `apps/advisor/pkg/apis/advisor/v0alpha1/constants.go` | verified |  |
| grafana | `apps/alerting/rules/pkg/app/recordingrule/validator.go` | verified |  |
| grafana | `packages/grafana-alerting/src/grafana/notificationPolicies/components/RoutingTreeSelector/RoutingTreeSelector.tsx` | verified |  |
| grafana | `packages/grafana-data/src/types/graph.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Forms/RadioButtonList/RadioButtonDot.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/options/builder/axis.tsx` | verified |  |
| grafana | `pkg/kinds/dashboard/dashboard_status_gen.go` | verified |  |
| grafana | `pkg/registry/apis/datasource/converter/converter.go` | verified |  |
| grafana | `pkg/registry/apis/iam/externalgroupmapping/search_noop.go` | verified |  |
| grafana | `pkg/registry/apis/iam/serviceaccount_org_hooks_test.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/webhooks/register.go` | verified |  |
| grafana | `pkg/services/ngalert/api/tooling/definitions/provisioning_alert_rules.go` | verified |  |
| grafana | `pkg/services/ngalert/state/historian/multiple_test.go` | verified |  |
| grafana | `pkg/services/ngalert/state/manager_private_test.go` | verified |  |
| grafana | `pkg/services/provisioning/provisioning_test.go` | verified |  |
| grafana | `pkg/services/publicdashboards/internal/api/middleware_test.go` | verified |  |
| grafana | `public/app/api/clients/legacy/index.ts` | verified |  |
| grafana | `public/app/features/admin/Users/OrgUnits.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/PluginBridge.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/mocks/server/configure.ts` | verified |  |
| grafana | `public/app/features/auth-config/index.ts` | verified |  |
| grafana | `public/app/features/browse-dashboards/state/utils.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/edit-pane/dashboard/DashboardVariablesList.tsx` | verified |  |
| grafana | `public/app/features/dimensions/utils.ts` | verified |  |
| grafana | `public/app/features/plugins/sandbox/codeLoader.ts` | verified |  |
| grafana | `public/app/features/variables/query/QueryVariableSortSelect.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/QueryEditor/QueryHeader.tsx` | verified |  |
| grafana | `public/boot/index.ts` | verified |  |
