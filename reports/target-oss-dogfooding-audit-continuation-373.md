# Target OSS no-LLM dogfooding audit — continuation 373 (batch 374)

Run: 2026-07-22T22:27:36.939480+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/asm/internal/flags/flags.go` | verified |  |
| go | `src/cmd/compile/internal/arm/ggen.go` | verified |  |
| go | `src/cmd/compile/internal/walk/switch.go` | verified |  |
| go | `src/cmd/go/internal/base/limit.go` | verified |  |
| go | `src/cmd/internal/obj/loong64/inst.go` | verified |  |
| go | `src/crypto/internal/boring/hmac.go` | verified |  |
| go | `src/crypto/tls/fipsonly/fipsonly_test.go` | verified |  |
| go | `src/internal/cpu/cpu_mipsle.go` | verified |  |
| go | `src/internal/fuzz/mem.go` | verified |  |
| go | `src/internal/trace/batch.go` | verified |  |
| go | `src/io/ioutil/tempfile_test.go` | verified |  |
| go | `src/runtime/signal_windows_test.go` | verified |  |
| go | `src/syscall/syscall_js.go` | verified |  |
| go | `src/syscall/zsyscall_linux_ppc64le.go` | verified |  |
| go | `test/abi/spills4.go` | verified |  |
| go | `test/codegen/clobberdead.go` | verified |  |
| go | `test/codegen/issue56440.go` | verified |  |
| go | `test/fixedbugs/bug19403.go` | verified |  |
| go | `test/fixedbugs/bug329.go` | verified |  |
| go | `test/fixedbugs/issue26341.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue58563.go` | verified |  |
| go | `test/fixedbugs/issue61127.go` | verified |  |
| go | `test/fixedbugs/issue71226.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v1beta1/timeinterval_object_gen.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/app/conversion.go` | verified |  |
| grafana | `apps/logsdrilldown/pkg/apis/logsdrilldown/v1beta1/logsdrilldowndefaultlabels_schema_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/applyconfiguration/provisioning/v0alpha1/jobstatus.go` | verified |  |
| grafana | `e2e-playwright/test-plugins/grafana-test-panel/tests/utils.ts` | verified |  |
| grafana | `pkg/infra/usagestats/service.go` | verified |  |
| grafana | `pkg/services/accesscontrol/roles.go` | verified |  |
| grafana | `pkg/services/apiserver/builder/runner/builder.go` | verified |  |
| grafana | `pkg/services/ngalert/api/prometheus/util.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/correlations_mig.go` | verified |  |
| grafana | `pkg/services/store/entity.go` | verified |  |
| grafana | `pkg/storage/unified/resource/cdk_blob_test.go` | verified |  |
| grafana | `pkg/tests/apis/alerting/rules/recordingrule/recordingrule_test.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/backtesting/BacktestPanel.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-viewer/tabs/version-history/VersionHistoryTable.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/types/amroutes.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/mutation-api/types.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/TransformationDebugDisplay.tsx` | verified |  |
| grafana | `public/app/features/geo/utils/frameVectorSource.ts` | verified |  |
| grafana | `public/app/features/manage-dashboards/import/utils/uidFieldText.ts` | verified |  |
| grafana | `public/app/features/plugins/extensions/appUtils.tsx` | verified |  |
| grafana | `public/app/features/profile/UserTeams.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/dashboard/constants.ts` | verified |  |
| grafana | `public/app/plugins/datasource/jaeger/testResponse.ts` | verified |  |
| grafana | `public/app/plugins/panel/nodeGraph/useCategorizeFrames.ts` | verified |  |
| grafana | `public/app/plugins/panel/timeseries/suggestions.ts` | verified |  |
| grafana | `public/test/mocks/images.ts` | verified |  |
