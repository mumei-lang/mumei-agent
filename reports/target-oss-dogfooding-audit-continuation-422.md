# Target OSS no-LLM dogfooding audit — continuation 422 (batch 423)

Run: 2026-07-23T01:36:28.207425+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ssa/prove_test.go` | verified |  |
| go | `src/cmd/go/internal/work/shell_test.go` | verified |  |
| go | `src/cmd/link/link_test.go` | verified |  |
| go | `src/debug/dwarf/buf.go` | verified |  |
| go | `src/go/token/position_test.go` | verified |  |
| go | `src/internal/goexperiment/flags.go` | verified |  |
| go | `src/internal/poll/sendfile_solaris.go` | verified |  |
| go | `src/math/big/float_test.go` | verified |  |
| go | `src/net/http/routing_tree_test.go` | verified |  |
| go | `src/net/rlimit_js.go` | verified |  |
| go | `src/runtime/defs_netbsd_amd64.go` | verified |  |
| go | `src/syscall/syscall_openbsd.go` | verified |  |
| go | `test/fixedbugs/bug235.go` | verified |  |
| go | `test/fixedbugs/bug396.dir/two.go` | verified |  |
| go | `test/fixedbugs/bug465.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue16949.go` | verified |  |
| go | `test/fixedbugs/issue50788.dir/a.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v1beta1/constants.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/conversion/v1_to_v2alpha1_mappings_test.go` | verified |  |
| grafana | `apps/plugins/pkg/apis/plugins/v0alpha1/plugin_schema_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/apis/auth/session_access_checker_test.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/clientset/versioned/fake/doc.go` | verified |  |
| grafana | `devenv/docker/ha-test-unified-alerting/webhook-listener.go` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/advisor/v0alpha1/endpoints.gen.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/ErrorBoundary/ErrorBoundary.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/types/completion.ts` | verified |  |
| grafana | `packages/grafana-ui/src/utils/skeleton.tsx` | verified |  |
| grafana | `pkg/api/pluginproxy/ds_auth_provider.go` | verified |  |
| grafana | `pkg/api/routing/route_register.go` | verified |  |
| grafana | `pkg/infra/log/databaseCounter_test.go` | verified |  |
| grafana | `pkg/infra/remotecache/redis_storage_test.go` | verified |  |
| grafana | `pkg/plugins/backendplugin/grpcplugin/client_v2.go` | verified |  |
| grafana | `pkg/plugins/repo/models.go` | verified |  |
| grafana | `pkg/services/cloudmigration/cloudmigrationimpl/fake/cloudmigration_fake.go` | verified |  |
| grafana | `pkg/services/ngalert/api/tooling/definitions/provisioning_mute_timings.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/pluginconfig/tracing.go` | verified |  |
| grafana | `pkg/services/provisioning/datasources/config_reader.go` | verified |  |
| grafana | `pkg/storage/unified/resource/kv/test/kv.go` | verified |  |
| grafana | `pkg/storage/unified/resource/noop.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/foldermetadata/update_folder_metadata_git_test.go` | verified |  |
| grafana | `pkg/tsdb/graphite/query_test.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/receivers/form/fields/styles.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/mocks/server/handlers/k8s/timeIntervals.k8s.ts` | verified |  |
| grafana | `public/app/features/dashboard/components/PanelEditor/getVisualizationOptions.tsx` | verified |  |
| grafana | `public/app/features/dashboard/components/SaveDashboard/SaveDashboardErrorProxy.tsx` | verified |  |
| grafana | `public/app/features/org/SelectOrgPage.tsx` | verified |  |
| grafana | `public/app/features/provisioning/Wizard/ConnectStep.tsx` | verified |  |
| grafana | `public/app/features/provisioning/components/Shared/SaveProvisionedResourceDrawer.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/loki/configuration/AlertingSettings.tsx` | verified |  |
| grafana | `public/app/plugins/panel/timeseries/plugins/annotations/AnnotationTooltip.tsx` | verified |  |
