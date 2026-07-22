# Target OSS no-LLM dogfooding audit — continuation 352 (batch 353)

Run: 2026-07-22T21:07:59.443441+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/debug/dwarf/const.go` | verified |  |
| go | `src/go/types/commentMap_test.go` | verified |  |
| go | `src/internal/syscall/unix/at_fstatat.go` | verified |  |
| go | `src/internal/syscall/windows/reparse_windows.go` | verified |  |
| go | `src/math/big/hilbert_test.go` | verified |  |
| go | `src/net/main_windows_test.go` | verified |  |
| go | `src/os/exec/internal/fdtest/exists_test.go` | verified |  |
| go | `src/reflect/stubs_riscv64.go` | verified |  |
| go | `src/runtime/auxv_none.go` | verified |  |
| go | `test/codegen/shape_assert.go` | verified |  |
| go | `test/codegen/stack.go` | verified |  |
| go | `test/fixedbugs/issue19507.dir/main.go` | verified |  |
| go | `test/fixedbugs/issue33020.go` | verified |  |
| go | `test/fixedbugs/issue43479.go` | verified |  |
| go | `test/fixedbugs/issue6789.go` | verified |  |
| go | `test/fixedbugs/issue8073.go` | verified |  |
| go | `test/typeparam/mdempsky/7.dir/a.go` | verified |  |
| grafana | `apps/annotation/pkg/app/app.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/conversion/conversion.go` | verified |  |
| grafana | `packages/get-document/index.js` | verified |  |
| grafana | `packages/grafana-sql/src/components/visual-query-builder/SQLGroupByRow.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Combobox/utils.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/InlineToast/InlineToast.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/InteractiveTable/types.ts` | verified |  |
| grafana | `pkg/cmd/grafana-cli/services/api_client.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/resources/authorizer_test.go` | verified |  |
| grafana | `pkg/services/ngalert/provisioning/accesscontrol.go` | verified |  |
| grafana | `pkg/services/plugindashboards/service/dashboard_updater.go` | verified |  |
| grafana | `pkg/services/ssosettings/strategies/saml_strategy.go` | verified |  |
| grafana | `pkg/storage/unified/sql/backend_bulk.go` | verified |  |
| grafana | `pkg/tests/apis/alerting/notifications/config/config_test.go` | verified |  |
| grafana | `pkg/tests/apis/openapi_test.go` | verified |  |
| grafana | `public/app/core/components/NestedFolderPicker/Skeleton.tsx` | verified |  |
| grafana | `public/app/features/browse-dashboards/state/reducers.ts` | verified |  |
| grafana | `public/app/features/dashboard/dashgrid/DashboardLibrary/utils/dashboardLibraryHelpers.ts` | verified |  |
| grafana | `public/app/features/explore/PrometheusListView/RawListItem.tsx` | verified |  |
| grafana | `public/app/features/profile/UserProfileEditForm.tsx` | verified |  |
| grafana | `public/app/features/variables/pickers/OptionsPicker/actions.ts` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/azureMetadata/logsResourceTypes.ts` | verified |  |
| grafana | `public/app/plugins/datasource/grafana/module.ts` | verified |  |
| prysm | `beacon-chain/blockchain/defragment.go` | verified |  |
| prysm | `beacon-chain/core/blocks/randao_test.go` | verified |  |
| prysm | `beacon-chain/db/filesystem/layout_test.go` | verified |  |
| prysm | `beacon-chain/rpc/prysm/v1alpha1/validator/proposer_sync_aggregate.go` | verified |  |
| prysm | `beacon-chain/state/stategen/service_test.go` | verified |  |
| prysm | `testing/spectest/mainnet/gloas__operations__builder_exit_request_test.go` | verified |  |
| prysm | `testing/spectest/minimal/electra__epoch_processing__inactivity_updates_test.go` | verified |  |
| prysm | `testing/spectest/shared/altair/sanity/block_processing.yaml.go` | verified |  |
| prysm | `testing/spectest/shared/phase0/epoch_processing/helpers.go` | verified |  |
| prysm | `validator/keymanager/local/import.go` | verified |  |
