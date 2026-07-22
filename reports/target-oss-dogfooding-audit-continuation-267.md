# Target OSS no-LLM dogfooding audit — continuation 267 (batch 268)

Run: 2026-07-22T15:46:18.872457+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/internal/robustio/robustio_darwin.go` | verified |  |
| go | `src/crypto/internal/fips140/nistec/fiat/p384.go` | verified |  |
| go | `src/crypto/tls/tls.go` | verified |  |
| go | `src/crypto/x509/parser_fips140v1.0_test.go` | verified |  |
| go | `src/encoding/gob/example_test.go` | verified |  |
| go | `src/go/constant/value_test.go` | verified |  |
| go | `src/internal/abi/export_test.go` | verified |  |
| go | `src/net/cgo_stub.go` | verified |  |
| go | `src/net/ipsock_posix.go` | verified |  |
| go | `test/fixedbugs/issue21655.go` | verified |  |
| go | `test/fixedbugs/issue23305.go` | verified |  |
| go | `test/fixedbugs/issue26407.go` | verified |  |
| go | `test/fixedbugs/issue29612.dir/p1/ssa/ssa.go` | verified |  |
| go | `test/fixedbugs/issue4932.go` | verified |  |
| go | `test/typeparam/issue51423.go` | verified |  |
| grafana | `apps/provisioning/pkg/apis/provisioning/v0alpha1/connections.go` | verified |  |
| grafana | `packages/grafana-ui/src/components/ConfirmButton/DeleteButton.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/TableNG/Filter/FilterList.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/cellUtils.ts` | verified |  |
| grafana | `packages/grafana-ui/src/index.ts` | verified |  |
| grafana | `pkg/middleware/request_metrics.go` | verified |  |
| grafana | `pkg/registry/apis/iam/resourcepermission/storage_backend_test.go` | verified |  |
| grafana | `pkg/registry/apis/secret/encryption/cipher/provider/aes256.go` | verified |  |
| grafana | `pkg/services/authn/clients/provisioning.go` | verified |  |
| grafana | `pkg/services/ngalert/state/historian/annotation_test.go` | verified |  |
| grafana | `pkg/services/star/starimpl/store_test.go` | verified |  |
| grafana | `pkg/storage/unified/resource/server.go` | verified |  |
| grafana | `pkg/tests/apis/preferences/k8s_preferences_test.go` | verified |  |
| grafana | `pkg/tsdb/grafana-testdata-datasource/resource_handler.go` | verified |  |
| grafana | `public/app/core/components/SharedPreferences/SharedPreferencesOld.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/PanelAlertRuleDrawer.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/triage/scene/Workbench.tsx` | verified |  |
| grafana | `public/app/features/dashboard/dashgrid/DashboardLibrary/utils/suggestedDashboardHelpers.ts` | verified |  |
| grafana | `public/app/features/explore/hooks/useExploreDataLinkPostProcessor.ts` | verified |  |
| grafana | `public/app/features/notifications/NotificationsPage.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/ArgQueryEditor/SubscriptionField.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/LogsQueryBuilder/GroupByItem.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/mocks/metric-math-test-data/secondArgQuery.ts` | verified |  |
| grafana | `public/app/plugins/panel/alertlist/unified-alerting/UngroupedView.tsx` | verified |  |
| grafana | `public/app/plugins/panel/debug/module.tsx` | verified |  |
| prysm | `beacon-chain/core/helpers/attestation.go` | verified |  |
| prysm | `beacon-chain/state/state-native/setters_withdrawal_test.go` | verified |  |
| prysm | `beacon-chain/sync/subscriber_test.go` | verified |  |
| prysm | `cmd/config_test.go` | verified |  |
| prysm | `testing/endtoend/evaluators/operations.go` | verified |  |
| prysm | `testing/spectest/mainnet/capella__epoch_processing__historical_summaries_update_test.go` | verified |  |
| prysm | `testing/spectest/minimal/bellatrix__epoch_processing__justification_and_finalization_test.go` | verified |  |
| prysm | `testing/spectest/minimal/fulu__operations__attestation_test.go` | verified |  |
| prysm | `tools/analyzers/modernize/minmax/analyzer.go` | verified |  |
| prysm | `tools/interop/export-genesis/main.go` | verified |  |
