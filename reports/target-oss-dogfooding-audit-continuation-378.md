# Target OSS no-LLM dogfooding audit — continuation 378 (batch 379)

Run: 2026-07-22T23:15:52.075671+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/amd64/ggen.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/opGen.go` | verified |  |
| go | `src/cmd/compile/internal/types2/resolver.go` | verified |  |
| go | `src/encoding/json/v2/fields_test.go` | verified |  |
| go | `src/internal/goexperiment/exp_regabiwrappers_off.go` | verified |  |
| go | `src/internal/trace/testtrace/expectation.go` | verified |  |
| go | `src/math/big/internal/asmgen/mips.go` | verified |  |
| go | `src/os/wait6_freebsd_386.go` | verified |  |
| go | `src/runtime/chanbarrier_test.go` | verified |  |
| go | `src/runtime/time_test.go` | verified |  |
| go | `src/simd/archsimd/_gen/unify/domain.go` | verified |  |
| go | `src/syscall/flock_linux.go` | verified |  |
| go | `test/codegen/strings.go` | verified |  |
| go | `test/fixedbugs/bug185.go` | verified |  |
| go | `test/fixedbugs/bug478.go` | verified |  |
| go | `test/fixedbugs/issue30659.go` | verified |  |
| go | `test/fixedbugs/issue3783.go` | verified |  |
| go | `test/ken/chan.go` | verified |  |
| grafana | `apps/dashvalidator/pkg/validator/errors.go` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/iam/v0alpha1/baseAPI.ts` | verified |  |
| grafana | `packages/grafana-api-clients/src/generator/openapi.ts` | verified |  |
| grafana | `packages/grafana-test-utils/src/handlers/helpers.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Monaco/ReactMonacoEditorLazy.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/types/forms.ts` | verified |  |
| grafana | `pkg/apis/datasource/v0alpha1/sqlschema.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/informer/connection.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs.go` | verified |  |
| grafana | `pkg/services/ngalert/api/tooling/definitions/eval_condition.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/file_store_test.go` | verified |  |
| grafana | `pkg/services/ngalert/tests/fakes/config.go` | verified |  |
| grafana | `pkg/services/search/sort/sorting.go` | verified |  |
| grafana | `pkg/services/sqlstore/bulk_test.go` | verified |  |
| grafana | `pkg/storage/unified/testing/storage_backend_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/apiversion/version_test.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/bridges/DeclareIncidentButton.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/import-to-gma/CollapsibleRenameList.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/triage/instance-details/InstanceSilenceForm.tsx` | verified |  |
| grafana | `public/app/features/auth-config/constants.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/behaviors/DashboardAnalyticsInitializerBehavior.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/sharing/ShareButton/share-externally/EmailShare/ConfigEmailSharing/ConfigEmailSharing.tsx` | verified |  |
| grafana | `public/app/features/explore/Graph/utils.ts` | verified |  |
| grafana | `public/app/features/panel/options/builder/annotations.ts` | verified |  |
| grafana | `public/app/features/plugins/extensions/errors.ts` | verified |  |
| grafana | `public/app/features/plugins/extensions/getPluginExtensions.ts` | verified |  |
| grafana | `public/app/features/provisioning/Config/ConfigForm.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/grafanaTemplateVariableFns.ts` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/utils/messageFromError.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/mocks/cloudwatch-sql-test-data/singleLineEmptyQuery.ts` | verified |  |
| grafana | `public/app/plugins/datasource/graphite/components/PlayButton.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/influxdb/components/editor/query/influxql/visual/VisualInfluxQLEditor.tsx` | verified |  |
