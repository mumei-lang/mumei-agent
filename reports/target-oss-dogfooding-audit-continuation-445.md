# Target OSS no-LLM dogfooding audit — continuation 445 (batch 446)

Run: 2026-07-23T02:50:58.415368+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/internal/telemetry/counter/counter.go` | verified |  |
| go | `src/compress/gzip/gzip_test.go` | verified |  |
| go | `src/crypto/internal/boring/doc.go` | verified |  |
| go | `src/crypto/internal/fips140/edwards25519/field/fe_generic.go` | verified |  |
| go | `src/crypto/internal/fips140deps/godebug/godebug.go` | verified |  |
| go | `src/encoding/pem/pem_test.go` | verified |  |
| go | `src/internal/syscall/unix/getrandom_freebsd.go` | verified |  |
| go | `src/math/big/internal/asmgen/add.go` | verified |  |
| go | `src/mime/quotedprintable/reader_test.go` | verified |  |
| go | `src/net/http/client.go` | verified |  |
| go | `src/regexp/syntax/prog_test.go` | verified |  |
| go | `src/runtime/secret/secret.go` | verified |  |
| go | `src/sort/example_interface_test.go` | verified |  |
| go | `src/time/mono_test.go` | verified |  |
| go | `test/codegen/simd.go` | verified |  |
| go | `test/fixedbugs/bug335.go` | verified |  |
| go | `test/fixedbugs/bug343.go` | verified |  |
| go | `test/fixedbugs/issue33438.go` | verified |  |
| go | `test/fixedbugs/issue49619.go` | verified |  |
| go | `test/fixedbugs/issue51291.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue63955.go` | verified |  |
| go | `test/typeparam/issue49659b.go` | verified |  |
| go | `test/varinit.go` | verified |  |
| grafana | `apps/advisor/pkg/app/checks/authchecks/check_test.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v2alpha1/dashboard_client_gen.go` | verified |  |
| grafana | `e2e-playwright/test-plugins/grafana-extensionstest-app/pages/index.tsx` | verified |  |
| grafana | `packages/grafana-data/src/valueFormats/categories.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/BigValue/PercentChange.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/VizLegend/VizLegendList.tsx` | verified |  |
| grafana | `pkg/middleware/auth.go` | verified |  |
| grafana | `pkg/plugins/repo/ifaces.go` | verified |  |
| grafana | `pkg/registry/apis/secret/clock/clock.go` | verified |  |
| grafana | `pkg/services/authn/clients/proxy.go` | verified |  |
| grafana | `pkg/services/ngalert/models/permissions.go` | verified |  |
| grafana | `pkg/services/ngalert/writer/noop.go` | verified |  |
| grafana | `pkg/services/search/model/model.go` | verified |  |
| grafana | `pkg/storage/secret/metadata/keeper_store.go` | verified |  |
| grafana | `pkg/storage/unified/sql/sqltemplate/sqltemplate_test.go` | verified |  |
| grafana | `pkg/tests/utils.go` | verified |  |
| grafana | `pkg/web/webtest/webtest.go` | verified |  |
| grafana | `public/app/features/alerting/unified/utils/accessControlHooks.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/edit-pane/DashboardExportButton.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/version-history/DiffViewer.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/sharing/ShareButton/share-externally/utils.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/v2schema/dashboardV2Schema.ts` | verified |  |
| grafana | `public/app/features/dimensions/editors/ValueMappingsEditor/ValueMappingsEditorModal.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/TraceTimelineViewer/TimelineRow.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/ConfigEditor/BasicLogsToggle.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/language/dynamic-labels/definition.ts` | verified |  |
| grafana | `public/app/plugins/panel/geomap/layers/data/geojsonDynamic.ts` | verified |  |
