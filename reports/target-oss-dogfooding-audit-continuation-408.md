# Target OSS no-LLM dogfooding audit — continuation 408 (batch 409)

Run: 2026-07-23T01:05:19.071316+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/trace/gstate.go` | verified |  |
| go | `src/debug/pe/symbols_test.go` | verified |  |
| go | `src/encoding/csv/writer_test.go` | verified |  |
| go | `src/encoding/json/v2_stream_test.go` | verified |  |
| go | `src/internal/race/doc.go` | verified |  |
| go | `src/internal/trace/traceviewer/http.go` | verified |  |
| go | `src/math/big/escape_test.go` | verified |  |
| go | `src/net/hook_windows.go` | verified |  |
| go | `src/os/executable_sysctl.go` | verified |  |
| go | `src/os/statat.go` | verified |  |
| go | `src/runtime/os_wasip1.go` | verified |  |
| go | `src/simd/archsimd/_gen/unify/env.go` | verified |  |
| go | `test/fixedbugs/bug402.go` | verified |  |
| go | `test/fixedbugs/bug464.go` | verified |  |
| go | `test/fixedbugs/issue19275.go` | verified |  |
| go | `test/fixedbugs/issue4909a.go` | verified |  |
| go | `test/float_lit3.go` | verified |  |
| go | `test/string_lit.go` | verified |  |
| grafana | `apps/alerting/rules/pkg/apis/alerting/v0alpha1/rulesequence_codec_gen.go` | verified |  |
| grafana | `apps/dashvalidator/pkg/cache/provider.go` | verified |  |
| grafana | `apps/example/pkg/apis/example/v1alpha1/constants.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/rolebinding_client_gen.go` | verified |  |
| grafana | `apps/logsdrilldown/pkg/apis/logsdrilldown/v1beta1/logsdrilldowndefaultlabels_spec_gen.go` | verified |  |
| grafana | `apps/shorturl/pkg/apis/shorturl_manifest.go` | verified |  |
| grafana | `packages/grafana-data/src/transformations/transformers/sortBy.ts` | verified |  |
| grafana | `packages/grafana-data/src/utils/arrayUtils.ts` | verified |  |
| grafana | `packages/grafana-data/src/utils/dataLinks.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Forms/FieldValidationMessage.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/PanelChrome/PanelStatus.tsx` | verified |  |
| grafana | `pkg/plugins/codegen/package_json.go` | verified |  |
| grafana | `pkg/registry/apis/dashboard/home/reader.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/history_writer.go` | verified |  |
| grafana | `pkg/registry/apps/alerting/rules/rulesequence/authorize.go` | verified |  |
| grafana | `pkg/registry/apps/shorturl/status.go` | verified |  |
| grafana | `pkg/services/accesscontrol/resourcepermissions/middleware.go` | verified |  |
| grafana | `pkg/services/authz/zanzana/client/shadow_client_test.go` | verified |  |
| grafana | `pkg/services/notifications/codes_test.go` | verified |  |
| grafana | `pkg/services/user/identity.go` | verified |  |
| grafana | `pkg/storage/unified/resource/eventstore.go` | verified |  |
| grafana | `pkg/util/xorm/session_cond.go` | verified |  |
| grafana | `public/app/core/services/echo/backends/grafana-javascript-agent/beforeSendHandler.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/insights/InsightsMenuButton.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/triage/scene/SummaryChart.tsx` | verified |  |
| grafana | `public/app/features/annotations/types.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/AutoRefreshIntervals.tsx` | verified |  |
| grafana | `public/app/features/dashboard/components/ShareModal/ShareLibraryPanel.tsx` | verified |  |
| grafana | `public/app/features/logs/components/panel/grammar.ts` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/ResourcePicker/styles.ts` | verified |  |
| grafana | `public/app/plugins/datasource/loki/querybuilder/operations.ts` | verified |  |
| grafana | `public/app/plugins/panel/geomap/types.ts` | verified |  |
