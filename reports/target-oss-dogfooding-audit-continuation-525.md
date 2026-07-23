# Target OSS no-LLM dogfooding audit — continuation 525 (batch 526)

Run: 2026-07-23T08:18:17.147298+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/test/issue23555a/a.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/sccp_test.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/softfloat.go` | verified |  |
| go | `src/cmd/link/internal/loadelf/ldelf.go` | verified |  |
| go | `src/crypto/cipher/ctr_aes_test.go` | verified |  |
| go | `src/crypto/internal/fips140/mlkem/mlkem768.go` | verified |  |
| go | `src/go/token/token.go` | verified |  |
| go | `src/go/types/mono_test.go` | verified |  |
| go | `src/index/suffixarray/sais.go` | verified |  |
| go | `src/internal/diff/diff.go` | verified |  |
| go | `src/math/big/natconv_test.go` | verified |  |
| go | `src/math/sqrt.go` | verified |  |
| go | `src/os/stat_openbsd.go` | verified |  |
| go | `src/runtime/linkname_shim.go` | verified |  |
| go | `src/runtime/malloc_bench_generated_test.go` | verified |  |
| go | `src/time/zoneinfo_test.go` | verified |  |
| go | `test/fixedbugs/bug082.go` | verified |  |
| go | `test/fixedbugs/issue14164.dir/main.go` | verified |  |
| go | `test/fixedbugs/issue28268.go` | verified |  |
| go | `test/fixedbugs/issue46653.dir/bad/bad.go` | verified |  |
| go | `test/fixedbugs/issue52841.go` | verified |  |
| go | `test/fixedbugs/issue68809.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v17_test.go` | verified |  |
| grafana | `apps/dashvalidator/pkg/generated/dashboardcompatibilityscore/v1alpha1/dashboardcompatibilityscore_schema_gen.go` | verified |  |
| grafana | `apps/playlist/pkg/apis/manifestdata/playlist_manifest.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/git/branch.go` | verified |  |
| grafana | `apps/provisioning/pkg/util/interface.go` | verified |  |
| grafana | `e2e-playwright/test-plugins/grafana-extensionstest-app/constants.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Select/mockOptions.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/utils/storybook/withStoryContainer.tsx` | verified |  |
| grafana | `pkg/plugins/manager/signature/manifest.go` | verified |  |
| grafana | `pkg/registry/apis/preferences/openapi.go` | verified |  |
| grafana | `pkg/registry/apps/alerting/notifications/timeinterval/legacy_storage.go` | verified |  |
| grafana | `pkg/registry/apps/annotation/custom_route_response_test.go` | verified |  |
| grafana | `pkg/services/folder/cleaner/contents_cleaner.go` | verified |  |
| grafana | `pkg/services/librarypanels/librarypanels.go` | verified |  |
| grafana | `pkg/services/ngalert/api/compat_contact_points.go` | verified |  |
| grafana | `pkg/services/ngalert/metrics/scheduler.go` | verified |  |
| grafana | `pkg/services/provisioning/dashboards/config_reader_test.go` | verified |  |
| grafana | `pkg/storage/unified/sql/db/service_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/quota/helpers_test.go` | verified |  |
| grafana | `public/app/features/alerting/unified/triage/rows/GenericRow.tsx` | verified |  |
| grafana | `public/app/features/annotations/components/AnnotationResultMapper.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/Actions.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/variables/components/VariableTextField.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/TraceTimelineViewer/types.tsx` | verified |  |
| grafana | `public/app/features/live/dashboard/dashboardWatcher.ts` | verified |  |
| grafana | `public/app/features/plugins/sandbox/pluginDependencies.ts` | verified |  |
| grafana | `public/app/features/provisioning/components/Dashboards/DashboardPreviewBanner.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/LogsQueryEditor/setQueryValue.ts` | verified |  |
