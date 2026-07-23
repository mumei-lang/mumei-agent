# Target OSS no-LLM dogfooding audit — continuation 415 (batch 416)

Run: 2026-07-23T01:20:21.971327+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/testfortran/fortran_test.go` | verified |  |
| go | `src/cmd/compile/internal/types2/gccgosizes.go` | verified |  |
| go | `src/cmd/internal/buildid/buildid.go` | verified |  |
| go | `src/cmd/internal/macho/macho.go` | verified |  |
| go | `src/crypto/hkdf/example_test.go` | verified |  |
| go | `src/debug/gosym/symtab_test.go` | verified |  |
| go | `src/go/types/named.go` | verified |  |
| go | `src/internal/routebsd/interface_openbsd.go` | verified |  |
| go | `src/internal/trace/raw/textwriter.go` | verified |  |
| go | `src/net/cgo_openbsd.go` | verified |  |
| go | `src/runtime/list_test.go` | verified |  |
| go | `src/simd/archsimd/_gen/simdgen/arm64/emit.go` | verified |  |
| go | `src/testing/helper_test.go` | verified |  |
| go | `test/alias1.go` | verified |  |
| go | `test/defernil.go` | verified |  |
| go | `test/fixedbugs/issue13779.go` | verified |  |
| go | `test/fixedbugs/issue30606.go` | verified |  |
| go | `test/fixedbugs/issue33020a.go` | verified |  |
| go | `test/fixedbugs/issue74908.go` | verified |  |
| go | `test/typeparam/issue48094b.dir/b.go` | verified |  |
| grafana | `apps/advisor/pkg/app/checkscheduler/checkscheduler_test.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v0alpha1/search.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v42.go` | verified |  |
| grafana | `apps/provisioning/pkg/connection/connection_token_mock.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/applyconfiguration/provisioning/v0alpha1/connectionwebhookconfig.go` | verified |  |
| grafana | `apps/secret/decrypt/v1beta1/decrypt.pb.go` | verified |  |
| grafana | `packages/grafana-test-utils/src/index.ts` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/releaseresources/worker.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/webhooks/webhook_test.go` | verified |  |
| grafana | `pkg/registry/apis/secret/encryption/kmsproviders/kmsproviders.go` | verified |  |
| grafana | `pkg/services/authz/zanzana/server.go` | verified |  |
| grafana | `pkg/services/datasources/errors.go` | verified |  |
| grafana | `pkg/services/ngalert/api/tooling/definitions/cortex-ruler_test.go` | verified |  |
| grafana | `pkg/services/provisioning/stubs.go` | verified |  |
| grafana | `pkg/services/sqlstore/transactions_test.go` | verified |  |
| grafana | `pkg/storage/legacysql/dualwrite/service_test.go` | verified |  |
| grafana | `pkg/tests/api/alerting/api_convert_prometheus_alertmanager_test.go` | verified |  |
| grafana | `pkg/tsdb/azuremonitor/standalone/main.go` | verified |  |
| grafana | `pkg/tsdb/grafana-testdata-datasource/usa_stats_test.go` | verified |  |
| grafana | `pkg/util/scheduler/scheduler_test.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/import-to-gma/ValidationStatus.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/insights/grafana/RulesByEvaluation.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/utils/amroutes.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/assistant/PanelAssistantHint.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/embedding/EmbeddedDashboard.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/DashboardDataLayerSet.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/utils/dashboardTemplateEnvelope.ts` | verified |  |
| grafana | `public/app/features/dashboard/components/GenAI/GenAIDashDescriptionButton.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/useDetailState.ts` | verified |  |
| grafana | `public/app/plugins/datasource/grafana-testdata-datasource/mocks/scenarios.ts` | verified |  |
