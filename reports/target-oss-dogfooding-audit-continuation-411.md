# Target OSS no-LLM dogfooding audit — continuation 411 (batch 412)

Run: 2026-07-23T01:13:14.535426+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cover/cfg_test.go` | verified |  |
| go | `src/encoding/gob/encoder_test.go` | verified |  |
| go | `src/encoding/gob/gobencdec_test.go` | verified |  |
| go | `src/internal/trace/raw/doc.go` | verified |  |
| go | `src/io/fs/glob_test.go` | verified |  |
| go | `src/log/syslog/example_test.go` | verified |  |
| go | `src/net/lookup_windows.go` | verified |  |
| go | `src/os/pipe_unix.go` | verified |  |
| go | `src/os/signal/example_unix_test.go` | verified |  |
| go | `src/runtime/mspanset.go` | verified |  |
| go | `src/runtime/preempt_amd64.go` | verified |  |
| go | `test/fixedbugs/bug121.go` | verified |  |
| go | `test/fixedbugs/bug442.go` | verified |  |
| go | `test/fixedbugs/issue34329.go` | verified |  |
| go | `test/fixedbugs/issue7794.go` | verified |  |
| go | `test/slicecap.go` | verified |  |
| go | `test/typeparam/issue50147.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/frontend_defaults.go` | verified |  |
| grafana | `apps/example/plugin/src/generated/examplekind/v1alpha1/examplekind_object_gen.ts` | verified |  |
| grafana | `apps/provisioning/pkg/generated/listers/provisioning/v0alpha1/connection.go` | verified |  |
| grafana | `packages/grafana-sql/src/defaults.ts` | verified |  |
| grafana | `pkg/api/pluginproxy/ds_auth_provider_test.go` | verified |  |
| grafana | `pkg/api/pluginproxy/loader_test.go` | verified |  |
| grafana | `pkg/middleware/request_test.go` | verified |  |
| grafana | `pkg/plugins/manager/registry/in_memory_test.go` | verified |  |
| grafana | `pkg/plugins/storage/fs.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/usage/namespace_test.go` | verified |  |
| grafana | `pkg/server/module_runner.go` | verified |  |
| grafana | `pkg/services/accesscontrol/acimpl/service_bench_test.go` | verified |  |
| grafana | `pkg/services/accesscontrol/resourcepermissions/fake.go` | verified |  |
| grafana | `pkg/services/live/pipeline/data_output_redirect.go` | verified |  |
| grafana | `pkg/services/ngalert/provisioning/alert_rules_test.go` | verified |  |
| grafana | `pkg/services/ngalert/schedule/loaded_metrics_reader.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/clientmiddleware/user_header_middleware.go` | verified |  |
| grafana | `pkg/tests/apis/alerting/rules/compat/convertprometheus_retrieval_test.go` | verified |  |
| grafana | `pkg/tsdb/azuremonitor/macros/macros.go` | verified |  |
| grafana | `pkg/tsdb/grafana-testdata-datasource/standalone/main.go` | verified |  |
| grafana | `pkg/tsdb/loki/healthcheck_test.go` | verified |  |
| grafana | `public/app/core/reducers/navBarTree.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/api/featureDiscoveryApi.ts` | verified |  |
| grafana | `public/app/features/browse-dashboards/BrowseFolderAlertingPage.tsx` | verified |  |
| grafana | `public/app/features/browse-dashboards/api/isProvisioned.ts` | verified |  |
| grafana | `public/app/features/browse-dashboards/components/BrowseActions/AffectedFolderContents.tsx` | verified |  |
| grafana | `public/app/features/connections/tabs/ConnectData/CardGrid/CardGrid.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/types/EditableDashboardElement.ts` | verified |  |
| grafana | `public/app/features/geo/format/utils.ts` | verified |  |
| grafana | `public/app/features/inspector/InspectErrorTab.tsx` | verified |  |
| grafana | `public/app/features/search/components/DescriptionTooltip.tsx` | verified |  |
| grafana | `public/app/features/transformers/editors/GroupToNestedTableTransformerEditor/index.tsx` | verified |  |
| grafana | `public/app/features/variables/editor/types.ts` | verified |  |
