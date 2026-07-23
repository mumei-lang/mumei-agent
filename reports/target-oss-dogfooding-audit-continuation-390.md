# Target OSS no-LLM dogfooding audit — continuation 390 (batch 391)

Run: 2026-07-23T00:07:47.879404+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/asm/internal/lex/slice.go` | verified |  |
| go | `src/cmd/internal/bootstrap_test/reboot_test.go` | verified |  |
| go | `src/crypto/internal/fips140/notpurego.go` | verified |  |
| go | `src/crypto/tls/cache_test.go` | verified |  |
| go | `src/internal/goexperiment/exp_loopvar_on.go` | verified |  |
| go | `src/mime/multipart/multipart.go` | verified |  |
| go | `src/net/file_posix.go` | verified |  |
| go | `src/runtime/mpagealloc_64bit.go` | verified |  |
| go | `src/runtime/signal_linux_loong64.go` | verified |  |
| go | `src/simd/archsimd/_gen/main.go` | verified |  |
| go | `test/append1.go` | verified |  |
| go | `test/fixedbugs/bug488.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue16133.go` | verified |  |
| go | `test/fixedbugs/issue67255.go` | verified |  |
| go | `test/fixedbugs/issue75278.go` | verified |  |
| go | `test/method.go` | verified |  |
| go | `test/typeparam/issue48185a.go` | verified |  |
| go | `test/typeparam/issue48185b.dir/a.go` | verified |  |
| grafana | `apps/annotation/pkg/apis/annotation/v0alpha1/annotation_spec_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/connection/github/extra_test.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/applyconfiguration/provisioning/v0alpha1/errordetails.go` | verified |  |
| grafana | `i18next.config.ts` | verified |  |
| grafana | `packages/grafana-flamegraph/src/CallTree/FunctionCellWithExpander.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/DataLinks/DataLinksInlineEditor/DataLinksInlineEditor.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/RadialGauge/RadialSparkline.tsx` | verified |  |
| grafana | `pkg/api/dtos/invite.go` | verified |  |
| grafana | `pkg/expr/mathexp/exp.go` | verified |  |
| grafana | `pkg/infra/usagestats/statscollector/prometheus_flavor.go` | verified |  |
| grafana | `pkg/plugins/manager/pipeline/initialization/steps.go` | verified |  |
| grafana | `pkg/plugins/test_utils.go` | verified |  |
| grafana | `pkg/registry/apis/iam/display/legacy_test.go` | verified |  |
| grafana | `pkg/server/wire.go` | verified |  |
| grafana | `pkg/services/apiserver/auth/authorizer/namespace.go` | verified |  |
| grafana | `pkg/services/frontend/request_config.go` | verified |  |
| grafana | `pkg/services/ngalert/lokiconfig/lokiconfig_test.go` | verified |  |
| grafana | `pkg/services/ngalert/state/multi_instance_reader_test.go` | verified |  |
| grafana | `pkg/services/queryhistory/queryhistory_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/v1beta1/connection_test.go` | verified |  |
| grafana | `pkg/tsdb/influxdb/flux/macros.go` | verified |  |
| grafana | `pkg/util/ring/adaptive_chan_test.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/export/GrafanaMuteTimingsExporter.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/receivers/grafanaAppReceivers/onCall/onCall.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/utils/rule-id.ts` | verified |  |
| grafana | `public/app/features/commandPalette/actions/deepSearchActions.ts` | verified |  |
| grafana | `public/app/features/datasources/hooks.ts` | verified |  |
| grafana | `public/app/features/provisioning/GettingStarted/GettingStarted.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/TracesQueryEditor/consts.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/language/cloudwatch-logs/syntax.ts` | verified |  |
| grafana | `public/app/plugins/datasource/graphite/components/FunctionsSection.tsx` | verified |  |
| grafana | `public/app/plugins/panel/timeseries/TimezonesEditor.tsx` | verified |  |
