# Target OSS no-LLM dogfooding audit — continuation 500 (batch 501)

Run: 2026-07-23T07:04:52.415352+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/compress/zlib/writer.go` | verified |  |
| go | `src/encoding/base64/base64.go` | verified |  |
| go | `src/encoding/json/tags.go` | verified |  |
| go | `src/encoding/json/v2/options.go` | verified |  |
| go | `src/flag/example_func_test.go` | verified |  |
| go | `src/go/doc/example_test.go` | verified |  |
| go | `src/hash/hash.go` | verified |  |
| go | `src/internal/goarch/zgoarch_ppc.go` | verified |  |
| go | `src/internal/syscall/unix/sysnum_linux_generic.go` | verified |  |
| go | `src/math/big/ratconv_test.go` | verified |  |
| go | `src/net/http/server.go` | verified |  |
| go | `src/net/iprawsock.go` | verified |  |
| go | `src/net/textproto/textproto.go` | verified |  |
| go | `src/os/exec_unix_test.go` | verified |  |
| go | `src/runtime/mpallocbits_test.go` | verified |  |
| go | `src/runtime/sys_nonppc64x.go` | verified |  |
| go | `src/time/zoneinfo_android.go` | verified |  |
| go | `test/codegen/bmi.go` | verified |  |
| go | `test/ddd.go` | verified |  |
| go | `test/fixedbugs/issue15975.go` | verified |  |
| go | `test/fixedbugs/issue23812.go` | verified |  |
| go | `test/fixedbugs/issue28450.go` | verified |  |
| go | `test/typeparam/dedup.dir/main.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v2beta1/types.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v2beta1/zz_generated.conversion.go` | verified |  |
| grafana | `apps/dashvalidator/pkg/validator/prometheus/benchmark_test.go` | verified |  |
| grafana | `packages/grafana-data/src/context/plugins/RestrictedGrafanaApis.tsx` | verified |  |
| grafana | `packages/grafana-i18n/src/types.ts` | verified |  |
| grafana | `packages/grafana-o11y-ds-frontend/src/TraceToMetrics/TraceToMetricsSettings.tsx` | verified |  |
| grafana | `packages/grafana-runtime/src/services/dataSourceSrv.ts` | verified |  |
| grafana | `packages/grafana-schema/src/raw/composable/barchart/panelcfg/x/types.gen.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Slider/RangeSlider.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/utils/debug.ts` | verified |  |
| grafana | `pkg/api/pluginproxy/token_provider_jwt.go` | verified |  |
| grafana | `pkg/login/social/connectors/gitlab_oauth.go` | verified |  |
| grafana | `pkg/registry/apis/userstorage/register_test.go` | verified |  |
| grafana | `pkg/services/live/pipeline/rule_builder_storage.go` | verified |  |
| grafana | `pkg/services/ssosettings/strategies/oauth_strategy.go` | verified |  |
| grafana | `pkg/tests/apis/dashboard/integration/api_validation_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/repository_conditions_patch_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/root_folder_sync_modes_test.go` | verified |  |
| grafana | `pkg/tsdb/sqlmacro/sqlmacro_test.go` | verified |  |
| grafana | `pkg/web/web.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/silences/SilenceDetails.tsx` | verified |  |
| grafana | `public/app/features/dashboard/components/TransformationsEditor/TransformationCard.tsx` | verified |  |
| grafana | `public/app/features/explore/hooks/utils.ts` | verified |  |
| grafana | `public/app/features/home/HomePageSkeleton.tsx` | verified |  |
| grafana | `public/app/features/teams/create-team/StepResultAlert.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/components/shared/LogGroups/LegacyLogGroupSelector.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/loki/queryHints.ts` | verified |  |
