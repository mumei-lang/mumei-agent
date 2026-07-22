# Target OSS no-LLM dogfooding audit — continuation 382 (batch 383)

Run: 2026-07-22T23:41:26.543471+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/go/internal/web/api.go` | verified |  |
| go | `src/encoding/json/bench_test.go` | verified |  |
| go | `src/fmt/example_test.go` | verified |  |
| go | `src/internal/syscall/windows/syscall_windows.go` | verified |  |
| go | `src/internal/testpty/pty_none.go` | verified |  |
| go | `src/internal/trace/tracev2/doc.go` | verified |  |
| go | `src/simd/archsimd/_gen/simdgen/arm64/instruction.go` | verified |  |
| go | `src/text/scanner/example_test.go` | verified |  |
| go | `test/codegen/alloc.go` | verified |  |
| go | `test/fixedbugs/bug216.go` | verified |  |
| go | `test/fixedbugs/bug407.dir/one.go` | verified |  |
| go | `test/fixedbugs/issue18092.go` | verified |  |
| go | `test/fixedbugs/issue18725.go` | verified |  |
| go | `test/fixedbugs/issue38745.go` | verified |  |
| go | `test/fixedbugs/issue5470.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue6902.go` | verified |  |
| go | `test/fixedbugs/issue7996.go` | verified |  |
| go | `test/typeparam/mdempsky/10.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/clientset/versioned/typed/provisioning/v0alpha1/doc.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/github/github_repository_mock.go` | verified |  |
| grafana | `devenv/docker/loadtest/modules/client.js` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/dashboard/v0alpha1/baseAPI.ts` | verified |  |
| grafana | `packages/grafana-data/src/types/query.ts` | verified |  |
| grafana | `packages/grafana-schema/src/raw/composable/news/panelcfg/x/types.gen.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/DataSourceSettings/types.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/VizTooltip/types.ts` | verified |  |
| grafana | `pkg/registry/apis/iam/authorizer/testutil.go` | verified |  |
| grafana | `pkg/registry/apps/alerting/notifications/integrationtypeschema/handler.go` | verified |  |
| grafana | `pkg/services/accesscontrol/pluginutils/utils.go` | verified |  |
| grafana | `pkg/services/authz/zanzana/server/server_mutate_test.go` | verified |  |
| grafana | `pkg/services/correlations/correlations.go` | verified |  |
| grafana | `pkg/services/extsvcauth/tests/extsvcregmock.go` | verified |  |
| grafana | `pkg/services/librarypanels/models.go` | verified |  |
| grafana | `pkg/services/publicdashboards/internal/api/query_test.go` | verified |  |
| grafana | `pkg/services/team/sortopts/sortopts_test.go` | verified |  |
| grafana | `public/app/api/clients/iam/v0alpha1/index.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/Templates.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/mute-timings/MuteTimingsTable.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/CloudAlertPreview.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/mutation-api/commands/updatePanel.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/Header/PluginActions.tsx` | verified |  |
| grafana | `public/app/features/dashboard/utils/screen.ts` | verified |  |
| grafana | `public/app/features/manage-dashboards/components/SnapshotListTable.tsx` | verified |  |
| grafana | `public/app/features/notebook/scene/buildNotebookEnvelope.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/components/shared/SelectionChipList.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/grafana-testdata-datasource/QueryEditor.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/mysql/sqlCompletionProvider.ts` | verified |  |
| grafana | `public/app/plugins/panel/bargauge/panelcfg.gen.ts` | verified |  |
| grafana | `public/app/plugins/panel/timeseries/module.tsx` | verified |  |
| grafana | `public/app/plugins/panel/timeseries/plugins/annotations/AnnotationTooltipCluster.tsx` | verified |  |
