# Target OSS no-LLM dogfooding audit — continuation 338 (batch 339)

Run: 2026-07-22T20:37:27.927538+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/test/issue6997_linux.go` | verified |  |
| go | `src/cmd/compile/internal/amd64/simdssa.go` | verified |  |
| go | `src/cmd/compile/internal/escape/stmt.go` | verified |  |
| go | `src/compress/flate/level2.go` | verified |  |
| go | `src/container/heap/example_pq_test.go` | verified |  |
| go | `src/html/template/transition.go` | verified |  |
| go | `src/internal/strconv/itoa_test.go` | verified |  |
| go | `src/os/root_js.go` | verified |  |
| go | `src/runtime/trace/annotation.go` | verified |  |
| go | `src/text/template/parse/lex_test.go` | verified |  |
| go | `test/fixedbugs/bug106.dir/bug1.go` | verified |  |
| go | `test/fixedbugs/issue14646.go` | verified |  |
| go | `test/fixedbugs/issue43835.go` | verified |  |
| go | `test/reflectmethod4.go` | verified |  |
| go | `test/typeparam/geninline.dir/main.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v3.go` | verified |  |
| grafana | `packages/grafana-runtime/src/components/EmbeddedDashboard.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/VizTooltip/VizTooltipColorIndicator.tsx` | verified |  |
| grafana | `pkg/plugins/localfiles.go` | verified |  |
| grafana | `pkg/registry/apis/datasource/migrator/validator.go` | verified |  |
| grafana | `pkg/registry/apis/iam/serviceaccount/mutate.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs_test.go` | verified |  |
| grafana | `pkg/services/apiserver/options/storage_test.go` | verified |  |
| grafana | `pkg/services/dashboardsnapshots/service.go` | verified |  |
| grafana | `pkg/storage/secret/metadata/secure_value_store_test.go` | verified |  |
| grafana | `pkg/storage/unified/search/bleve_mappings_test.go` | verified |  |
| grafana | `pkg/storage/unified/sql/db/migrations/resource_rv_fix_mig.go` | verified |  |
| grafana | `public/app/core/components/SharedPreferences/SharedPreferencesFunctional.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/notification-policies/PoliciesList.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/notificaton-preview/NotificationPolicySidebar.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/pages/utils.ts` | verified |  |
| grafana | `public/app/features/explore/TimeSyncButton.tsx` | verified |  |
| grafana | `public/app/features/home/Recommendations/RecommendationExisting.tsx` | verified |  |
| grafana | `public/app/features/plugins/admin/pages/PluginDetails.tsx` | verified |  |
| grafana | `public/app/features/provisioning/Config/PullRequestOptionsSection.tsx` | verified |  |
| grafana | `public/app/features/provisioning/components/Dashboards/ProvisionedImportForm.tsx` | verified |  |
| grafana | `public/app/features/serviceaccounts/state/reducers.ts` | verified |  |
| grafana | `public/app/features/variables/state/keyedVariablesReducer.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/language/cloudwatch-logs-sql/completion/suggestionKind.ts` | verified |  |
| grafana | `public/app/plugins/panel/table/panelcfg.gen.ts` | verified |  |
| prysm | `beacon-chain/db/filesystem/doc.go` | verified |  |
| prysm | `cmd/prysmctl/db/buckets.go` | verified |  |
| prysm | `config/features/config.go` | verified |  |
| prysm | `consensus-types/hdiff/state_diff_gloas_test.go` | verified |  |
| prysm | `crypto/bls/blst/doc.go` | verified |  |
| prysm | `crypto/bls/constants.go` | verified |  |
| prysm | `testing/spectest/mainnet/capella__operations__block_header_test.go` | verified |  |
| prysm | `testing/spectest/shared/altair/operations/proposer_slashing.go` | verified |  |
| prysm | `testing/spectest/shared/common/operations/attester_slashing.go` | verified |  |
| prysm | `testing/spectest/shared/electra/epoch_processing/slashings_reset.go` | verified |  |
