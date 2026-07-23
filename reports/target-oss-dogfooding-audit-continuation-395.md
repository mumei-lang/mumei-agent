# Target OSS no-LLM dogfooding audit — continuation 395 (batch 396)

Run: 2026-07-23T00:27:06.357632+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ssa/location.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/nilcheck.go` | verified |  |
| go | `src/cmd/go/internal/toolchain/umask_none.go` | verified |  |
| go | `src/cmd/internal/objabi/symkind.go` | verified |  |
| go | `src/encoding/ascii85/ascii85.go` | verified |  |
| go | `src/html/template/attr_string.go` | verified |  |
| go | `src/internal/cpu/datacache_x86_test.go` | verified |  |
| go | `src/internal/goarch/zgoarch_386.go` | verified |  |
| go | `src/math/floor_asm.go` | verified |  |
| go | `src/net/pipe_test.go` | verified |  |
| go | `src/runtime/mem_nonsbrk.go` | verified |  |
| go | `src/runtime/softfloat64_test.go` | verified |  |
| go | `test/fixedbugs/bug406.go` | verified |  |
| go | `test/fixedbugs/issue23298.go` | verified |  |
| go | `test/fixedbugs/issue47087.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue52701.go` | verified |  |
| go | `test/fixedbugs/issue60991.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v0alpha1/inhibitionrule_spec_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/tester_test.go` | verified |  |
| grafana | `packages/grafana-alerting/tests/story-utils.tsx` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/legacy/endpoints.gen.ts` | verified |  |
| grafana | `packages/grafana-sql/src/components/query-editor-raw/RawEditor.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/TableNG/components/SummaryCell.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/uPlot/geometries/XYCanvas.tsx` | verified |  |
| grafana | `pkg/apis/iam/v0alpha1/types_user.go` | verified |  |
| grafana | `pkg/ifaces/s3ifaces/s3ifaces.go` | verified |  |
| grafana | `pkg/infra/log/log_test.go` | verified |  |
| grafana | `pkg/infra/metrics/metrics.go` | verified |  |
| grafana | `pkg/middleware/auth_test.go` | verified |  |
| grafana | `pkg/plugins/backendplugin/provider/provider.go` | verified |  |
| grafana | `pkg/registry/backgroundsvcs/background_services.go` | verified |  |
| grafana | `pkg/services/frontend/webassets/webassets.go` | verified |  |
| grafana | `pkg/services/live/pipeline/data_output_builtin.go` | verified |  |
| grafana | `pkg/services/ngalert/provisioning/accesscontrol_test.go` | verified |  |
| grafana | `pkg/services/ngalert/remote/client/mimir.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/pluginaccesscontrol/accesscontrol.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/accesscontrol/admin_only.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/accesscontrol/service_account_action_set_migration.go` | verified |  |
| grafana | `pkg/setting/setting_remote_cache.go` | verified |  |
| grafana | `pkg/tests/api/plugins/api_plugins_test.go` | verified |  |
| grafana | `pkg/tests/apis/zanzana_reconcile.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/folder-actions/DeleteModal.tsx` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| grafana | `public/app/features/dashboard-scene/mutation-api/commands/addAnnotation.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/AddLibraryPanelDrawer.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/variables/editors/QueryVariableEditor/PaneItem.tsx` | verified |  |
| grafana | `public/app/features/explore/spec/helper/setup.tsx` | verified |  |
| grafana | `public/app/features/plugins/admin/components/PluginActions.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/graphite/state/providers.ts` | verified |  |
| grafana | `public/app/plugins/datasource/jaeger/webpack.config.ts` | verified |  |
| grafana | `public/app/plugins/panel/xychart/migrations.ts` | verified |  |
