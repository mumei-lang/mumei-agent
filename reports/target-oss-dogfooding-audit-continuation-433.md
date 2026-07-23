# Target OSS no-LLM dogfooding audit — continuation 433 (batch 434)

Run: 2026-07-23T02:09:06.643598+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/syntax/scanner_test.go` | verified |  |
| go | `src/cmd/compile/internal/types2/labels.go` | verified |  |
| go | `src/cmd/go/internal/vet/vetflag.go` | verified |  |
| go | `src/cmd/link/internal/ld/main.go` | verified |  |
| go | `src/go/constant/example_test.go` | verified |  |
| go | `src/hash/maphash/smhasher_test.go` | verified |  |
| go | `src/internal/syscall/unix/sysnum_linux_mipsx.go` | verified |  |
| go | `src/math/big/sqrt.go` | verified |  |
| go | `src/net/error_plan9_test.go` | verified |  |
| go | `src/os/error_unix_test.go` | verified |  |
| go | `src/runtime/cgo/callbacks_traceback.go` | verified |  |
| go | `test/escape_mutations.go` | verified |  |
| go | `test/fixedbugs/bug351.go` | verified |  |
| go | `test/fixedbugs/bug384.go` | verified |  |
| go | `test/fixedbugs/issue28797.go` | verified |  |
| go | `test/fixedbugs/issue49016.dir/c.go` | verified |  |
| go | `test/fixedbugs/shrd_zero_count.go` | verified |  |
| go | `test/index2.go` | verified |  |
| go | `test/method4.dir/prog.go` | verified |  |
| go | `test/typeparam/issue48344.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v1/validation.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/serviceaccount_object_gen.go` | verified |  |
| grafana | `packages/grafana-runtime/src/services/pluginSettings/getPluginSettings.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/DateTimePickers/DatePicker/DatePicker.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/List/List.tsx` | verified |  |
| grafana | `pkg/apiserver/registry/generic/storage_test.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/job_resource_result_test.go` | verified |  |
| grafana | `pkg/services/apiserver/builder/runner/admission_test.go` | verified |  |
| grafana | `pkg/services/secrets/manager/helpers.go` | verified |  |
| grafana | `pkg/services/serviceaccounts/proxy/service.go` | verified |  |
| grafana | `pkg/storage/unified/resource/kv/datastoretypes.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/connection/status_auth_test.go` | verified |  |
| grafana | `pkg/tsdb/Magefile.go` | verified |  |
| grafana | `pkg/tsdb/jaeger/jaeger_test.go` | verified |  |
| grafana | `public/app/core/components/AppChrome/QuickAdd/QuickAdd.tsx` | verified |  |
| grafana | `public/app/core/selectors/navModel.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/RecordingRulesNameSpaceAndGroupStep.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/notificaton-preview/NotificationPolicyDrawer.tsx` | verified |  |
| grafana | `public/app/features/datasources/tracking.ts` | verified |  |
| grafana | `public/app/features/explore/Explore.tsx` | verified |  |
| grafana | `public/app/features/gops/configuration-tracker/onCall/hooks.ts` | verified |  |
| grafana | `public/app/features/migrate-to-cloud/shared/AlertWithTraceID.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/mocks/cloudwatch-logs-test-data/whitespaceQuery.ts` | verified |  |
| grafana | `public/app/plugins/datasource/influxdb/components/editor/config-v2/AuthSettings.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/influxdb/components/editor/query/influxql/QueryEditorModeSwitcher.tsx` | verified |  |
| grafana | `public/app/plugins/panel/barchart/bars.ts` | verified |  |
| grafana | `public/app/plugins/panel/canvas/CanvasPanel.tsx` | verified |  |
| grafana | `public/app/plugins/panel/debug/DebugPanel.tsx` | verified |  |
| grafana | `public/app/plugins/panel/logstable/fieldSelector/buildColumnsWithMeta.ts` | verified |  |
| grafana | `public/app/plugins/panel/timeseries/plugins/utils.ts` | verified |  |
