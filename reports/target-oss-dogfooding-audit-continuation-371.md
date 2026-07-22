# Target OSS no-LLM dogfooding audit — continuation 371 (batch 372)

Run: 2026-07-22T22:20:25.559354+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ssa/decompose.go` | verified |  |
| go | `src/cmd/compile/internal/test/clobberdead_test.go` | verified |  |
| go | `src/embed/example_test.go` | verified |  |
| go | `src/encoding/xml/typeinfo.go` | verified |  |
| go | `src/image/jpeg/reader.go` | verified |  |
| go | `src/internal/goarch/goarch_mips64.go` | verified |  |
| go | `src/internal/poll/hook_cloexec.go` | verified |  |
| go | `src/internal/reflectlite/swapper.go` | verified |  |
| go | `src/math/cmplx/sin.go` | verified |  |
| go | `src/net/http/csrf.go` | verified |  |
| go | `src/net/http/response.go` | verified |  |
| go | `src/net/write_unix_test.go` | verified |  |
| go | `src/runtime/mem.go` | verified |  |
| go | `src/runtime/metrics/value.go` | verified |  |
| go | `src/runtime/tagptr.go` | verified |  |
| go | `test/alias3.dir/b.go` | verified |  |
| go | `test/codegen/maps.go` | verified |  |
| go | `test/fixedbugs/bug165.go` | verified |  |
| go | `test/fixedbugs/issue13160.go` | verified |  |
| go | `test/fixedbugs/issue18410.go` | verified |  |
| go | `test/fixedbugs/issue23188.go` | verified |  |
| go | `test/typeparam/pairimp.dir/main.go` | verified |  |
| go | `test/typeparam/stringerimp.dir/main.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v1beta1/timeinterval_client_gen.go` | verified |  |
| grafana | `apps/folder/pkg/apis/folder/v1/folder_client_gen.go` | verified |  |
| grafana | `e2e-playwright/test-plugins/grafana-extensionstest-app/plugins/grafana-extensionexample3-app/module.tsx` | verified |  |
| grafana | `packages/grafana-test-utils/src/handlers/api/folders/handlers.ts` | verified |  |
| grafana | `packages/grafana-ui/src/slate-plugins/newline.ts` | verified |  |
| grafana | `packages/grafana-ui/src/utils/useComponetInstanceId.ts` | verified |  |
| grafana | `pkg/infra/httpclient/httpclientprovider/http_logger_middleware.go` | verified |  |
| grafana | `pkg/services/authz/zanzana/server/admission_test.go` | verified |  |
| grafana | `pkg/services/live/pipeline/converter_json_auto_test.go` | verified |  |
| grafana | `pkg/services/loginattempt/loginattemptimpl/store_test.go` | verified |  |
| grafana | `pkg/services/ngalert/api/promql_compat_test.go` | verified |  |
| grafana | `pkg/services/ngalert/provisioning/templates_test.go` | verified |  |
| grafana | `pkg/services/serviceaccounts/api/api_test.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/ualert/alert_rule_missing_series_evals_to_resolve.go` | verified |  |
| grafana | `pkg/services/user/userimpl/store_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/jobs/movejob_test.go` | verified |  |
| grafana | `pkg/tsdb/azuremonitor/httpclient.go` | verified |  |
| grafana | `pkg/util/httpclient/client.go` | verified |  |
| grafana | `public/app/features/admin/ldap/LdapSettingsPage.tsx` | verified |  |
| grafana | `public/app/features/alerting/state/reducers.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/import-to-gma/types.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/rule-list/GroupedView.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/edit-pane/MultiSelectedObjectsEditableElement.tsx` | verified |  |
| grafana | `public/app/features/dashboard/components/GenAI/hooks.ts` | verified |  |
| grafana | `public/app/features/explore/state/explorePane.ts` | verified |  |
| grafana | `public/app/features/library-panels/components/DeleteLibraryPanelModal/DeleteLibraryPanelModal.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/LogsQueryBuilder/utils.ts` | verified |  |
