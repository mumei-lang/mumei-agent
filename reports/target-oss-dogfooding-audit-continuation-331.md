# Target OSS no-LLM dogfooding audit — continuation 331 (batch 332)

Run: 2026-07-22T20:07:35.775405+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/go/ast/filter.go` | verified |  |
| go | `src/hash/maphash/maphash_test.go` | verified |  |
| go | `src/internal/zstd/zstd.go` | verified |  |
| go | `src/net/tcpconn_keepalive_conf_posix_test.go` | verified |  |
| go | `src/sync/waitgroup_test.go` | verified |  |
| go | `src/syscall/js/js_test.go` | verified |  |
| go | `src/syscall/zsyscall_openbsd_386.go` | verified |  |
| go | `test/fixedbugs/issue15902.go` | verified |  |
| go | `test/fixedbugs/issue18747.go` | verified |  |
| go | `test/fixedbugs/issue20014.go` | verified |  |
| go | `test/fixedbugs/issue26855.go` | verified |  |
| go | `test/fixedbugs/issue33460.go` | verified |  |
| go | `test/fixedbugs/issue40367.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/workflows.go` | verified |  |
| grafana | `packages/grafana-ui/src/components/DateTimePickers/TimeZonePicker.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Select/SelectContainer.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/themes/GlobalStyles/filterTable.ts` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/sync/folder_metadata_diff_split_test.go` | verified |  |
| grafana | `pkg/services/accesscontrol/migrator/migrator_test.go` | verified |  |
| grafana | `pkg/services/auth/jwt/rsa_keys_test.go` | verified |  |
| grafana | `pkg/services/authn/identity_test.go` | verified |  |
| grafana | `pkg/services/live/pipeline/frame_output_threshold.go` | verified |  |
| grafana | `pkg/services/ngalert/schedule/ticker/ticker.go` | verified |  |
| grafana | `pkg/services/secrets/fakes/fake_service.go` | verified |  |
| grafana | `pkg/tests/apis/folder/parity_test.go` | verified |  |
| grafana | `pkg/tests/apis/iam/resourcepermission/resource_permissions_integration_test.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/panel-alerts-tab/NewRuleFromPanelButton.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/hooks/useProduceNewAlertmanagerConfig.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/mocks/alertmanagerApi.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/utils/misc.ts` | verified |  |
| grafana | `public/app/features/correlations/__mocks__/server.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/mutation-api/commands/updateTab.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/variables/components/IntervalVariableForm.tsx` | verified |  |
| grafana | `public/app/features/explore/extensions/toolbar/QuerylessAppsExtensions.tsx` | verified |  |
| grafana | `public/app/features/manage-dashboards/services/ValidationSrv.ts` | verified |  |
| grafana | `public/app/features/plugins/admin/hooks/usePluginConfig.tsx` | verified |  |
| grafana | `public/app/features/variables/inspect/utils.ts` | verified |  |
| grafana | `public/app/plugins/panel/timeseries/NullsThresholdInput.tsx` | verified |  |
| grafana | `scripts/go-workspace/main.go` | verified |  |
| prysm | `api/client/client_test.go` | verified |  |
| prysm | `api/server/structs/endpoints_events.go` | verified |  |
| prysm | `beacon-chain/cache/highest_execution_payload_bid_test.go` | verified |  |
| prysm | `beacon-chain/core/altair/exports_test.go` | verified |  |
| prysm | `beacon-chain/core/feed/state/notifier.go` | verified |  |
| prysm | `beacon-chain/rpc/prysm/v1alpha1/validator/exit_test.go` | verified |  |
| prysm | `beacon-chain/state/state-native/hasher_test.go` | verified |  |
| prysm | `cmd/prysmctl/p2p/mock_chain.go` | verified |  |
| prysm | `consensus-types/interfaces/signed_execution_payload_bid.go` | verified |  |
| prysm | `crypto/bls/common/interface.go` | verified |  |
| prysm | `testing/util/fulu_state.go` | verified |  |
