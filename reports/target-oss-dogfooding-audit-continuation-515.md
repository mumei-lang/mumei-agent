# Target OSS no-LLM dogfooding audit — continuation 515 (batch 516)

Run: 2026-07-23T07:42:37.283302+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ssa/phiopt.go` | verified |  |
| go | `src/cmd/compile/internal/types2/context_test.go` | verified |  |
| go | `src/cmd/covdata/doc.go` | verified |  |
| go | `src/cmd/cover/cover.go` | verified |  |
| go | `src/cmd/go/internal/work/gccgo.go` | verified |  |
| go | `src/cmd/internal/osinfo/version_unix_test.go` | verified |  |
| go | `src/cmd/link/internal/ld/stackcheck.go` | verified |  |
| go | `src/go/importer/importer_test.go` | verified |  |
| go | `src/go/types/trie.go` | verified |  |
| go | `src/image/geom_test.go` | verified |  |
| go | `src/internal/syscall/unix/at_sysnum_newfstatat_linux.go` | verified |  |
| go | `src/math/j0.go` | verified |  |
| go | `src/mime/encodedword_test.go` | verified |  |
| go | `src/runtime/complex.go` | verified |  |
| go | `src/runtime/os_freebsd_noauxv.go` | verified |  |
| go | `src/simd/archsimd/_gen/simdgen/arm64/load.go` | verified |  |
| go | `src/syscall/ztypes_darwin_arm64.go` | verified |  |
| go | `src/testing/match_test.go` | verified |  |
| go | `test/abi/leaf2.go` | verified |  |
| go | `test/abi/struct_lower_1.go` | verified |  |
| go | `test/escape5.go` | verified |  |
| go | `test/fixedbugs/bug158.go` | verified |  |
| go | `test/fixedbugs/bug243.go` | verified |  |
| go | `test/fixedbugs/bug307.go` | verified |  |
| go | `test/fixedbugs/bug414.go` | verified |  |
| go | `test/fixedbugs/issue21882.go` | verified |  |
| go | `test/fixedbugs/issue22877.dir/p.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v2alpha1/constants.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v18_test.go` | verified |  |
| grafana | `apps/logsdrilldown/pkg/apis/logsdrilldown/v1beta1/logsdrilldowndefaultcolumns_codec_gen.go` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/dashboard/v2beta1/index.ts` | verified |  |
| grafana | `packages/grafana-ui/src/themes/getTheme.ts` | verified |  |
| grafana | `pkg/codegen/jenny_core_registry.go` | verified |  |
| grafana | `pkg/expr/ml/testing.go` | verified |  |
| grafana | `pkg/generated/applyconfiguration/service/v0alpha1/externalname.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/controller/mocks/ConnectionStatusPatcher.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/sync/full_sync_fn_mock.go` | verified |  |
| grafana | `pkg/services/apikey/apikeyimpl/store.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/angulardetectorsprovider/dynamic.go` | verified |  |
| grafana | `pkg/storage/unified/search/embed/backfill/backfiller.go` | verified |  |
| grafana | `public/app/core/components/OptionsUI/multiSelect.tsx` | verified |  |
| grafana | `public/app/features/annotations/isAnnotationApiAvailable.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/hooks/useAlertRulesForPanel.ts` | verified |  |
| grafana | `public/app/features/explore/Graph/exploreGraphStyleUtils.ts` | verified |  |
| grafana | `public/app/features/profile/FeatureTogglePage.tsx` | verified |  |
| grafana | `public/app/features/provisioning/Connection/ConnectionsTabContent.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/ArgQueryEditor/QueryField.tsx` | verified |  |
| grafana | `public/app/plugins/panel/barchart/utils.ts` | verified |  |
| grafana | `public/app/plugins/panel/logstable/fields/getFieldWidth.ts` | verified |  |
| grafana | `public/app/plugins/panel/timeseries/SpanNullsEditor.tsx` | verified |  |
