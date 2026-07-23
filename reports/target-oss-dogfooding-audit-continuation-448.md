# Target OSS no-LLM dogfooding audit — continuation 448 (batch 449)

Run: 2026-07-23T02:56:45.299358+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/asm/internal/asm/endtoend_test.go` | verified |  |
| go | `src/cmd/cgo/godefs.go` | verified |  |
| go | `src/cmd/cgo/internal/swig/swig_test.go` | verified |  |
| go | `src/cmd/go/go11.go` | verified |  |
| go | `src/cmd/go/internal/base/tool.go` | verified |  |
| go | `src/crypto/mldsa/mldsa_fips140v1.0_test.go` | verified |  |
| go | `src/internal/cpu/cpu_ppc64x_aix.go` | verified |  |
| go | `src/internal/cpu/cpu_x86.go` | verified |  |
| go | `src/internal/syscall/unix/faccessat_darwin.go` | verified |  |
| go | `src/log/slog/handler_test.go` | verified |  |
| go | `src/simd/archsimd/_gen/unify/yaml.go` | verified |  |
| go | `src/strings/example_test.go` | verified |  |
| go | `src/syscall/ztypes_linux_riscv64.go` | verified |  |
| go | `test/codegen/issue68845.go` | verified |  |
| go | `test/fixedbugs/bug028.go` | verified |  |
| go | `test/fixedbugs/bug147.go` | verified |  |
| go | `test/fixedbugs/bug205.go` | verified |  |
| go | `test/fixedbugs/bug251.go` | verified |  |
| go | `test/fixedbugs/issue18419.go` | verified |  |
| go | `test/fixedbugs/issue23837.go` | verified |  |
| go | `test/fixedbugs/issue73748a.go` | verified |  |
| go | `test/fixedbugs/issue75327.go` | verified |  |
| go | `test/typeparam/issue51522a.go` | verified |  |
| grafana | `e2e-playwright/panels-suite/table-utils.ts` | verified |  |
| grafana | `e2e-playwright/test-plugins/grafana-extensionstest-app/components/ActionButton/ActionButton.tsx` | verified |  |
| grafana | `pkg/expr/errors.go` | verified |  |
| grafana | `pkg/registry/apps/annotation/sql_adapter_test.go` | verified |  |
| grafana | `pkg/services/apiserver/standalone/runtime.go` | verified |  |
| grafana | `pkg/services/authn/authnimpl/service_test.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/silence_svc_test.go` | verified |  |
| grafana | `pkg/services/ngalert/state/historian/prometheus_test.go` | verified |  |
| grafana | `pkg/storage/unified/resource/search_field_manifest_test.go` | verified |  |
| grafana | `pkg/storage/unified/sql/sqltemplate/example_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/sync_folder_metadata_flag_disabled_test.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/sort_frame_test.go` | verified |  |
| grafana | `public/app/core/components/Footer/Footer.tsx` | verified |  |
| grafana | `public/app/core/components/Login/LoginForm.tsx` | verified |  |
| grafana | `public/app/core/components/SplashScreenModal/useShouldShowSplash.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/labels/LabelsEditorModal.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/triage/scene/dataFrameUtils.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/utils/receivers.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/inspect/HelpWizard/randomizer.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/Sidebar/Footer/SidebarFooter.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/variables/components/SwitchVariableForm.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/sharing/panel-share/SharePanelPreview.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/variables/VariableUsagesButton.tsx` | verified |  |
| grafana | `public/app/features/provisioning/Config/DashboardPreviewField.tsx` | verified |  |
| grafana | `public/app/features/scopes/dashboards/ScopesDashboards.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/azure_resource_graph/azure_resource_graph_datasource.ts` | verified |  |
| grafana | `public/app/plugins/panel/nodeGraph/types.ts` | verified |  |
