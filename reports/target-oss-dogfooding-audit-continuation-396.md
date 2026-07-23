# Target OSS no-LLM dogfooding audit — continuation 396 (batch 397)

Run: 2026-07-23T00:28:57.391402+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/inline/inlheur/parampropbits_string.go` | verified |  |
| go | `src/cmd/compile/internal/types2/instantiate_test.go` | verified |  |
| go | `src/encoding/json/v2/inline_test.go` | verified |  |
| go | `src/expvar/expvar.go` | verified |  |
| go | `src/go/types/eval_test.go` | verified |  |
| go | `src/internal/nettest/listener_test.go` | verified |  |
| go | `src/internal/poll/sys_cloexec.go` | verified |  |
| go | `src/internal/xcoff/ar_test.go` | verified |  |
| go | `src/net/netcgo_off.go` | verified |  |
| go | `src/os/file_test.go` | verified |  |
| go | `src/simd/archsimd/internal/simd_test/reduce_arm64_test.go` | verified |  |
| go | `src/simd/archsimd/internal/simd_test/ternary_helpers_wider_test.go` | verified |  |
| go | `src/simd/archsimd/ops_arm64.go` | verified |  |
| go | `test/abi/open_defer_1.go` | verified |  |
| go | `test/fixedbugs/bug513.go` | verified |  |
| go | `test/fixedbugs/issue31637.go` | verified |  |
| go | `test/fixedbugs/issue49094.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue70175.go` | verified |  |
| go | `test/intrinsic_atomic.go` | verified |  |
| go | `test/nul1.go` | verified |  |
| grafana | `apps/advisor/pkg/apis/advisor/v0alpha1/check_codec_gen.go` | verified |  |
| grafana | `apps/alerting/rules/pkg/apis/alerting/v0alpha1/rulesequence_spec_gen.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v2beta1/conversion.go` | verified |  |
| grafana | `e2e-playwright/dashboard-new-layouts/page-objects/sidebar/Sidebar.ts` | verified |  |
| grafana | `packages/grafana-schema/src/schema/dashboard/v0alpha1/dashboard_object_gen.ts` | verified |  |
| grafana | `packages/grafana-sql/src/ResponseParser.ts` | verified |  |
| grafana | `pkg/api/login_oauth.go` | verified |  |
| grafana | `pkg/infra/filestorage/api_test.go` | verified |  |
| grafana | `pkg/registry/apis/query/clientapi/clientapi.go` | verified |  |
| grafana | `pkg/services/libraryelements/cache_test.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/legacy_storage/v1/model.go` | verified |  |
| grafana | `pkg/services/ngalert/store/deltas_test.go` | verified |  |
| grafana | `pkg/services/ngalert/store/json_test.go` | verified |  |
| grafana | `pkg/setting/setting_secure_socks_proxy_test.go` | verified |  |
| grafana | `pkg/storage/legacysql/dualwrite/types.go` | verified |  |
| grafana | `pkg/storage/unified/resource/unimplemented.go` | verified |  |
| grafana | `pkg/storage/unified/search/bleve_snapshot_upload.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/services/log_groups_test.go` | verified |  |
| grafana | `pkg/util/xorm/syslogger.go` | verified |  |
| grafana | `public/app/core/history/richHistoryLocalStorageUtils.ts` | verified |  |
| grafana | `public/app/core/utils/ticks.ts` | verified |  |
| grafana | `public/app/features/admin/UserListPublicDashboardPage/DeleteUserModalButton.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/utils/getRepeatLocalVariableValue.ts` | verified |  |
| grafana | `public/app/features/dashboard/components/ShareModal/SharePublicDashboard/ModalAlerts/UnsupportedDataSourcesAlert.tsx` | verified |  |
| grafana | `public/app/features/dimensions/editors/BackgroundSizeEditor.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/TracePageHeader/TraceAdHocFiltersController.ts` | verified |  |
| grafana | `public/app/features/expressions/components/QueryToolbox.tsx` | verified |  |
| grafana | `public/app/features/plugins/admin/components/PluginLogo.tsx` | verified |  |
| grafana | `public/app/features/provisioning/hooks/useIsProvisionedInstance.ts` | verified |  |
| grafana | `public/app/plugins/datasource/loki/mocks/createDetectedFieldValuesMetadataRequest.ts` | verified |  |
