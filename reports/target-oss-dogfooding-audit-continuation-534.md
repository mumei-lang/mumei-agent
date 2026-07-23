# Target OSS no-LLM dogfooding audit — continuation 534 (batch 535)

Run: 2026-07-23T09:11:11.404335+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/archive/tar/example_test.go` | verified |  |
| go | `src/cmd/compile/internal/ir/func.go` | verified |  |
| go | `src/cmd/go/internal/load/pkg_test.go` | verified |  |
| go | `src/internal/goexperiment/exp_newinliner_off.go` | verified |  |
| go | `src/internal/goos/zgoos_hurd.go` | verified |  |
| go | `src/math/big/accuracy_string.go` | verified |  |
| go | `src/net/http/cgi/cgi_main.go` | verified |  |
| go | `src/net/sock_plan9.go` | verified |  |
| go | `src/os/exec_unix.go` | verified |  |
| go | `src/os/signal/signal_unix.go` | verified |  |
| go | `src/runtime/export_pipe_test.go` | verified |  |
| go | `src/runtime/security_unix.go` | verified |  |
| go | `src/simd/archsimd/_gen/sgutil/insert_ordered_map_test.go` | verified |  |
| go | `src/syscall/zerrors_freebsd_arm.go` | verified |  |
| go | `test/fixedbugs/bug227.go` | verified |  |
| go | `test/fixedbugs/issue25958.go` | verified |  |
| go | `test/fixedbugs/issue30862.go` | verified |  |
| go | `test/fixedbugs/issue32288.go` | verified |  |
| go | `test/fixedbugs/issue35291.go` | verified |  |
| go | `test/fixedbugs/issue43167.go` | verified |  |
| go | `test/fixedbugs/issue66873.go` | verified |  |
| go | `test/interface/private.dir/private1.go` | verified |  |
| go | `test/interface/recursive.go` | verified |  |
| go | `test/typeparam/absdiff3.go` | verified |  |
| go | `test/typeparam/issue48462.dir/main.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v0alpha1/inhibitionrule_object_gen.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v2/zz_generated.defaults.go` | verified |  |
| grafana | `apps/logsdrilldown/pkg/app/app.go` | verified |  |
| grafana | `apps/scope/pkg/apis/scope/v0alpha1/types.go` | verified |  |
| grafana | `packages/grafana-data/src/events/types.ts` | verified |  |
| grafana | `packages/grafana-test-utils/src/handlers/apis/dashboard.grafana.app/v2beta1/handlers.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/CustomScrollbar/ScrollIndicators.tsx` | verified |  |
| grafana | `pkg/registry/backgroundsvcs/adapter/manager.go` | verified |  |
| grafana | `pkg/services/kmsproviders/defaultprovider/grafana_provider.go` | verified |  |
| grafana | `pkg/services/ngalert/api/generated_base_api_testing.go` | verified |  |
| grafana | `pkg/services/ngalert/models/receivers_diff_test.go` | verified |  |
| grafana | `pkg/services/ngalert/state/state.go` | verified |  |
| grafana | `pkg/services/oauthtoken/oauthtokentest/mock.go` | verified |  |
| grafana | `pkg/storage/unified/sql/db/dbimpl/util_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/resourcekinds/export_test.go` | verified |  |
| grafana | `pkg/tsdb/prometheus/prometheus_test.go` | verified |  |
| grafana | `public/app/features/alerting/unified/api/alertRuleModel.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/receivers/editor/templateDataSuggestions.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/Body/QueryEditorDetailsSidebar.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/layout-auto-grid/AutoGridItem.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/version-history/VersionHistoryButtons.tsx` | verified |  |
| grafana | `public/app/features/dimensions/resource.ts` | verified |  |
| grafana | `public/app/features/provisioning/utils/repositoryTypes.ts` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/LogsQueryBuilder/AzureMonitorKustoQueryBuilder.ts` | verified |  |
| grafana | `public/app/plugins/datasource/loki/types.ts` | verified |  |
