# Target OSS no-LLM dogfooding audit — continuation 491 (batch 492)

Run: 2026-07-23T06:19:59.171325+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/test/issue21897b.go` | verified |  |
| go | `src/cmd/compile/internal/noder/helpers.go` | verified |  |
| go | `src/cmd/compile/internal/types2/termlist_test.go` | verified |  |
| go | `src/crypto/des/internal_test.go` | verified |  |
| go | `src/encoding/base64/base64_test.go` | verified |  |
| go | `src/errors/errors_test.go` | verified |  |
| go | `src/internal/goarch/zgoarch_mips64p32le.go` | verified |  |
| go | `src/internal/runtime/gc/scan.go` | verified |  |
| go | `src/internal/runtime/maps/runtime.go` | verified |  |
| go | `src/net/cgo_resnew.go` | verified |  |
| go | `src/runtime/cgo/callbacks.go` | verified |  |
| go | `src/runtime/race/race_v1_amd64.go` | verified |  |
| go | `test/abi/zombie_struct_select.go` | verified |  |
| go | `test/fixedbugs/bug249.go` | verified |  |
| go | `test/fixedbugs/bug397.go` | verified |  |
| go | `test/fixedbugs/issue28053.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue40252.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue43942.go` | verified |  |
| go | `test/fixedbugs/issue59680.go` | verified |  |
| go | `test/fixedbugs/issue73888b.go` | verified |  |
| go | `test/typeparam/mdempsky/10.dir/a.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v1beta1/inhibitionrule_codec_gen.go` | verified |  |
| grafana | `apps/correlations/pkg/apis/correlation/v0alpha1/constants.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/rolebinding_object_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/connection/github/validator.go` | verified |  |
| grafana | `packages/grafana-runtime/src/services/logging/loggers.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/Cells/SparklineCell.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/themes/GlobalStyles/dashboardGrid.ts` | verified |  |
| grafana | `pkg/api/short_url.go` | verified |  |
| grafana | `pkg/expr/threshold_bench_test.go` | verified |  |
| grafana | `pkg/infra/nats/server.go` | verified |  |
| grafana | `pkg/registry/apis/datasource/metrics.go` | verified |  |
| grafana | `pkg/services/anonymous/anonimpl/anonstore/database.go` | verified |  |
| grafana | `pkg/services/apiserver/appinstaller/server.go` | verified |  |
| grafana | `pkg/services/authn/authnimpl/priority_queue.go` | verified |  |
| grafana | `pkg/services/live/remotewrite/remotewrite_test.go` | verified |  |
| grafana | `pkg/services/ngalert/schedule/sequence.go` | verified |  |
| grafana | `pkg/storage/unified/resource/usagestats/declaration.go` | verified |  |
| grafana | `pkg/tsdb/loki/standalone/datasource.go` | verified |  |
| grafana | `pkg/util/xorm/session_iterate.go` | verified |  |
| grafana | `public/app/core/components/Signup/VerifyEmail.tsx` | verified |  |
| grafana | `public/app/core/services/echo/backends/analytics/GA4Backend.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/saved-searches/InlineSaveInput.tsx` | verified |  |
| grafana | `public/app/features/connections/tabs/ConnectData/hooks/usePluginFiltering.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/interaction.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/layouts-shared/layoutRegistry.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/serialization/DashboardSceneSerializer.ts` | verified |  |
| grafana | `public/app/features/explore/RecentQueries/useRecentQueriesData.ts` | verified |  |
| grafana | `public/app/features/logs/components/logParser.ts` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/LogsQueryEditor/QueryField.tsx` | verified |  |
