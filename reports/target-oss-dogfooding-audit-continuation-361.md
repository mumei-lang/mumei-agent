# Target OSS no-LLM dogfooding audit — continuation 361 (batch 362)

Run: 2026-07-22T21:35:49.579361+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/types2/index.go` | verified |  |
| go | `src/cmd/go/internal/lockedfile/lockedfile_plan9.go` | verified |  |
| go | `src/crypto/internal/fips140/aes/gcm/gcm_generic.go` | verified |  |
| go | `src/encoding/base32/base32_test.go` | verified |  |
| go | `src/encoding/json/v2_scanner.go` | verified |  |
| go | `src/go/scanner/example_test.go` | verified |  |
| go | `src/internal/race/race.go` | verified |  |
| go | `src/math/big/internal/asmgen/func.go` | verified |  |
| go | `src/os/readfrom_unix_test.go` | verified |  |
| go | `src/reflect/value.go` | verified |  |
| go | `src/runtime/pprof/defs_darwin_arm64.go` | verified |  |
| go | `src/simd/archsimd/cpu_other.go` | verified |  |
| go | `src/syscall/export_bsd_test.go` | verified |  |
| go | `test/fixedbugs/bug318.go` | verified |  |
| go | `test/fixedbugs/bug426.go` | verified |  |
| go | `test/fixedbugs/issue10925.go` | verified |  |
| go | `test/fixedbugs/issue5260.go` | verified |  |
| go | `test/interface/recursive1.dir/recursive2.go` | verified |  |
| go | `test/rotate3.go` | verified |  |
| grafana | `apps/advisor/pkg/apis/advisor/v0alpha1/checktype_client_gen.go` | verified |  |
| grafana | `apps/advisor/pkg/app/checks/utils_test.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v1beta1/templategroup_client_gen.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/conversion/v2_to_v1beta1.go` | verified |  |
| grafana | `packages/grafana-data/src/types/trace.ts` | verified |  |
| grafana | `packages/grafana-e2e-selectors/src/index.ts` | verified |  |
| grafana | `packages/grafana-o11y-ds-frontend/src/IntervalInput/IntervalInput.tsx` | verified |  |
| grafana | `packages/grafana-runtime/src/analytics/utils.ts` | verified |  |
| grafana | `packages/grafana-runtime/src/utils/megaMenuOpen.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/uPlot/config/UPlotConfigBuilder.ts` | verified |  |
| grafana | `pkg/middleware/loggermw/logger_test.go` | verified |  |
| grafana | `pkg/plugins/manager/client/client_test.go` | verified |  |
| grafana | `pkg/plugins/manager/installer.go` | verified |  |
| grafana | `pkg/registry/apis/dashboard/snapshot/routes.go` | verified |  |
| grafana | `pkg/services/ldap/helpers.go` | verified |  |
| grafana | `pkg/services/ngalert/accesscontrol/fakes/receivers.go` | verified |  |
| grafana | `pkg/services/ngalert/state/template/template_test.go` | verified |  |
| grafana | `pkg/storage/legacysql/time.go` | verified |  |
| grafana | `public/app/core/components/AppNotifications/NotificationButton.tsx` | verified |  |
| grafana | `public/app/core/navigation/GrafanaRoute.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/receivers/NewReceiverView.tsx` | verified |  |
| grafana | `public/app/features/annotations/components/AnnotationQueryEditorActionsWrapper.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditPanelWrapper.tsx` | verified |  |
| grafana | `public/app/features/dashboard/components/PanelEditor/getPanelFrameOptions.tsx` | verified |  |
| grafana | `public/app/features/dashboard/components/ShareModal/SharePublicDashboard/SharePublicDashboardUtils.ts` | verified |  |
| grafana | `public/app/features/explore/TraceView/TraceViewContainer.tsx` | verified |  |
| grafana | `public/app/features/logs/components/fieldSelector/FieldSearch.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/components/QueryEditor/MetricsQueryEditor/SQLBuilderEditor/SQLGroupBy.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/tracking.ts` | verified |  |
| grafana | `public/app/plugins/datasource/graphite/components/FunctionParamEditor.tsx` | verified |  |
| grafana | `public/app/plugins/panel/geomap/__fixtures__/olMapMock.ts` | verified |  |
