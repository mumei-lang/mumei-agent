# Target OSS no-LLM dogfooding audit — continuation 420 (batch 421)

Run: 2026-07-23T01:29:38.699404+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/test/issue26430/a.go` | verified |  |
| go | `src/cmd/go/internal/modfetch/codehost/codehost.go` | verified |  |
| go | `src/crypto/sha1/_asm/sha1block_amd64_asm.go` | verified |  |
| go | `src/crypto/sha1/sha1block_decl.go` | verified |  |
| go | `src/debug/elf/symbols_test.go` | verified |  |
| go | `src/internal/runtime/maps/runtime_fast32.go` | verified |  |
| go | `src/os/pipe_test.go` | verified |  |
| go | `src/runtime/debugcall.go` | verified |  |
| go | `src/simd/example_test.go` | verified |  |
| go | `test/fixedbugs/bug146.go` | verified |  |
| go | `test/fixedbugs/bug184.go` | verified |  |
| go | `test/fixedbugs/issue12413.go` | verified |  |
| go | `test/fixedbugs/issue15747.go` | verified |  |
| go | `test/fixedbugs/issue16317.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue21808.go` | verified |  |
| go | `test/fixedbugs/issue65957.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue6703v.go` | verified |  |
| go | `test/fixedbugs/issue77613.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v1beta1/timeinterval_ext.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/applyconfiguration/provisioning/v0alpha1/repository.go` | verified |  |
| grafana | `apps/provisioning/pkg/safepath/dir.go` | verified |  |
| grafana | `packages/grafana-runtime/src/services/pluginSettings/invalidatePluginSettingsCache.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/VizTooltip/VizTooltipHeader.tsx` | verified |  |
| grafana | `pkg/apiserver/auditing/middleware_test.go` | verified |  |
| grafana | `pkg/cmd/grafana-cli/commands/install_command.go` | verified |  |
| grafana | `pkg/components/loki/lokihttp/types.go` | verified |  |
| grafana | `pkg/expr/mathexp/parse/parse.go` | verified |  |
| grafana | `pkg/modules/modules.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/controller/webhook_test.go` | verified |  |
| grafana | `pkg/services/apiserver/builder/custom_route_metrics.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/config_test.go` | verified |  |
| grafana | `pkg/services/ngalert/schedule/retry.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/clientmiddleware/logger_middleware.go` | verified |  |
| grafana | `pkg/storage/unified/sql/kv.go` | verified |  |
| grafana | `pkg/tests/apis/iam/team/team_search_integration_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/nats/jobs_test.go` | verified |  |
| grafana | `pkg/tsdb/graphite/utils_test.go` | verified |  |
| grafana | `pkg/web/context_test.go` | verified |  |
| grafana | `public/app/core/components/Layers/LayerDragDropList.tsx` | verified |  |
| grafana | `public/app/core/components/NestedFolderPicker/NestedFolderPicker.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/folder-actions/PauseUnpauseActionMenuItem.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rules/deleted-rules/ConfirmRestoreDeletedRuleModal.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/hooks/usePluginBridge.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/mocks/server/handlers/historian.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/serialization/layoutSerializers/AutoGridLayoutSerializer.ts` | verified |  |
| grafana | `public/app/features/dashboard/dashgrid/DashboardLibrary/enterprise-components/DashboardTemplatesTabExtension.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/e2e/selectors.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/components/QueryEditor/QueryEditor.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/influxdb/components/editor/config-v2/LeftSideBar.tsx` | verified |  |
| grafana | `public/app/plugins/panel/logstable/options/types.ts` | verified |  |
