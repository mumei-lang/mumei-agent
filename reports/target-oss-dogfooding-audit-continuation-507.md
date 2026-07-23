# Target OSS no-LLM dogfooding audit — continuation 507 (batch 508)

Run: 2026-07-23T07:17:44.555370+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/bufio/scan.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/debug_test.go` | verified |  |
| go | `src/cmd/cover/pkgname_test.go` | verified |  |
| go | `src/cmd/go/internal/cache/default.go` | verified |  |
| go | `src/crypto/internal/fips140/sha3/_asm/keccakf_amd64_asm.go` | verified |  |
| go | `src/crypto/internal/fips140test/nistec_test.go` | verified |  |
| go | `src/encoding/csv/fuzz_test.go` | verified |  |
| go | `src/encoding/json/v2/arshal_methods.go` | verified |  |
| go | `src/go/types/methodset.go` | verified |  |
| go | `src/runtime/float_test.go` | verified |  |
| go | `src/simd/archsimd/internal/simd_test/shift_arm64_test.go` | verified |  |
| go | `src/sort/example_test.go` | verified |  |
| go | `src/syscall/ztypes_linux_s390x.go` | verified |  |
| go | `test/fixedbugs/bug014.go` | verified |  |
| go | `test/fixedbugs/bug083.go` | verified |  |
| go | `test/fixedbugs/bug1515.go` | verified |  |
| go | `test/fixedbugs/bug191.dir/b.go` | verified |  |
| go | `test/fixedbugs/bug278.go` | verified |  |
| go | `test/fixedbugs/bug284.go` | verified |  |
| go | `test/fixedbugs/bug405.go` | verified |  |
| go | `test/fixedbugs/issue16241_64.go` | verified |  |
| go | `test/fixedbugs/issue26097.go` | verified |  |
| go | `test/fixedbugs/issue8475.go` | verified |  |
| go | `test/sizeof.go` | verified |  |
| go | `test/typeparam/mapsimp.go` | verified |  |
| go | `test/typeparam/mdempsky/7.dir/b.go` | verified |  |
| grafana | `apps/correlations/pkg/apis/correlation/v0alpha1/correlation_schema_gen.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v24_test.go` | verified |  |
| grafana | `e2e-playwright/dashboard-cujs/utils.ts` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/dashboard/v2beta1/baseAPI.ts` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/preferences/team/endpoints.gen.ts` | verified |  |
| grafana | `packages/grafana-o11y-ds-frontend/src/TraceToLogs/TraceToLogsSettings.tsx` | verified |  |
| grafana | `pkg/apimachinery/errutil/log.go` | verified |  |
| grafana | `pkg/login/social/connectors/azuread_oauth_test.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/queue.go` | verified |  |
| grafana | `pkg/services/dashboardimport/utils/dash_template_evaluator_test.go` | verified |  |
| grafana | `pkg/services/org/orgimpl/org_delete_svc.go` | verified |  |
| grafana | `pkg/services/team/teamimpl/store_test.go` | verified |  |
| grafana | `pkg/services/temp_user/tempuserimpl/temp_user.go` | verified |  |
| grafana | `pkg/tests/apis/helper_retry_test.go` | verified |  |
| grafana | `public/app/core/components/OptionsUI/links.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/receivers/form/fields/OptionField.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/QueryEditorContent.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/layout-default/findSpaceForNewPanel.ts` | verified |  |
| grafana | `public/app/features/dashboard/components/PanelEditor/PanelNotSupported.tsx` | verified |  |
| grafana | `public/app/features/datasources/utils.ts` | verified |  |
| grafana | `public/app/features/library-panels/types.ts` | verified |  |
| grafana | `public/app/features/variables/interval/reducer.ts` | verified |  |
| grafana | `public/app/features/variables/state/__tests__/fixtures.ts` | verified |  |
| grafana | `public/app/plugins/panel/piechart/panelcfg.gen.ts` | verified |  |
