# Target OSS no-LLM dogfooding audit — continuation 393 (batch 394)

Run: 2026-07-23T00:18:37.099346+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/compress/zlib/example_test.go` | verified |  |
| go | `src/crypto/internal/cryptotest/allocations.go` | verified |  |
| go | `src/internal/syscall/unix/kernel_version_other.go` | verified |  |
| go | `src/internal/trace/internal/testgen/trace.go` | verified |  |
| go | `src/io/fs/sub.go` | verified |  |
| go | `src/math/atanh.go` | verified |  |
| go | `src/net/cgo_socknew.go` | verified |  |
| go | `src/net/http/internal/http2/ciphers_test.go` | verified |  |
| go | `src/runtime/softfloat64.go` | verified |  |
| go | `src/simd/archsimd/internal/simd_test/convert_helpers_wider_test.go` | verified |  |
| go | `test/fixedbugs/bug114.go` | verified |  |
| go | `test/fixedbugs/bug217.go` | verified |  |
| go | `test/fixedbugs/bug421.go` | verified |  |
| go | `test/fixedbugs/issue17270.go` | verified |  |
| go | `test/fixedbugs/issue44266.go` | verified |  |
| go | `test/fixedbugs/issue49143.dir/b.go` | verified |  |
| go | `test/nilptr.go` | verified |  |
| go | `test/rename1.go` | verified |  |
| go | `test/typeparam/mapimp.dir/a.go` | verified |  |
| grafana | `apps/alerting/rules/pkg/apis/alerting/v0alpha1/recordingrule_object_gen.go` | verified |  |
| grafana | `apps/example/plugin/src/generated/example/v1alpha1/example_object_gen.ts` | verified |  |
| grafana | `apps/plugins/pkg/apis/plugins/v0alpha1/plugin_status_gen.go` | verified |  |
| grafana | `apps/plugins/plugin/src/generated/plugin/v0alpha1/types.status.gen.ts` | verified |  |
| grafana | `apps/provisioning/pkg/repository/repository.go` | verified |  |
| grafana | `apps/shorturl/pkg/apis/shorturl/v1beta1/shorturl_client_gen.go` | verified |  |
| grafana | `packages/grafana-ui/src/components/Menu/MenuGroup.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/graveyard/uPlot/plugins/ZoomPlugin.tsx` | verified |  |
| grafana | `pkg/api/admin.go` | verified |  |
| grafana | `pkg/registry/apps/advisor/accesscontrol.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/legacy_storage/persist.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/clientmiddleware/grafana_request_id_header_middleware_test.go` | verified |  |
| grafana | `pkg/services/publicdashboards/internal/service/query_annotations_test.go` | verified |  |
| grafana | `pkg/services/serviceaccounts/retriever/retriever.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/silences/SilencedAlertsTableRow.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/mocks/mimirRulerApi.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/types/mute-timing-form.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/addToDashboard/AddToDashboardForm.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/addToDashboard/addPanelsOnLoadBehavior.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/new-toolbar/types.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/sharing/types.ts` | verified |  |
| grafana | `public/app/features/notebook/pages/NotebookScenePageStateManager.ts` | verified |  |
| grafana | `public/app/features/plugins/admin/components/PluginDetailsDeprecatedWarning.tsx` | verified |  |
| grafana | `public/app/features/plugins/sandbox/constants.ts` | verified |  |
| grafana | `public/app/features/provisioning/utils/connectionStatus.ts` | verified |  |
| grafana | `public/app/features/variables-management/components/VariablesTable.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/components/MetaInspector/MetaInspector.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/language/monarch/CompletionItemProvider.ts` | verified |  |
| grafana | `public/app/plugins/datasource/dashboard/runSharedRequest.ts` | verified |  |
| grafana | `public/app/plugins/panel/logstable/rows/LogsTableRowActionButtons.tsx` | verified |  |
| grafana | `public/app/plugins/panel/stat/module.tsx` | verified |  |
