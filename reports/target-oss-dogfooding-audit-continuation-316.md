# Target OSS no-LLM dogfooding audit — continuation 316 (batch 317)

Run: 2026-07-22T19:06:48.687522+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/ast.go` | verified |  |
| go | `src/cmd/covdata/metamerge.go` | verified |  |
| go | `src/cmd/cover/html.go` | verified |  |
| go | `src/crypto/internal/fips140/aes/gcm/interface_test.go` | verified |  |
| go | `src/debug/elf/file.go` | verified |  |
| go | `src/internal/buildcfg/cfg_test.go` | verified |  |
| go | `src/internal/runtime/gc/internal/gen/simd.go` | verified |  |
| go | `src/io/fs/walk_test.go` | verified |  |
| go | `src/strconv/example_test.go` | verified |  |
| go | `test/cmplxdivide.go` | verified |  |
| go | `test/fixedbugs/bug221.go` | verified |  |
| go | `test/fixedbugs/issue33020a.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue5841.go` | verified |  |
| go | `test/prove.go` | verified |  |
| go | `test/typeparam/issue376214.go` | verified |  |
| go | `test/typeparam/typelist.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v2beta1/notebook_codec_gen.go` | verified |  |
| grafana | `apps/dashvalidator/pkg/apis/dashvalidator/v1alpha1/constants.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/applyconfiguration/provisioning/v0alpha1/connectioninfo.go` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/iam/v0alpha1/index.ts` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/preferences/v1alpha1/index.ts` | verified |  |
| grafana | `packages/grafana-data/src/themes/registry.ts` | verified |  |
| grafana | `pkg/components/apikeygen/apikeygen.go` | verified |  |
| grafana | `pkg/services/auth/gcomsso/gcom_logout_hook_test.go` | verified |  |
| grafana | `pkg/services/provisioning/alerting/notification_policy_types.go` | verified |  |
| grafana | `pkg/storage/legacysql/time_test.go` | verified |  |
| grafana | `pkg/storage/unified/search/bleve_mappings_golden_test.go` | verified |  |
| grafana | `public/app/core/components/TimelineChart/timeline.ts` | verified |  |
| grafana | `public/app/features/admin/UserProfile.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/AnnotationDetailsField.tsx` | verified |  |
| grafana | `public/app/features/canvas/runtime/scene.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/Sidebar/SectionEmptyState.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/TracePageHeader/SearchBar/TracePageSearchBar.tsx` | verified |  |
| grafana | `public/app/features/profile/state/reducers.ts` | verified |  |
| grafana | `public/app/features/provisioning/Shared/ConnectRepositoryButton.tsx` | verified |  |
| grafana | `public/app/features/transformers/extractFields/ExtractFieldsTransformerEditor.tsx` | verified |  |
| grafana | `public/app/features/users/UsersListPage.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/jest.config.js` | verified |  |
| grafana | `public/app/plugins/datasource/grafana-testdata-datasource/components/CSVContentEditor.tsx` | verified |  |
| grafana | `public/app/plugins/panel/gauge/GaugePanel.tsx` | verified |  |
| prysm | `api/jwt_test.go` | verified |  |
| prysm | `beacon-chain/core/electra/consolidations_test.go` | verified |  |
| prysm | `cmd/beacon-chain/storage/options_test.go` | verified |  |
| prysm | `cmd/flags_test.go` | verified |  |
| prysm | `config/util.go` | verified |  |
| prysm | `testing/spectest/mainnet/bellatrix__operations__deposit_test.go` | verified |  |
| prysm | `testing/spectest/minimal/altair__light_client__single_merkle_proof_test.go` | verified |  |
| prysm | `testing/spectest/shared/altair/operations/deposit.go` | verified |  |
| prysm | `testing/spectest/shared/capella/finality/finality.go` | verified |  |
| prysm | `validator/client/beacon-api/duties.go` | verified |  |
