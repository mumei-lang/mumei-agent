# Target OSS no-LLM dogfooding audit — continuation 362 (batch 363)

Run: 2026-07-22T21:52:20.184087+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/compare/compare_test.go` | verified |  |
| go | `src/crypto/internal/fips140test/edwards25519_test.go` | verified |  |
| go | `src/encoding/json/example_marshaling_test.go` | verified |  |
| go | `src/hash/crc32/crc32_generic.go` | verified |  |
| go | `src/image/jpeg/dct_test.go` | verified |  |
| go | `src/internal/cpu/cpu_mips64x.go` | verified |  |
| go | `src/runtime/fastlog2_test.go` | verified |  |
| go | `src/runtime/hash_test.go` | verified |  |
| go | `src/simd/archsimd/_gen/simdgen/arm64/operands.go` | verified |  |
| go | `src/text/template/exec.go` | verified |  |
| go | `test/fixedbugs/bug005.go` | verified |  |
| go | `test/fixedbugs/issue20335.go` | verified |  |
| go | `test/fixedbugs/issue23179.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue42587.go` | verified |  |
| go | `test/fixedbugs/issue59572.go` | verified |  |
| go | `test/fixedbugs/issue73491.go` | verified |  |
| go | `test/for.go` | verified |  |
| go | `test/intrinsic.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v0alpha1/validation.go` | verified |  |
| grafana | `apps/plugins/pkg/app/meta_storage.go` | verified |  |
| grafana | `e2e-playwright/test-plugins/frontend-sandbox-datasource-test/module.js` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| grafana | `packages/grafana-runtime/src/utils/openfeature.ts` | verified |  |
| grafana | `packages/grafana-schema/src/raw/composable/dashboardlist/panelcfg/x/types.gen.ts` | verified |  |
| grafana | `pkg/plugins/pluginassets/localprovider_test.go` | verified |  |
| grafana | `pkg/registry/apis/folders/sub_access_test.go` | verified |  |
| grafana | `pkg/registry/apis/iam/user/validate.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/controller/repository_quota_test.go` | verified |  |
| grafana | `pkg/services/accesscontrol/acimpl/basic_role_db_seed.go` | verified |  |
| grafana | `pkg/services/authz/zanzana/server/server.go` | verified |  |
| grafana | `pkg/services/ngalert/state/persist.go` | verified |  |
| grafana | `pkg/services/provisioning/provisioning_mock.go` | verified |  |
| grafana | `pkg/storage/secret/encryption/data_key_store.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/mocks/logs.go` | verified |  |
| grafana | `pkg/util/contextutil.go` | verified |  |
| grafana | `public/app/core/components/OptionsUI/select.tsx` | verified |  |
| grafana | `public/app/core/utils/arrayMove.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/triage/Triage.tsx` | verified |  |
| grafana | `public/app/features/canvas/elements/rectangle.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/VariableControls.tsx` | verified |  |
| grafana | `public/app/features/dashboard/dashgrid/DashboardLibrary/utils/autoMapDatasources.ts` | verified |  |
| grafana | `public/app/features/explore/Graph/ExploreGraph.tsx` | verified |  |
| grafana | `public/app/features/home/Recommendations/Recommendations.tsx` | verified |  |
| grafana | `public/app/features/logs/components/panel/analytics.ts` | verified |  |
| grafana | `public/app/features/provisioning/Wizard/components/WizardStepContent.tsx` | verified |  |
| grafana | `public/app/features/provisioning/hooks/useCreateOrUpdateConnection.ts` | verified |  |
| grafana | `public/app/features/transformers/editors/LabelsToFieldsTransformerEditor.tsx` | verified |  |
| grafana | `public/app/features/variables/getAllVariableValuesForUrl.ts` | verified |  |
| grafana | `public/app/features/variables/inspect/NetworkGraph.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/grafana-testdata-datasource/jest-setup.js` | verified |  |
| grafana | `public/app/plugins/panel/geomap/editor/layerEditor.tsx` | verified |  |
