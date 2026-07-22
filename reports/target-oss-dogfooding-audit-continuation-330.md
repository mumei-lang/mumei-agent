# Target OSS no-LLM dogfooding audit — continuation 330 (batch 331)

Run: 2026-07-22T20:04:47.727476+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/arm64/pair.go` | verified |  |
| go | `src/cmd/compile/internal/importer/gcimporter.go` | verified |  |
| go | `src/cmd/link/internal/sym/symkind.go` | verified |  |
| go | `src/crypto/internal/fips140/ecdsa/cast.go` | verified |  |
| go | `src/crypto/internal/fips140/subtle/xor_riscv64.go` | verified |  |
| go | `src/go/types/interface.go` | verified |  |
| go | `src/net/hosts.go` | verified |  |
| go | `src/syscall/route_darwin.go` | verified |  |
| go | `test/fixedbugs/bug362.go` | verified |  |
| go | `test/fixedbugs/issue4283.go` | verified |  |
| go | `test/fixedbugs/issue48476.go` | verified |  |
| go | `test/typeparam/issue50552.dir/main.go` | verified |  |
| go | `test/typeparam/issue54302.go` | verified |  |
| go | `test/typeparam/mdempsky/9.go` | verified |  |
| grafana | `apps/example/pkg/apis/example/v1alpha1/example_custom_gen.go` | verified |  |
| grafana | `apps/live/pkg/apis/manifestdata/live_manifest.go` | verified |  |
| grafana | `apps/shorturl/plugin/src/generated/shorturl/v1beta1/types.metadata.gen.ts` | verified |  |
| grafana | `packages/grafana-schema/src/raw/composable/stat/panelcfg/x/types.gen.ts` | verified |  |
| grafana | `packages/grafana-sql/src/components/TableSelector.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Combobox/filter.ts` | verified |  |
| grafana | `pkg/infra/filestorage/cdk_blob_filestorage.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/resources/dualwriter.go` | verified |  |
| grafana | `pkg/registry/apis/secret/contracts/data_key.go` | verified |  |
| grafana | `pkg/services/frontend/request_config_middleware.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/routes/testing.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/dashboard_version_mig.go` | verified |  |
| grafana | `pkg/storage/unified/search/embed/pending_delete_test.go` | verified |  |
| grafana | `pkg/tsdb/azuremonitor/azuremonitor-resource-handler.go` | verified |  |
| grafana | `pkg/tsdb/influxdb/models/model_parser_test.go` | verified |  |
| grafana | `public/app/core/components/RolePicker/RoleMenuGroupOption.tsx` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| grafana | `public/app/core/components/TimeSeries/utils.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/variables/components/VariableMultiPropStaticOptionsForm.tsx` | verified |  |
| grafana | `public/app/features/explore/hooks/useStateSync/external.utils.ts` | verified |  |
| grafana | `public/app/features/library-panels/state/api.ts` | verified |  |
| grafana | `public/app/features/provisioning/Shared/TokenPermissionsInfo.tsx` | verified |  |
| grafana | `public/app/features/provisioning/Wizard/GitHubAppFields.tsx` | verified |  |
| grafana | `public/app/features/variables-management/components/MoveVariablesModal.tsx` | verified |  |
| grafana | `public/app/features/variables/shared/testing/multiVariableBuilder.ts` | verified |  |
| grafana | `public/app/plugins/panel/logstable/transforms/organizeLogsFieldsTransform.ts` | verified |  |
| prysm | `beacon-chain/cache/depositsnapshot/spec_test.go` | verified |  |
| prysm | `beacon-chain/core/helpers/validators.go` | verified |  |
| prysm | `beacon-chain/db/kv/kv.go` | verified |  |
| prysm | `beacon-chain/light-client/store_test.go` | verified |  |
| prysm | `beacon-chain/sync/subscriber_signed_proposer_preferences_test.go` | verified |  |
| prysm | `testing/endtoend/evaluators/validator_test.go` | verified |  |
| prysm | `testing/spectest/mainnet/altair__forkchoice__forkchoice_test.go` | verified |  |
| prysm | `testing/spectest/mainnet/altair__random__random_test.go` | verified |  |
| prysm | `testing/spectest/mainnet/capella__epoch_processing__justification_and_finalization_test.go` | verified |  |
| prysm | `testing/spectest/mainnet/capella__epoch_processing__randao_mixes_reset_test.go` | verified |  |
| prysm | `testing/spectest/minimal/phase0__epoch_processing__randao_mixes_reset_test.go` | verified |  |
