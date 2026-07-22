# Target OSS no-LLM dogfooding audit — continuation 359 (batch 360)

Run: 2026-07-22T21:31:22.459384+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `misc/chrome/gophertool/background.js` | verified |  |
| go | `src/cmd/compile/internal/types/type_test.go` | verified |  |
| go | `src/container/heap/example_intheap_test.go` | verified |  |
| go | `src/go/printer/printer_test.go` | verified |  |
| go | `src/go/token/serialize_test.go` | verified |  |
| go | `src/net/dnsname_test.go` | verified |  |
| go | `src/os/exec_posix.go` | verified |  |
| go | `src/runtime/gc_test.go` | verified |  |
| go | `test/cmplxdivide1.go` | verified |  |
| go | `test/fixedbugs/issue15992.go` | verified |  |
| go | `test/fixedbugs/issue20602.go` | verified |  |
| go | `test/fixedbugs/issue33219.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue41780.go` | verified |  |
| go | `test/typeparam/dedup.dir/a.go` | verified |  |
| grafana | `apps/advisor/pkg/app/checks/plugincheck/unsigned_step.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v0alpha1/templategroup_object_gen.go` | verified |  |
| grafana | `apps/example/pkg/app/reconciler.go` | verified |  |
| grafana | `packages/grafana-runtime/src/services/dataSource/constants.ts` | verified |  |
| grafana | `packages/grafana-ui/src/themes/GlobalStyles/dashdiff.ts` | verified |  |
| grafana | `pkg/expr/service_test.go` | verified |  |
| grafana | `pkg/infra/features/openfeature.go` | verified |  |
| grafana | `pkg/infra/nats/subscriber_test.go` | verified |  |
| grafana | `pkg/services/folder/folderimpl/unifiedstore_test.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/pluginchecker/checker.go` | verified |  |
| grafana | `public/app/core/components/SVG/utils.ts` | verified |  |
| grafana | `public/app/core/components/Select/MetricSelect.tsx` | verified |  |
| grafana | `public/app/core/hooks/useHomeNav.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/AlertsFolderView.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/triage/instance-details/stateHistoryUtils.ts` | verified |  |
| grafana | `public/app/features/canvas/runtime/sceneElementManagement.ts` | verified |  |
| grafana | `public/app/features/correlations/components/Wizard/wizardContext.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/edit-pane/add-new/AddLink.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/edit-pane/useOutlineRename.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/layout-default/DashboardGridItem.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/CriticalPath/testCases/test4.ts` | verified |  |
| grafana | `public/app/features/library-panels/guard.ts` | verified |  |
| grafana | `public/app/features/plugins/admin/components/PluginDetailsHeaderSignature.tsx` | verified |  |
| grafana | `public/app/features/provisioning/components/Shared/ResourceEditFormSharedFields.tsx` | verified |  |
| grafana | `public/app/features/transformers/timeSeriesTable/TimeSeriesTableTransformEditor.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/loki/backendResultTransformer.ts` | verified |  |
| grafana | `public/app/plugins/panel/gauge/panelcfg.gen.ts` | verified |  |
| grafana | `public/app/plugins/panel/nodeGraph/editor/ArcOptionsEditor.tsx` | verified |  |
| grafana | `public/test/helpers/getTemplateSrvDependencies.ts` | verified |  |
| prysm | `beacon-chain/core/peerdas/reconstruction.go` | verified |  |
| prysm | `beacon-chain/db/pruner/log.go` | verified |  |
| prysm | `beacon-chain/state/state-native/state_fuzz_test.go` | verified |  |
| prysm | `beacon-chain/sync/backfill/batcher_test.go` | verified |  |
| prysm | `consensus-types/primitives/execution_address.go` | verified |  |
| prysm | `testing/spectest/shared/common/light_client/update_ranking.go` | verified |  |
| prysm | `tools/analyzers/interfacechecker/analyzer.go` | verified |  |
