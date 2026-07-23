# Target OSS no-LLM dogfooding audit — continuation 435 (batch 436)

Run: 2026-07-23T02:12:53.307367+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ssa/cse_test.go` | verified |  |
| go | `src/cmd/go/internal/modfetch/bootstrap.go` | verified |  |
| go | `src/cmd/internal/gcprog/gcprog.go` | verified |  |
| go | `src/encoding/pem/example_test.go` | verified |  |
| go | `src/image/draw/draw_test.go` | verified |  |
| go | `src/internal/abi/abi_generic.go` | verified |  |
| go | `src/internal/godebug/godebug.go` | verified |  |
| go | `src/net/http/fcgi/fcgi.go` | verified |  |
| go | `src/net/interface_unix_test.go` | verified |  |
| go | `src/runtime/mfinal_test.go` | verified |  |
| go | `src/strings/replace_test.go` | verified |  |
| go | `src/sync/pool_test.go` | verified |  |
| go | `src/time/example_test.go` | verified |  |
| go | `test/codegen/deadstore.go` | verified |  |
| go | `test/fixedbugs/bug209.go` | verified |  |
| go | `test/fixedbugs/bug233.go` | verified |  |
| go | `test/fixedbugs/bug438.go` | verified |  |
| go | `test/fixedbugs/issue15920.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue20245.go` | verified |  |
| go | `test/fixedbugs/issue23536.go` | verified |  |
| go | `test/fixedbugs/issue4785.go` | verified |  |
| go | `test/fixedbugs/issue61992.go` | verified |  |
| go | `test/print.go` | verified |  |
| go | `test/typeparam/issue50417.go` | verified |  |
| grafana | `apps/advisor/pkg/app/checks/datasourcecheck/prom_dep_auth_check_step.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v2beta1/validation_test.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/github/validator_test.go` | verified |  |
| grafana | `packages/grafana-sql/src/components/configuration/Divider.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/slate-plugins/clipboard.ts` | verified |  |
| grafana | `pkg/registry/apis/dashboard/register.go` | verified |  |
| grafana | `pkg/services/featuremgmt/strcase/camel.go` | verified |  |
| grafana | `pkg/services/live/survey/survey.go` | verified |  |
| grafana | `pkg/services/ngalert/eval/validate.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/legacy_storage/v1/compat_validation.go` | verified |  |
| grafana | `pkg/services/ngalert/schedule/rule_sequence_store_k8s_test.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/angularinspector/angularinspector.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/clientmiddleware/grafana_request_id_header_middleware.go` | verified |  |
| grafana | `pkg/services/queryhistory/api.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrator/mysql_dialect.go` | verified |  |
| grafana | `pkg/storage/unified/parquet/reader_test.go` | verified |  |
| grafana | `pkg/storage/unified/search/embed/embedder/vertex/integration_test.go` | verified |  |
| grafana | `public/app/features/actions/utils.ts` | verified |  |
| grafana | `public/app/features/browse-dashboards/components/FolderDetailsActions/FolderDetailsActions.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/conditional-rendering/hooks/useIsConditionallyHidden.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/serialization/layoutSerializers/NotebookLayoutSerializer.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/annotations/ListNewButton.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/sharing/DownloadDiagnostics.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/TraceTimelineViewer/SpanDetail/AccordionLogs.tsx` | verified |  |
| grafana | `public/app/features/plugins/components/restrictedGrafanaApis/dashboardMutation/dashboardMutationApi.ts` | verified |  |
| grafana | `public/app/features/provisioning/Wizard/components/WizardButtonBar.tsx` | verified |  |
