# Target OSS no-LLM dogfooding audit — continuation 464 (batch 465)

Run: 2026-07-23T04:09:43.327371+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/testgodefs/testgodefs_test.go` | verified |  |
| go | `src/cmd/compile/internal/ir/check_reassign_yes.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/debug_lines_test.go` | verified |  |
| go | `src/cmd/compile/internal/typecheck/mkbuiltin.go` | verified |  |
| go | `src/cmd/compile/internal/types2/errorcalls_test.go` | verified |  |
| go | `src/cmd/link/internal/ld/fips140.go` | verified |  |
| go | `src/crypto/md5/md5_test.go` | verified |  |
| go | `src/crypto/pbkdf2/pbkdf2_wycheproof_test.go` | verified |  |
| go | `src/html/template/state_string.go` | verified |  |
| go | `src/internal/routebsd/sys_freebsd.go` | verified |  |
| go | `src/os/exec/lp_wasm.go` | verified |  |
| go | `src/os/export_windows_test.go` | verified |  |
| go | `src/os/file_open_unix.go` | verified |  |
| go | `src/runtime/signal_plan9.go` | verified |  |
| go | `src/runtime/vdso_linux_arm.go` | verified |  |
| go | `src/syscall/zsyscall_darwin_arm64.go` | verified |  |
| go | `src/syscall/zsysnum_openbsd_arm64.go` | verified |  |
| go | `test/fixedbugs/issue18231.go` | verified |  |
| go | `test/fixedbugs/issue4654.go` | verified |  |
| go | `test/inline.go` | verified |  |
| go | `test/typeparam/issue44688.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v24.go` | verified |  |
| grafana | `e2e-playwright/test-plugins/grafana-extensionstest-app/plugins/grafana-extensionexample2-app/module.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Combobox/getMultiComboboxStyles.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/Cells/GeoCell.tsx` | verified |  |
| grafana | `pkg/api/utils.go` | verified |  |
| grafana | `pkg/infra/features/baggage.go` | verified |  |
| grafana | `pkg/infra/httpclient/httpclientprovider/datasource_metrics_middleware_test.go` | verified |  |
| grafana | `pkg/infra/tracing/tracing_config.go` | verified |  |
| grafana | `pkg/registry/apis/iam/legacysort/sort_test.go` | verified |  |
| grafana | `pkg/services/accesscontrol/ossaccesscontrol/dashboard.go` | verified |  |
| grafana | `pkg/services/dashboards/service/dashboard_service.go` | verified |  |
| grafana | `pkg/services/datasources/service/datasource.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/dashboards/filestore_test.go` | verified |  |
| grafana | `pkg/storage/unified/search/options_test.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/constants/metrics.go` | verified |  |
| grafana | `public/app/core/components/RolePicker/constants.ts` | verified |  |
| grafana | `public/app/core/components/SharedPreferences/analytics/main.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/contact-points/useContactPointsSearch.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/mocks/server/configure/datasources.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/utils/annotations.tsx` | verified |  |
| grafana | `public/app/features/correlations/Forms/AddCorrelationForm.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/sharing/ExportButton/ExportAsCode.tsx` | verified |  |
| grafana | `public/app/features/dashboard/components/PanelEditor/state/getRecentOptions.ts` | verified |  |
| grafana | `public/app/features/playlist/ShareModal.tsx` | verified |  |
| grafana | `public/app/features/provisioning/Shared/ProgressBar.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/mocks/CloudWatchVariables.ts` | verified |  |
| grafana | `public/app/plugins/datasource/grafana-testdata-datasource/components/RawFrameEditor.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/grafana-testdata-datasource/metricTree.ts` | verified |  |
| grafana | `public/app/plugins/panel/status-history/module.tsx` | verified |  |
