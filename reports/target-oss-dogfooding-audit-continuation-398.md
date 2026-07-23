# Target OSS no-LLM dogfooding audit — continuation 398 (batch 399)

Run: 2026-07-23T00:32:41.967350+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/deadlocals/deadlocals.go` | verified |  |
| go | `src/cmd/go/internal/auth/netrc.go` | verified |  |
| go | `src/cmd/preprofile/main.go` | verified |  |
| go | `src/crypto/internal/fips140/sha3/shake.go` | verified |  |
| go | `src/go/types/hash.go` | verified |  |
| go | `src/image/jpeg/writer_test.go` | verified |  |
| go | `src/internal/bytealg/equal_generic.go` | verified |  |
| go | `src/internal/goexperiment/exp_greenteagc_off.go` | verified |  |
| go | `src/math/big/ratmarsh.go` | verified |  |
| go | `src/regexp/backtrack.go` | verified |  |
| go | `src/runtime/export_test.go` | verified |  |
| go | `src/simd/archsimd/other_gen_amd64.go` | verified |  |
| go | `src/slices/sort_benchmark_test.go` | verified |  |
| go | `test/alias.go` | verified |  |
| go | `test/fixedbugs/gcc61264.go` | verified |  |
| go | `test/fixedbugs/issue13365.go` | verified |  |
| go | `test/fixedbugs/issue40746.go` | verified |  |
| go | `test/fixedbugs/issue58300b.go` | verified |  |
| go | `test/fixedbugs/issue6131.go` | verified |  |
| grafana | `apps/advisor/pkg/app/checks/healthchecker.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v16_test.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/externalgroupmapping_codec_gen.go` | verified |  |
| grafana | `packages/grafana-runtime/src/services/pluginMeta/types/plugin/types.status.gen.ts` | verified |  |
| grafana | `packages/grafana-schema/src/raw/composable/debug/panelcfg/x/types.gen.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/DateTimePickers/TimeRangePicker/TimeRangeOption.tsx` | verified |  |
| grafana | `pkg/api/bootdata_test.go` | verified |  |
| grafana | `pkg/registry/apis/dashboard/snapshot/snapshot_fields.go` | verified |  |
| grafana | `pkg/services/auth/external_session.go` | verified |  |
| grafana | `pkg/services/dashboardversion/dashverimpl/dashver.go` | verified |  |
| grafana | `pkg/services/ngalert/remote/client/alertmanager_configuration.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/pluginsettings/decrypted_test.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/ualert/state_annotations_mig.go` | verified |  |
| grafana | `pkg/storage/unified/apistore/managed_test.go` | verified |  |
| grafana | `pkg/storage/unified/resource/usagestats/usagestats_test.go` | verified |  |
| grafana | `pkg/util/interface_test.go` | verified |  |
| grafana | `pkg/util/xorm/statement_args.go` | verified |  |
| grafana | `public/app/features/alerting/unified/hooks/useSlowQuery.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/mutation-api/commands/listAnnotations.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/saving/DashboardSceneChangeTracker.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/LibraryPanelBehavior.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/setDashboardPanelContext.ts` | verified |  |
| grafana | `public/app/features/datasources/components/DataSourcePluginSettings.tsx` | verified |  |
| grafana | `public/app/features/explore/CorrelationUnsavedChangesModal.tsx` | verified |  |
| grafana | `public/app/features/gops/configuration-tracker/Analytics.ts` | verified |  |
| grafana | `public/app/features/logs/logsFrame.ts` | verified |  |
| grafana | `public/app/features/provisioning/components/Dashboards/MoveProvisionedDashboardForm.tsx` | verified |  |
| grafana | `public/app/features/serviceaccounts/ServiceAccountPage.tsx` | verified |  |
| grafana | `public/app/features/variables/shared/testing/queryVariableBuilder.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/components/QueryEditor/MetricsQueryEditor/MetricsQueryEditor.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/grafana-testdata-datasource/variables.ts` | verified |  |
