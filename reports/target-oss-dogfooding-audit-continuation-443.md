# Target OSS no-LLM dogfooding audit — continuation 443 (batch 444)

Run: 2026-07-23T02:38:48.039370+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/inline/inlheur/analyze.go` | verified |  |
| go | `src/cmd/internal/cov/readcovdata.go` | verified |  |
| go | `src/crypto/md5/md5block_generic.go` | verified |  |
| go | `src/internal/goroot/gc.go` | verified |  |
| go | `src/internal/syscall/windows/registry/key.go` | verified |  |
| go | `src/net/platform_unix_test.go` | verified |  |
| go | `src/runtime/float.go` | verified |  |
| go | `src/runtime/profbuf.go` | verified |  |
| go | `src/simd/archsimd/internal/simd_test/unary_wasm_test.go` | verified |  |
| go | `src/strconv/number.go` | verified |  |
| go | `src/time/sys_unix.go` | verified |  |
| go | `test/fixedbugs/bug492.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue16515.go` | verified |  |
| go | `test/fixedbugs/issue21317.go` | verified |  |
| go | `test/fixedbugs/issue30907.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue55242.go` | verified |  |
| go | `test/fixedbugs/issue59169.go` | verified |  |
| go | `test/ken/simpvar.go` | verified |  |
| go | `test/linkmain_run.go` | verified |  |
| go | `test/typeparam/select.dir/main.go` | verified |  |
| go | `test/uintptrescapes3.go` | verified |  |
| grafana | `apps/advisor/pkg/app/checks/configchecks/check.go` | verified |  |
| grafana | `packages/grafana-api-clients/src/generator/files.ts` | verified |  |
| grafana | `packages/grafana-data/src/vector/ArrayVector.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Monaco/types.ts` | verified |  |
| grafana | `packages/grafana-ui/src/themes/GlobalStyles/page.ts` | verified |  |
| grafana | `pkg/api/dashboard_snapshot_test.go` | verified |  |
| grafana | `pkg/infra/httpclient/harcapture/harcapture.go` | verified |  |
| grafana | `pkg/infra/httpclient/httpclientprovider/tracing_middleware.go` | verified |  |
| grafana | `pkg/infra/slugify/slugify.go` | verified |  |
| grafana | `pkg/plugins/errors_test.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/usage/usage.go` | verified |  |
| grafana | `pkg/registry/apis/query/queryschema/query_type_storage.go` | verified |  |
| grafana | `pkg/services/apiserver/client/client.go` | verified |  |
| grafana | `pkg/services/ngalert/sender/router_test.go` | verified |  |
| grafana | `pkg/services/ngalert/state/manager_test.go` | verified |  |
| grafana | `pkg/services/ngalert/store/models_test.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/ualert/rule_creator_mig.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/quota/sync_quota_test.go` | verified |  |
| grafana | `pkg/tsdb/azuremonitor/loganalytics/azure-log-analytics-datasource.go` | verified |  |
| grafana | `pkg/util/shortid_generator.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/receivers/GlobalConfigForm.tsx` | verified |  |
| grafana | `public/app/features/connections/pages/ConnectionsHomePage.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/edit-pane/types.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/mutation-api/commands/schemas.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/Body/SqlExpressionsCTA.tsx` | verified |  |
| grafana | `public/app/features/manage-dashboards/components/PublicDashboardListTable/DeletePublicDashboardButton.tsx` | verified |  |
| grafana | `public/app/features/plugins/importer/types.ts` | verified |  |
| grafana | `public/app/features/provisioning/Migrate/MigrateToGitopsHeader.tsx` | verified |  |
| grafana | `public/app/features/variables/adhoc/picker/AdHocFilterRenderer.tsx` | verified |  |
