# Target OSS no-LLM dogfooding audit — continuation 413 (batch 414)

Run: 2026-07-23T01:16:45.911337+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/s390x/ggen.go` | verified |  |
| go | `src/cmd/compile/internal/typecheck/bexport.go` | verified |  |
| go | `src/cmd/internal/pgo/serialize.go` | verified |  |
| go | `src/compress/flate/dict_decoder_test.go` | verified |  |
| go | `src/compress/lzw/reader_test.go` | verified |  |
| go | `src/crypto/internal/fips140test/indicator_test.go` | verified |  |
| go | `src/crypto/mldsa/mldsa_test.go` | verified |  |
| go | `src/internal/bytealg/count_generic.go` | verified |  |
| go | `src/net/ipsock_test.go` | verified |  |
| go | `src/runtime/mpagecache_test.go` | verified |  |
| go | `test/fixedbugs/issue12108.go` | verified |  |
| go | `test/fixedbugs/issue16133.dir/a1.go` | verified |  |
| go | `test/fixedbugs/issue26341.go` | verified |  |
| go | `test/fixedbugs/issue28055.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v2alpha1/zz_generated.conversion.go` | verified |  |
| grafana | `apps/dashvalidator/pkg/generated/manifestdata/dashvalidator_manifest.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/local/local_test.go` | verified |  |
| grafana | `packages/grafana-data/src/dataframe/MutableDataFrame.ts` | verified |  |
| grafana | `packages/grafana-data/src/text/sanitize.ts` | verified |  |
| grafana | `packages/grafana-data/src/types/navModel.ts` | verified |  |
| grafana | `packages/grafana-runtime/src/services/pluginMeta/logging.ts` | verified |  |
| grafana | `packages/grafana-test-utils/jest.config.js` | verified |  |
| grafana | `packages/grafana-ui/src/components/PageLayout/PageToolbar.tsx` | verified |  |
| grafana | `pkg/apis/service/v0alpha1/zz_generated.defaults.go` | verified |  |
| grafana | `pkg/expr/mathexp/funcs_test.go` | verified |  |
| grafana | `pkg/registry/apis/secret/encryption/cipher/provider/aes256_test.go` | verified |  |
| grafana | `pkg/services/accesscontrol/metadata_test.go` | verified |  |
| grafana | `pkg/services/ngalert/api/lotex_ruler.go` | verified |  |
| grafana | `pkg/services/ngalert/models/accesscontrol.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/plugintest/plugins_test.go` | verified |  |
| grafana | `pkg/services/secrets/secrets.go` | verified |  |
| grafana | `pkg/services/ssosettings/ssosettingstests/service_fake.go` | verified |  |
| grafana | `pkg/storage/secret/encryption/encrypted_value_model.go` | verified |  |
| grafana | `pkg/storage/unified/apistore/doc.go` | verified |  |
| grafana | `pkg/storage/unified/resource/storage_backend_bulk_test.go` | verified |  |
| grafana | `pkg/storage/unified/sql/db/dbimpl/driver_test.go` | verified |  |
| grafana | `pkg/storage/unified/testing/lease_test.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/get_dimension_values_for_wildcards_test.go` | verified |  |
| grafana | `public/app/features/alerting/unified/insights/SectionSubheader.tsx` | verified |  |
| grafana | `public/app/features/browse-dashboards/state/hooks.ts` | verified |  |
| grafana | `public/app/features/commandPalette/actions/useActions.tsx` | verified |  |
| grafana | `public/app/features/dashboard/api/UnifiedDashboardAPI.ts` | verified |  |
| grafana | `public/app/features/explore/hooks/useStateSync/migrators/v0.ts` | verified |  |
| grafana | `public/app/features/home/DashboardTabs/DashboardTabsSkeleton.tsx` | verified |  |
| grafana | `public/app/features/migrate-to-cloud/api/errors.ts` | verified |  |
| grafana | `public/app/features/org/NewOrgPage.tsx` | verified |  |
| grafana | `public/app/features/stars/folders.ts` | verified |  |
| grafana | `public/app/features/transformers/editors/CalculateFieldTransformerEditor/BinaryOperationOptionsEditor.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/mocks/ResourcesAPI.ts` | verified |  |
| grafana | `scripts/modowners/modowners.go` | verified |  |
