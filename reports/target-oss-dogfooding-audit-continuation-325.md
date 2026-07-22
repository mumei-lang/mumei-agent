# Target OSS no-LLM dogfooding audit — continuation 325 (batch 326)

Run: 2026-07-22T19:46:00.215488+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/testcarchive/carchive_test.go` | verified |  |
| go | `src/compress/gzip/example_test.go` | verified |  |
| go | `src/crypto/rand/rand_test.go` | verified |  |
| go | `src/crypto/tls/bogo_shim_test.go` | verified |  |
| go | `src/log/slog/internal/ignorepc.go` | verified |  |
| go | `src/runtime/proc_runtime_test.go` | verified |  |
| go | `test/crlf.go` | verified |  |
| go | `test/fixedbugs/issue12686.go` | verified |  |
| go | `test/fixedbugs/issue15514.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue18661.go` | verified |  |
| go | `test/fixedbugs/issue38916.go` | verified |  |
| grafana | `apps/folder/pkg/apis/folder/v1beta1/types.go` | verified |  |
| grafana | `apps/plugins/pkg/app/meta/provider.go` | verified |  |
| grafana | `packages/grafana-data/src/types/fieldOverrides.ts` | verified |  |
| grafana | `packages/grafana-data/src/utils/OptionsUIBuilders.ts` | verified |  |
| grafana | `packages/grafana-runtime/src/services/pluginMeta/mappers/mappers.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/DateTimePickers/DatePickerWithInput/DatePickerWithInput.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/DateTimePickers/TimeRangePicker/hooks.ts` | verified |  |
| grafana | `pkg/infra/httpclient/httpclientprovider/prometheus_metrics_middleware_test.go` | verified |  |
| grafana | `pkg/services/anonymous/anonimpl/api/api.go` | verified |  |
| grafana | `pkg/services/ngalert/prom/query.go` | verified |  |
| grafana | `pkg/services/team/teamapi/team_members_adapter_test.go` | verified |  |
| grafana | `pkg/setting/setting_secrets_manager_test.go` | verified |  |
| grafana | `pkg/tests/api/influxdb/influxdb_test.go` | verified |  |
| grafana | `pkg/tests/apis/iam/user/user_search_integration_test.go` | verified |  |
| grafana | `pkg/util/xorm/session_update.go` | verified |  |
| grafana | `public/app/core/components/AccessControl/Permissions.tsx` | verified |  |
| grafana | `public/app/core/components/AppChrome/TopBar/useChromeHeaderHeight.ts` | verified |  |
| grafana | `public/app/core/history/RichHistoryStorage.ts` | verified |  |
| grafana | `public/app/core/hooks/useMediaQueryMinWidth.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-viewer/EvalStatus.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/mutation-api/commands/updateLayout.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/variables/components/TextBoxVariableForm.tsx` | verified |  |
| grafana | `public/app/features/dashboard/dashgrid/DashboardLibrary/GrafanaTemplatesTab.tsx` | verified |  |
| grafana | `public/app/features/explore/Logs/LogsMetaRow.tsx` | verified |  |
| grafana | `public/app/features/explore/RichHistory/RichHistoryQueriesTab.tsx` | verified |  |
| grafana | `public/app/features/explore/state/selectors.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/mocks/dynamic-label-test-data/afterLabelValue.ts` | verified |  |
| grafana | `public/app/plugins/panel/status-history/StatusHistoryPanel.tsx` | verified |  |
| grafana | `public/swagger/plugins.tsx` | verified |  |
| prysm | `beacon-chain/cache/highest_execution_payload_bid.go` | verified |  |
| prysm | `beacon-chain/rpc/prysm/v1alpha1/validator/duties_v3_test.go` | verified |  |
| prysm | `beacon-chain/sync/data_column_sidecars_test.go` | verified |  |
| prysm | `testing/bls/sign_test.go` | verified |  |
| prysm | `testing/spectest/mainnet/gloas__operations__attestation_test.go` | verified |  |
| prysm | `testing/spectest/minimal/bellatrix__operations__attestation_test.go` | verified |  |
| prysm | `testing/spectest/shared/electra/merkle_proof/merkle_proof.go` | verified |  |
| prysm | `testing/spectest/shared/electra/operations/block_header.go` | verified |  |
| prysm | `testing/spectest/shared/phase0/epoch_processing/randao_mixes_reset.go` | verified |  |
| prysm | `validator/client/beacon-api/state_validators.go` | verified |  |
