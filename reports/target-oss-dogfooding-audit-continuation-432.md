# Target OSS no-LLM dogfooding audit — continuation 432 (batch 433)

Run: 2026-07-23T02:04:21.887358+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/archive/tar/strconv.go` | verified |  |
| go | `src/cmd/compile/internal/bloop/bloop.go` | verified |  |
| go | `src/cmd/go/stop_unix_test.go` | verified |  |
| go | `src/cmd/internal/robustio/robustio_windows.go` | verified |  |
| go | `src/cmd/link/internal/sym/symkind_string.go` | verified |  |
| go | `src/cmp/cmp_test.go` | verified |  |
| go | `src/crypto/internal/fips140/mlkem/generate1024.go` | verified |  |
| go | `src/internal/runtime/maps/map_test.go` | verified |  |
| go | `src/net/interface_aix.go` | verified |  |
| go | `src/runtime/coro.go` | verified |  |
| go | `src/simd/archsimd/internal/simd_test/convert_arm64_test.go` | verified |  |
| go | `src/syscall/zerrors_linux_ppc64le.go` | verified |  |
| go | `src/syscall/ztypes_linux_ppc64.go` | verified |  |
| go | `test/chan/select2.go` | verified |  |
| go | `test/fixedbugs/bug022.go` | verified |  |
| go | `test/fixedbugs/issue30977.go` | verified |  |
| go | `test/fixedbugs/issue56141.go` | verified |  |
| go | `test/fixedbugs/issue59404.go` | verified |  |
| go | `test/fixedbugs/issue61187.go` | verified |  |
| go | `test/fixedbugs/issue8280.go` | verified |  |
| go | `test/typeparam/absdiff.go` | verified |  |
| go | `test/typeparam/issue48454.go` | verified |  |
| grafana | `apps/advisor/pkg/apis/advisor/v0alpha1/check_object_gen.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v31.go` | verified |  |
| grafana | `apps/plugins/pkg/app/meta_storage_test.go` | verified |  |
| grafana | `apps/provisioning/pkg/loki/client.go` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/plugins/v0alpha1/index.ts` | verified |  |
| grafana | `packages/grafana-runtime/rollup.config.ts` | verified |  |
| grafana | `packages/grafana-runtime/src/utils/returnToPrevious.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/ContextMenu/ContextMenu.tsx` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| grafana | `packages/grafana-ui/src/components/Table/Table.tsx` | verified |  |
| grafana | `pkg/infra/log/file.go` | verified |  |
| grafana | `pkg/services/apiserver/auth/authorizer/role_test.go` | verified |  |
| grafana | `pkg/services/ngalert/api/hcl/hcl_test.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/errors.go` | verified |  |
| grafana | `pkg/services/ngalert/store/proto_instance_database.go` | verified |  |
| grafana | `pkg/services/ssosettings/ssosettingsimpl/mtsettings_client.go` | verified |  |
| grafana | `pkg/services/ssosettings/ssosettingstests/reloadable_mock.go` | verified |  |
| grafana | `pkg/tsdb/influxdb/fsql/fsql.go` | verified |  |
| grafana | `pkg/tsdb/loki/schema_test.go` | verified |  |
| grafana | `public/app/core/components/AppChrome/News/NewsWrapper.tsx` | verified |  |
| grafana | `public/app/features/canvas/runtime/ables.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/saving/enterprise-components/SaveDashboardTemplateFormExtension.tsx` | verified |  |
| grafana | `public/app/features/explore/QueryRows.tsx` | verified |  |
| grafana | `public/app/features/plugins/components/PluginErrorBoundary.tsx` | verified |  |
| grafana | `public/app/features/templating/template_srv.ts` | verified |  |
| grafana | `public/app/features/transformers/smoothing/asap.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/mocks/cloudwatch-ppl-test-data/multilineQueries.ts` | verified |  |
| grafana | `public/app/plugins/datasource/loki/querybuilder/components/LokiQueryCodeEditor.tsx` | verified |  |
| grafana | `public/app/routes/RoutesWrapper.tsx` | verified |  |
