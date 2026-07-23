# Target OSS no-LLM dogfooding audit — continuation 490 (batch 491)

Run: 2026-07-23T06:18:14.417228+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/archive/tar/writer_test.go` | verified |  |
| go | `src/archive/zip/zip64_test.go` | verified |  |
| go | `src/cmd/cgo/internal/test/issue4029w.go` | verified |  |
| go | `src/cmd/cgo/internal/testlife/life_test.go` | verified |  |
| go | `src/cmd/compile/internal/ir/fmt.go` | verified |  |
| go | `src/crypto/internal/fips140/nistec/fiat/p521_invert.go` | verified |  |
| go | `src/database/sql/ctxutil.go` | verified |  |
| go | `src/encoding/json/v2/fold.go` | verified |  |
| go | `src/go/types/errors.go` | verified |  |
| go | `src/image/internal/imageutil/impl.go` | verified |  |
| go | `src/io/ioutil/ioutil_test.go` | verified |  |
| go | `src/mime/quotedprintable/example_test.go` | verified |  |
| go | `src/os/root_noopenat.go` | verified |  |
| go | `src/runtime/mgcsweep.go` | verified |  |
| go | `test/escape_runtime_atomic.go` | verified |  |
| go | `test/fixedbugs/issue8048.go` | verified |  |
| go | `test/nilcheck.go` | verified |  |
| go | `test/simassign.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v2beta1/variable_client_gen.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/conversion/golden_test.go` | verified |  |
| grafana | `apps/playlist/pkg/apis/playlist/v0alpha1/playlist_status_gen.go` | verified |  |
| grafana | `packages/grafana-schema/src/common/common.gen.ts` | verified |  |
| grafana | `packages/grafana-test-utils/src/matchers/toEmitValuesWith.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/Cells/DataLinksCell.tsx` | verified |  |
| grafana | `pkg/api/pluginproxy/token_provider_test.go` | verified |  |
| grafana | `pkg/components/imguploader/azureblobuploader.go` | verified |  |
| grafana | `pkg/infra/remotecache/database_storage_test.go` | verified |  |
| grafana | `pkg/login/social/connectors/generic_oauth_test.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/resources/resources_test.go` | verified |  |
| grafana | `pkg/registry/apis/secret/inline/grpc_client.go` | verified |  |
| grafana | `pkg/services/apiserver/standalone/factory.go` | verified |  |
| grafana | `pkg/services/ldap/service/ldap_test.go` | verified |  |
| grafana | `pkg/services/ngalert/metrics/alertmanager_test.go` | verified |  |
| grafana | `pkg/services/ngalert/metrics/util.go` | verified |  |
| grafana | `pkg/setting/setting_data_proxy.go` | verified |  |
| grafana | `pkg/storage/unified/apistore/stream.go` | verified |  |
| grafana | `pkg/storage/unified/search/embed/reconciler/fakes_test.go` | verified |  |
| grafana | `pkg/tests/api/alerting/api_admin_configuration_test.go` | verified |  |
| grafana | `pkg/tests/apis/dashboard/integration/library_panels_api_validation_test.go` | verified |  |
| grafana | `pkg/tsdb/jaeger/client_test.go` | verified |  |
| grafana | `public/app/features/alerting/unified/triage/scene/filters/SeverityFilter.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/links/DashboardLinkList.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/variables/VariablesDependenciesButton.tsx` | verified |  |
| grafana | `public/app/features/dashboard/components/ShareModal/ShareLink.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/TraceTimelineViewer/SpanTreeOffset.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/TraceTimelineViewer/VirtualizedTraceView.tsx` | verified |  |
| grafana | `public/app/features/plugins/sandbox/documentSandbox.ts` | verified |  |
| grafana | `public/app/features/provisioning/Wizard/fields.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/language/cloudwatch-sql/SQLGenerator.ts` | verified |  |
| grafana | `public/app/plugins/panel/table/cells/SparklineCellOptionsEditor.tsx` | verified |  |
