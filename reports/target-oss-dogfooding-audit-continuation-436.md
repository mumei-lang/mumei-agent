# Target OSS no-LLM dogfooding audit — continuation 436 (batch 437)

Run: 2026-07-23T02:14:38.655309+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/asm/internal/asm/operand_test.go` | verified |  |
| go | `src/cmd/compile/internal/inline/inlheur/function_properties.go` | verified |  |
| go | `src/cmd/go/internal/toolchain/toolchain_test.go` | verified |  |
| go | `src/compress/flate/inflate_test.go` | verified |  |
| go | `src/crypto/ecdh/ecdh.go` | verified |  |
| go | `src/crypto/internal/sysrand/internal/seccomp/seccomp_unsupported.go` | verified |  |
| go | `src/crypto/tls/defaults_boring.go` | verified |  |
| go | `src/math/example_test.go` | verified |  |
| go | `src/math/log_stub.go` | verified |  |
| go | `test/complit1.go` | verified |  |
| go | `test/fixedbugs/bug509.go` | verified |  |
| go | `test/fixedbugs/issue23823.go` | verified |  |
| go | `test/fixedbugs/issue42944.go` | verified |  |
| go | `test/fixedbugs/issue48459.go` | verified |  |
| go | `test/fixedbugs/issue64606.go` | verified |  |
| go | `test/fixedbugs/issue7050.go` | verified |  |
| go | `test/typeparam/map.go` | verified |  |
| go | `test/typeparam/mdempsky/12.go` | verified |  |
| go | `test/typeparam/mdempsky/8.dir/b.go` | verified |  |
| grafana | `apps/alerting/rules/pkg/apis/alerting/v0alpha1/rulesequence_status_gen.go` | verified |  |
| grafana | `packages/grafana-alerting/src/grafana/notificationPolicies/types.ts` | verified |  |
| grafana | `packages/grafana-data/src/utils/datasource.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/MatchersUI/types.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/uPlot/PlotLegend.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/themes/GlobalStyles/slate.ts` | verified |  |
| grafana | `pkg/api/datasources.go` | verified |  |
| grafana | `pkg/api/playlist.go` | verified |  |
| grafana | `pkg/cmd/grafana/main.go` | verified |  |
| grafana | `pkg/generated/informers/externalversions/service/v0alpha1/interface.go` | verified |  |
| grafana | `pkg/services/apiserver/appinstaller/noop_opts_getter.go` | verified |  |
| grafana | `pkg/services/serviceaccounts/manager/stats.go` | verified |  |
| grafana | `pkg/storage/unified/search/bleve_snapshot_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/foldermetadata/jobs_auth_test.go` | verified |  |
| grafana | `pkg/tsdb/azuremonitor/loganalytics/utils.go` | verified |  |
| grafana | `pkg/tsdb/graphite/resource_handler_test.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/query-and-alert-condition/descriptions.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/triage/rows/GroupRow.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/components/DashboardTemplateUseBanner.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/edit-pane/DashboardCodePane.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/edit-pane/add-new/AddNewSection.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelDataPane/PanelDataPane.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/keyboardShortcuts.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/layouts-shared/useClipboardState.ts` | verified |  |
| grafana | `public/app/features/plugins/datasource_srv.ts` | verified |  |
| grafana | `public/app/features/provisioning/Repository/PullRequestButtons.tsx` | verified |  |
| grafana | `public/app/features/variables-management/VariableEditorView.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/ConfigEditor/AzureCredentialsForm.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/jaeger/module.ts` | verified |  |
| grafana | `public/app/plugins/datasource/loki/components/LokiCheatSheet.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/loki/mocks/datasource.ts` | verified |  |
