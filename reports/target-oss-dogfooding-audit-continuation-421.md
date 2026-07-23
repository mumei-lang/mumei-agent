# Target OSS no-LLM dogfooding audit — continuation 421 (batch 422)

Run: 2026-07-23T01:34:42.619386+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/inline/inlheur/analyze_func_callsites.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/passbm_test.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/writebarrier.go` | verified |  |
| go | `src/crypto/internal/boring/ecdh.go` | verified |  |
| go | `src/crypto/internal/fips140/edwards25519/field/fe_amd64.go` | verified |  |
| go | `src/net/fd_posix.go` | verified |  |
| go | `src/net/http/httptest/recorder_test.go` | verified |  |
| go | `src/net/port.go` | verified |  |
| go | `src/regexp/exec2_test.go` | verified |  |
| go | `src/runtime/cpuflags.go` | verified |  |
| go | `src/runtime/metrics_cgo_test.go` | verified |  |
| go | `src/simd/archsimd/ops_internal_arm64.go` | verified |  |
| go | `src/simd/archsimd/slice_gen_arm64.go` | verified |  |
| go | `src/syscall/types_dragonfly.go` | verified |  |
| go | `test/fixedbugs/bug000.go` | verified |  |
| go | `test/fixedbugs/bug488.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue64565.go` | verified |  |
| go | `test/fixedbugs/issue8836.go` | verified |  |
| go | `test/typeparam/mutualimp.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/serviceaccount_createserviceaccounttoken_response_body_types_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/applyconfiguration/provisioning/v0alpha1/branchoptions.go` | verified |  |
| grafana | `packages/grafana-data/src/transformations/transformers/groupBy.ts` | verified |  |
| grafana | `packages/grafana-data/src/types/flot.ts` | verified |  |
| grafana | `packages/grafana-runtime/src/utils/userStorage.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/ScrollContainer/ScrollIndicators.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Segment/styles.ts` | verified |  |
| grafana | `pkg/infra/tracing/test_helper.go` | verified |  |
| grafana | `pkg/plugins/codegen/jenny_plugintstypes.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/migrate/mock_wrap_with_stage_fn.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/resources/parser_test.go` | verified |  |
| grafana | `pkg/services/accesscontrol/ossaccesscontrol/team.go` | verified |  |
| grafana | `pkg/services/ldap/api/service_test.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/migrations_test.go` | verified |  |
| grafana | `pkg/setting/settings_zanzana.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/foldermetadata/folder_authorization_test.go` | verified |  |
| grafana | `public/app/core/components/AppChrome/TopBar/SingleTopBarActions.tsx` | verified |  |
| grafana | `public/app/core/components/Login/LoginPage.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/extensions/AlertingRuleExtensionPointMenu.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/mute-timings/MuteTimingTimeRange.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/saved-searches/InlineRenameInput.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/inspect/StandardErrorsAndNoticesInspector.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/inspect/panelInspectorOpener.ts` | verified |  |
| grafana | `public/app/features/support-bundles/SupportBundlesCreate.tsx` | verified |  |
| grafana | `public/app/features/variables/adhoc/actions.ts` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/types/logAnalyticsMetadata.ts` | verified |  |
| grafana | `public/app/plugins/datasource/loki/components/monaco-query-field/MonacoQueryFieldWrapper.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/loki/components/monaco-query-field/monaco-completion-provider/validation.ts` | verified |  |
| grafana | `public/app/plugins/datasource/loki/lineParser.ts` | verified |  |
| grafana | `public/app/plugins/panel/timeseries/overrides/colorSeriesConfigFactory.ts` | verified |  |
| grafana | `public/test/helpers/TestProvider.tsx` | verified |  |
