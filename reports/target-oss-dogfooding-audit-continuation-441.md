# Target OSS no-LLM dogfooding audit — continuation 441 (batch 442)

Run: 2026-07-23T02:31:49.307497+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/test/issue23555b/a.go` | verified |  |
| go | `src/cmd/compile/internal/ir/ir.go` | verified |  |
| go | `src/cmd/internal/obj/mips/list0.go` | verified |  |
| go | `src/crypto/cipher/gcm_test.go` | verified |  |
| go | `src/crypto/cipher/ofb_test.go` | verified |  |
| go | `src/crypto/internal/fips140/aes/ctr_arm64_gen.go` | verified |  |
| go | `src/net/platform_plan9_test.go` | verified |  |
| go | `src/net/textproto/reader.go` | verified |  |
| go | `src/runtime/debuglog_off.go` | verified |  |
| go | `src/runtime/lockrank_off.go` | verified |  |
| go | `src/runtime/race/syso_test.go` | verified |  |
| go | `src/syscall/wtf8_windows.go` | verified |  |
| go | `test/fixedbugs/bug296.go` | verified |  |
| go | `test/fixedbugs/bug306.dir/p1.go` | verified |  |
| go | `test/fixedbugs/issue22822.go` | verified |  |
| go | `test/goto.go` | verified |  |
| go | `test/reflectmethod5.go` | verified |  |
| go | `test/reorder2.go` | verified |  |
| go | `test/typeparam/issue48016.go` | verified |  |
| go | `test/typeparam/issue48198.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/team_deleteteammember_response_object_types_gen.go` | verified |  |
| grafana | `packages/grafana-data/src/types/thresholds.ts` | verified |  |
| grafana | `packages/grafana-e2e-selectors/src/selectors/pages.ts` | verified |  |
| grafana | `packages/grafana-test-utils/src/handlers/apis/collections.grafana.app/v1alpha1/handlers.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/DataLinks/DataLinksInlineEditor/DataLinkEditorModalContent.tsx` | verified |  |
| grafana | `pkg/apimachinery/utils/manager.go` | verified |  |
| grafana | `pkg/registry/apis/iam/user/store_wrapper_test.go` | verified |  |
| grafana | `pkg/services/accesscontrol/actest/store_mock.go` | verified |  |
| grafana | `pkg/services/authz/zanzana/server/server_write.go` | verified |  |
| grafana | `pkg/services/cloudmigration/gmsclient/client.go` | verified |  |
| grafana | `pkg/services/ngalert/sender/notifier.go` | verified |  |
| grafana | `pkg/services/publicdashboards/internal/commands/generate_datasources/main.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/folder_uid_mig.go` | verified |  |
| grafana | `pkg/storage/unified/sql/backend_bulk_chunked_test.go` | verified |  |
| grafana | `pkg/tests/alertmanager/alertmanager_test.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/utils/metrics_test.go` | verified |  |
| grafana | `public/app/core/components/AppChrome/MegaMenu/MegaMenu.tsx` | verified |  |
| grafana | `public/app/core/components/RolePickerDrawer/RolePickerSelect.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/api/stateHistoryApi.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/receivers/TemplateDataDocs.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/AnnotationHeaderField.tsx` | verified |  |
| grafana | `public/app/features/datasources/state/navModel.ts` | verified |  |
| grafana | `public/app/features/logs/components/panel/LogLineDetailsTrace.tsx` | verified |  |
| grafana | `public/app/features/plugins/admin/components/PluginListItemBadges.tsx` | verified |  |
| grafana | `public/app/features/provisioning/Job/JobSummary.tsx` | verified |  |
| grafana | `public/app/features/transformers/timeSeriesTable/applicability.ts` | verified |  |
| grafana | `public/app/features/variables/query/reducer.ts` | verified |  |
| grafana | `public/app/plugins/panel/candlestick/defaultOptions.ts` | verified |  |
| grafana | `public/app/plugins/panel/histogram/HistogramTooltip.tsx` | verified |  |
| grafana | `public/app/plugins/panel/news/types.ts` | verified |  |
