# Target OSS no-LLM dogfooding audit — continuation 539 (batch 540)

Run: 2026-07-23T09:28:26.487440+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/test/iface_test.go` | verified |  |
| go | `src/cmd/link/internal/ld/macho_combine_dwarf.go` | verified |  |
| go | `src/compress/flate/load_store.go` | verified |  |
| go | `src/context/x_test.go` | verified |  |
| go | `src/crypto/elliptic/p224_test.go` | verified |  |
| go | `src/crypto/x509/internal/macos/corefoundation.go` | verified |  |
| go | `src/internal/syscall/windows/security_windows.go` | verified |  |
| go | `src/net/interface_bsd.go` | verified |  |
| go | `src/net/rlimit_unix.go` | verified |  |
| go | `src/path/filepath/example_unix_test.go` | verified |  |
| go | `src/path/match.go` | verified |  |
| go | `src/simd/archsimd/internal/simd_test/shift_helpers_wider_test.go` | verified |  |
| go | `src/unicode/letter_test.go` | verified |  |
| go | `test/fixedbugs/bug112.go` | verified |  |
| go | `test/fixedbugs/bug303.go` | verified |  |
| go | `test/fixedbugs/bug404.go` | verified |  |
| go | `test/fixedbugs/bug470.go` | verified |  |
| go | `test/fixedbugs/issue18419.dir/other.go` | verified |  |
| go | `test/fixedbugs/issue20185.go` | verified |  |
| go | `test/fixedbugs/issue32901.dir/main.go` | verified |  |
| go | `test/fixedbugs/issue5963.go` | verified |  |
| go | `test/ken/label.go` | verified |  |
| go | `test/rangegen.go` | verified |  |
| go | `test/rename.go` | verified |  |
| go | `test/typeparam/mdempsky/10.dir/b.go` | verified |  |
| grafana | `apps/advisor/pkg/app/checks/datasourcecheck/missing_plugin_step.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v36_test.go` | verified |  |
| grafana | `apps/folder/pkg/apis/manifestdata/folder_manifest.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/github/webhook_test.go` | verified |  |
| grafana | `packages/grafana-flamegraph/src/constants.ts` | verified |  |
| grafana | `packages/grafana-sql/src/utils/migration.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/ConfirmModal/ConfirmModal.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/InfoBox/InfoBox.tsx` | verified |  |
| grafana | `pkg/infra/httpclient/httpclientprovider/host_redirect_validation_middleware_test.go` | verified |  |
| grafana | `pkg/middleware/request_tracing.go` | verified |  |
| grafana | `pkg/plugins/envvars/envvars.go` | verified |  |
| grafana | `pkg/registry/apis/iam/team/mutate.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/sync/changes_test.go` | verified |  |
| grafana | `pkg/services/ngalert/api/api_ruler_export_test.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/pluginsettings/service/service.go` | verified |  |
| grafana | `pkg/services/setting/service_test.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/accesscontrol/errors.go` | verified |  |
| grafana | `public/app/core/monacoEnv.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/CollapseToggle.tsx` | verified |  |
| grafana | `public/app/features/connections/pages/CacheFeatureHighlightPage.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelVizTypePicker.tsx` | verified |  |
| grafana | `public/app/features/provisioning/useGetActiveJob.ts` | verified |  |
| grafana | `public/app/features/transformers/calculateHeatmap/editor/AxisEditor.tsx` | verified |  |
| grafana | `public/app/features/variables/datasource/reducer.ts` | verified |  |
| grafana | `public/app/plugins/panel/news/panelcfg.gen.ts` | verified |  |
