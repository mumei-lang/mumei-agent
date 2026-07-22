# Target OSS no-LLM dogfooding audit — continuation 263 (batch 264)

Run: 2026-07-22T15:35:17.132893+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification after fixing Go top nil-guarded receivers and Unicode identifier extraction.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/types2/array.go` | verified |  |
| go | `src/cmd/go/internal/load/flag_test.go` | verified |  |
| go | `src/cmd/internal/objfile/xcoff.go` | verified |  |
| go | `src/path/filepath/match.go` | verified |  |
| go | `test/fixedbugs/bug313.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue11354.go` | verified |  |
| go | `test/fixedbugs/issue15470.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue19168.go` | verified |  |
| go | `test/fixedbugs/issue27836.dir/Þfoo.go` | verified |  |
| go | `test/fixedbugs/issue29610.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue53982.go` | verified |  |
| go | `test/fixedbugs/issue54722b.go` | verified |  |
| go | `test/fixedbugs/issue58563.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue7675.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v22_test.go` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/TableNG/styles.ts` | verified |  |
| grafana | `pkg/api/bootdata.go` | verified |  |
| grafana | `pkg/registry/apis/dashboard/migrator/migrator.go` | verified |  |
| grafana | `pkg/services/authn/clients/grafana.go` | verified |  |
| grafana | `pkg/services/featuremgmt/service.go` | verified |  |
| grafana | `pkg/services/ngalert/models/notifications.go` | verified |  |
| grafana | `pkg/services/ngalert/state/template/funcs_test.go` | verified |  |
| grafana | `pkg/services/serviceaccounts/database/store_test.go` | verified |  |
| grafana | `pkg/tests/api/correlations/correlations_provisioning_api_test.go` | verified |  |
| grafana | `pkg/tsdb/grafana-postgresql-datasource/pool_config_test.go` | verified |  |
| grafana | `public/app/core/components/TagFilter/TagBadge.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/import-to-gma/steps/utils.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/types/rule-form.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/utils/k8s/utils.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/serialization/annotations.ts` | verified |  |
| grafana | `public/app/features/dashboard/dashgrid/DashboardLibrary/SuggestedDashboardsList/DashboardResultsGrid.tsx` | verified |  |
| grafana | `public/app/features/explore/PrometheusListView/RawListItemAttributes.tsx` | verified |  |
| grafana | `public/app/features/folders/state/navModel.ts` | verified |  |
| grafana | `public/app/features/live/dashboard/DashboardChangedModal.tsx` | verified |  |
| grafana | `public/app/features/playlist/types.ts` | verified |  |
| grafana | `public/app/features/provisioning/hooks/useProvisionedRequestHandler.ts` | verified |  |
| grafana | `public/app/plugins/datasource/graphite/components/MetricTankMetaInspector.tsx` | verified |  |
| grafana | `public/app/plugins/panel/heatmap/renderHistogram.tsx` | verified |  |
| grafana | `public/app/plugins/panel/heatmap/types.ts` | verified |  |
| prysm | `beacon-chain/cache/checkpoint_state_test.go` | verified |  |
| prysm | `beacon-chain/node/registration/log.go` | verified |  |
| prysm | `beacon-chain/rpc/eth/blob/handlers_test.go` | verified |  |
| prysm | `beacon-chain/rpc/lookup/blocker.go` | verified |  |
| prysm | `beacon-chain/rpc/prysm/v1alpha1/validator/attester.go` | verified |  |
| prysm | `beacon-chain/state/state-native/mvslice_fuzz_test.go` | verified |  |
| prysm | `cmd/beacon-chain/log.go` | verified |  |
| prysm | `proto/engine/v1/electra_test.go` | verified |  |
| prysm | `testing/slasher/simulator/simulator.go` | verified |  |
| prysm | `validator/client/subnets.go` | verified |  |
| prysm | `validator/db/filesystem/migration.go` | verified |  |
