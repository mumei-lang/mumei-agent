# Target OSS no-LLM dogfooding audit — continuation 363 (batch 364)

Run: 2026-07-22T21:57:40.403382+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/staticinit/sched.go` | verified |  |
| go | `src/cmd/go/internal/tool/signal_js.go` | verified |  |
| go | `src/cmd/link/internal/loong64/asm.go` | verified |  |
| go | `src/crypto/internal/fips140cache/cache.go` | verified |  |
| go | `src/crypto/internal/fips140test/ctrdrbg_test.go` | verified |  |
| go | `src/errors/join_test.go` | verified |  |
| go | `src/internal/goarch/zgoarch_riscv.go` | verified |  |
| go | `src/internal/godebug/godebug_test.go` | verified |  |
| go | `src/internal/trace/internal/tracev1/parser_test.go` | verified |  |
| go | `src/net/http/range_test.go` | verified |  |
| go | `src/runtime/covercounter.go` | verified |  |
| go | `src/runtime/mbitmap.go` | verified |  |
| go | `test/fixedbugs/issue25897a.go` | verified |  |
| go | `test/fixedbugs/issue27356.go` | verified |  |
| go | `test/fixedbugs/issue4748.go` | verified |  |
| go | `test/fixedbugs/issue48473.go` | verified |  |
| go | `test/fixedbugs/issue58826.go` | verified |  |
| go | `test/typeparam/issue49246.dir/b.go` | verified |  |
| grafana | `apps/advisor/pkg/apis/advisor/v0alpha1/client_gen.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/user_schema_gen.go` | verified |  |
| grafana | `e2e-playwright/plugin-e2e/plugin-e2e-api-tests/mocks/queries.ts` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/index.ts` | verified |  |
| grafana | `packages/grafana-data/src/table/amendTimeSeries.ts` | verified |  |
| grafana | `packages/grafana-data/src/types/OptionsUIRegistryBuilder.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/DateTimePickers/TimeOfDayPicker.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Forms/Legacy/Select/SelectOptionGroup.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/VizTooltip/SeriesTable.tsx` | verified |  |
| grafana | `pkg/api/frontend_logging.go` | verified |  |
| grafana | `pkg/components/imguploader/mock.go` | verified |  |
| grafana | `pkg/registry/apis/iam/user/store_wrapper.go` | verified |  |
| grafana | `pkg/registry/apis/secret/garbagecollectionworker/worker.go` | verified |  |
| grafana | `pkg/registry/apps/alerting/notifications/routingtree/conversions.go` | verified |  |
| grafana | `pkg/services/accesscontrol/acimpl/uid_resolver_test.go` | verified |  |
| grafana | `pkg/services/datasourceproxy/datasourceproxy_test.go` | verified |  |
| grafana | `pkg/services/encryption/service/helpers.go` | verified |  |
| grafana | `pkg/services/query/expr_sql_schema.go` | verified |  |
| grafana | `pkg/services/serviceaccounts/manager/store.go` | verified |  |
| grafana | `pkg/services/validations/oss.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/v1beta1/repository_test.go` | verified |  |
| grafana | `pkg/tsdb/influxdb/models/model_parser.go` | verified |  |
| grafana | `public/app/core/components/Login/types.ts` | verified |  |
| grafana | `public/app/core/components/OwnerReferences/OwnerReferenceSelector.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/contact-points/components/UnusedBadge.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/import-to-gma/Wizard/types.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/receivers/TemplatesTable.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-viewer/tabs/Notifications.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/triage/types.ts` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/mocks/panelData.ts` | verified |  |
| grafana | `public/app/plugins/panel/geomap/editor/GeomapStyleRulesEditor.tsx` | verified |  |
| grafana | `public/app/plugins/panel/histogram/HistogramPanel.tsx` | verified |  |
