# Target OSS no-LLM dogfooding audit — continuation 293 (batch 294)

Run: 2026-07-22T17:35:22.975598+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/logopt/logopt_test.go` | verified |  |
| go | `src/cmd/internal/obj/arm64/encoding_gen.go` | verified |  |
| go | `src/go/parser/example_test.go` | verified |  |
| go | `src/image/jpeg/scan.go` | verified |  |
| go | `src/net/rpc/server_test.go` | verified |  |
| go | `src/runtime/debug/stack_test.go` | verified |  |
| go | `src/runtime/mprof_test.go` | verified |  |
| go | `src/text/template/doc.go` | verified |  |
| go | `src/time/zoneinfo_plan9.go` | verified |  |
| go | `test/fixedbugs/bug392.dir/pkg2.go` | verified |  |
| go | `test/fixedbugs/issue33158.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue7316.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v0alpha1/receiver_client_gen.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v0alpha1/dashboard_status_gen.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v2beta1/variable_spec_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/connection/github/validator_test.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/github/mock_commit_file.go` | verified |  |
| grafana | `packages/grafana-test-utils/src/handlers/index.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/DateTimePickers/RelativeTimeRangePicker/utils.ts` | verified |  |
| grafana | `packages/grafana-ui/src/themes/stylesFactory.ts` | verified |  |
| grafana | `pkg/api/org_users_test.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/request.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/resources/client_test.go` | verified |  |
| grafana | `pkg/services/featuremgmt/static_provider.go` | verified |  |
| grafana | `pkg/services/ngalert/api/tooling/definitions/prom_bench_test.go` | verified |  |
| grafana | `pkg/services/ssosettings/strategies/saml_strategy_test.go` | verified |  |
| grafana | `pkg/services/store/utils_test.go` | verified |  |
| grafana | `pkg/storage/unified/resource/search_field_test.go` | verified |  |
| grafana | `pkg/tsdb/azuremonitor/sql_resources_test.go` | verified |  |
| grafana | `public/app/core/components/QueryOperationRow/QueryOperationRowHeader.tsx` | verified |  |
| grafana | `public/app/core/components/Select/OrgPicker.tsx` | verified |  |
| grafana | `public/app/core/journeys/searchToResource.ts` | verified |  |
| grafana | `public/app/features/migrate-to-cloud/onprem/SupportedTypesDisclosure.tsx` | verified |  |
| grafana | `public/app/features/provisioning/GettingStarted/SidebarItem.tsx` | verified |  |
| grafana | `public/app/features/provisioning/Shared/StatusBadge.tsx` | verified |  |
| grafana | `public/app/features/provisioning/utils/currentUser.ts` | verified |  |
| grafana | `public/app/features/transformers/editors/CalculateFieldTransformerEditor/CumulativeOptionsEditor.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/LogsQueryEditor/AzureCheatSheet.tsx` | verified |  |
| grafana | `public/app/plugins/panel/logstable/testsUtils.ts` | verified |  |
| grafana | `public/test/core/utils/silenceConsoleOutput.ts` | verified |  |
| prysm | `beacon-chain/core/blocks/randao.go` | verified |  |
| prysm | `beacon-chain/core/gloas/deposit_request_test.go` | verified |  |
| prysm | `beacon-chain/state/state-native/spec_parameters.go` | verified |  |
| prysm | `beacon-chain/sync/doc.go` | verified |  |
| prysm | `beacon-chain/sync/validate_signed_proposer_preferences.go` | verified |  |
| prysm | `testing/endtoend/components/boot_node.go` | verified |  |
| prysm | `testing/spectest/mainnet/gloas__epoch_processing__eth1_data_reset_test.go` | verified |  |
| prysm | `testing/spectest/shared/bellatrix/rewards/rewards_penalties.go` | verified |  |
| prysm | `tools/specs-checker/check.go` | verified |  |
| prysm | `validator/client/metrics.go` | verified |  |
