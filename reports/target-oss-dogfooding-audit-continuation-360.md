# Target OSS no-LLM dogfooding audit — continuation 360 (batch 361)

Run: 2026-07-22T21:33:27.151406+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/test/backdoor.go` | verified |  |
| go | `src/cmd/compile/internal/devirtualize/pgo.go` | verified |  |
| go | `src/cmd/compile/internal/ir/class_string.go` | verified |  |
| go | `src/crypto/internal/fips140/nistec/fiat/cast.go` | verified |  |
| go | `src/hash/fnv/fnv.go` | verified |  |
| go | `src/internal/routebsd/interface.go` | verified |  |
| go | `src/math/big/int_test.go` | verified |  |
| go | `src/net/http/clone.go` | verified |  |
| go | `src/runtime/sigqueue_note.go` | verified |  |
| go | `test/fixedbugs/bug507.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue14540.go` | verified |  |
| go | `test/fixedbugs/issue27201.go` | verified |  |
| go | `test/fixedbugs/issue30606b.go` | verified |  |
| go | `test/fixedbugs/issue5755.dir/main.go` | verified |  |
| go | `test/typeparam/issue53087.go` | verified |  |
| go | `test/typeparam/issue54765.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/serviceaccount_client_gen.go` | verified |  |
| grafana | `packages/grafana-flamegraph/src/FlameGraphHeader.tsx` | verified |  |
| grafana | `packages/grafana-sql/src/components/visual-query-builder/OrderByRow.tsx` | verified |  |
| grafana | `packages/grafana-test-utils/src/handlers/api/search/constants.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/DateTimePickers/TimeRangePicker/TimePickerFooter.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/slate-plugins/slate-prism/index.ts` | verified |  |
| grafana | `pkg/api/dtos/prefs.go` | verified |  |
| grafana | `pkg/api/pluginproxy/pluginproxy.go` | verified |  |
| grafana | `pkg/api/pluginproxy/token_provider_azure.go` | verified |  |
| grafana | `pkg/api/pluginproxy/token_provider_generic.go` | verified |  |
| grafana | `pkg/apis/service/v0alpha1/doc.go` | verified |  |
| grafana | `pkg/cmd/grafana-server/commands/flags.go` | verified |  |
| grafana | `pkg/services/accesscontrol/resourcepermissions/api_adapter_test.go` | verified |  |
| grafana | `pkg/services/authz/zanzana/schema/transform.go` | verified |  |
| grafana | `pkg/services/extsvcauth/errors.go` | verified |  |
| grafana | `pkg/services/extsvcauth/registry/service_test.go` | verified |  |
| grafana | `pkg/services/live/pipeline/frame_processor_drop_field.go` | verified |  |
| grafana | `pkg/storage/unified/resource/kv/dialect.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/jobs/historicjobs_auth_test.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/models/resources/log_group_fields_resource_request_test.go` | verified |  |
| grafana | `public/app/core/components/AppChrome/QuickAdd/utils.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/receivers/editor/alertManagerSuggestions.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/utils/parseJsonWithSchema.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/utils/rules.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/mutation-api/commands/removeAnnotation.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/VariablesEditView.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/links/LinkAddEditableElement.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/selectors/trace.fixture.ts` | verified |  |
| grafana | `public/app/features/explore/utils/links.ts` | verified |  |
| grafana | `public/app/features/profile/types.ts` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/LogsQueryBuilder/FilterSection.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/components/shared/Account.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/influxdb/fsql/sqlUtil.ts` | verified |  |
| grafana | `public/app/plugins/panel/live/types.ts` | verified |  |
