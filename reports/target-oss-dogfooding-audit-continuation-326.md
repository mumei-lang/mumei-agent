# Target OSS no-LLM dogfooding audit — continuation 326 (batch 327)

Run: 2026-07-22T19:48:56.519499+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `lib/time/mkzip.go` | verified |  |
| go | `src/cmd/compile/internal/syntax/testing.go` | verified |  |
| go | `src/cmd/compile/internal/types/utils.go` | verified |  |
| go | `src/internal/goarch/zgoarch_mips.go` | verified |  |
| go | `src/runtime/export_debug_arm64_test.go` | verified |  |
| go | `test/abi/named_results.go` | verified |  |
| go | `test/fixedbugs/bug106.go` | verified |  |
| go | `test/fixedbugs/issue27718.go` | verified |  |
| go | `test/fixedbugs/issue32778.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue4529.go` | verified |  |
| go | `test/fixedbugs/issue5089.go` | verified |  |
| go | `test/typeparam/mdempsky/19.go` | verified |  |
| go | `test/typeparam/mdempsky/6.go` | verified |  |
| go | `test/typeparam/mdempsky/7.go` | verified |  |
| grafana | `apps/annotation/pkg/apis/annotation/v0alpha1/client_gen.go` | verified |  |
| grafana | `apps/dashvalidator/pkg/apis/dashvalidator/v1alpha1/dashboardcompatibilityscore_object_gen.go` | verified |  |
| grafana | `apps/preferences/pkg/apis/preferences/v1/constants.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/github/impl.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/workflows_test.go` | verified |  |
| grafana | `packages/grafana-runtime/src/analytics/types.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/utils.ts` | verified |  |
| grafana | `packages/grafana-ui/src/utils/tags.ts` | verified |  |
| grafana | `pkg/api/admin_provisioning_test.go` | verified |  |
| grafana | `pkg/expr/hysteresis.go` | verified |  |
| grafana | `pkg/middleware/dashboard_redirect.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/filepath.go` | verified |  |
| grafana | `pkg/services/live/pipeline/frame_output_threshold_test.go` | verified |  |
| grafana | `pkg/services/ngalert/models/rule_sequence.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/adapters/adapters.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/angulardetectorsprovider/dynamic_test.go` | verified |  |
| grafana | `pkg/services/serviceaccounts/tests/extsvcaccmock.go` | verified |  |
| grafana | `pkg/storage/legacysql/dualwrite/context.go` | verified |  |
| grafana | `pkg/tsdb/azuremonitor/azmoncredentials/builder.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/receivers/TemplateData.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/rule-list/GrafanaRuleListItem.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/Sidebar/AddCardButton.tsx` | verified |  |
| grafana | `public/app/features/dashboard/dashgrid/DashboardLibrary/SuggestedDashboardsList/EmptyResults.tsx` | verified |  |
| grafana | `public/app/features/explore/RecentQueries/RecentQueriesFilters.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/custom.d.ts` | verified |  |
| grafana | `public/app/plugins/panel/barchart/test-helpers.ts` | verified |  |
| prysm | `beacon-chain/core/signing/domain_test.go` | verified |  |
| prysm | `beacon-chain/state/stategen/migrate.go` | verified |  |
| prysm | `beacon-chain/sync/backfill/verify_test.go` | verified |  |
| prysm | `config/params/log.go` | verified |  |
| prysm | `runtime/interop/premined_genesis_state.go` | verified |  |
| prysm | `testing/bls/aggregate_test.go` | verified |  |
| prysm | `testing/spectest/mainnet/gloas__epoch_processing__participation_flag_updates_test.go` | verified |  |
| prysm | `testing/spectest/minimal/altair__fork__upgrade_to_altair_test.go` | verified |  |
| prysm | `testing/spectest/minimal/deneb__epoch_processing__rewards_and_penalties_test.go` | verified |  |
| prysm | `testing/spectest/shared/common/operations/deposit_request.go` | verified |  |
