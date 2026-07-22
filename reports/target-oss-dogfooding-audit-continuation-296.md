# Target OSS no-LLM dogfooding audit — continuation 296 (batch 297)

Run: 2026-07-22T17:50:28.655469+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/inline/inlheur/scoreadjusttyp_string.go` | verified |  |
| go | `src/cmd/go/internal/lockedfile/transform_test.go` | verified |  |
| go | `src/cmd/go/internal/toolchain/path_none.go` | verified |  |
| go | `src/debug/macho/file.go` | verified |  |
| go | `src/math/export_test.go` | verified |  |
| go | `src/runtime/debug/mod.go` | verified |  |
| go | `src/runtime/import_test.go` | verified |  |
| go | `src/runtime/runtime2.go` | verified |  |
| go | `src/runtime/vdso_linux_test.go` | verified |  |
| go | `test/fixedbugs/bug066.go` | verified |  |
| go | `test/fixedbugs/bug387.go` | verified |  |
| go | `test/fixedbugs/issue33020.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue65778.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v1beta1/routingtree_object_gen.go` | verified |  |
| grafana | `apps/dashvalidator/pkg/apis/dashvalidator/v1alpha1/createcheck_request_body_types_gen.go` | verified |  |
| grafana | `apps/logsdrilldown/pkg/apis/logsdrilldown/v1beta1/logsdrilldowndefaultcolumns_schema_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/git/git_repository_mock.go` | verified |  |
| grafana | `e2e-playwright/test-plugins/grafana-test-datasource/module.ts` | verified |  |
| grafana | `packages/grafana-runtime/src/services/appEvents.ts` | verified |  |
| grafana | `packages/grafana-test-utils/src/handlers/api/teams/handlers.ts` | verified |  |
| grafana | `packages/grafana-ui/src/utils/keyframes.ts` | verified |  |
| grafana | `pkg/registry/apis/secret/encryption/cipher/service/service_test.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/receiver_testing_svc.go` | verified |  |
| grafana | `pkg/setting/setting_azure_test.go` | verified |  |
| grafana | `pkg/storage/unified/resource/storage_backend_test.go` | verified |  |
| grafana | `pkg/tests/apis/folder/folder_tree_test.go` | verified |  |
| grafana | `pkg/tsdb/grafanads/query.go` | verified |  |
| grafana | `pkg/tsdb/influxdb/influxql/util/util_test.go` | verified |  |
| grafana | `pkg/util/xorm/table_name.go` | verified |  |
| grafana | `public/app/features/alerting/unified/rule-list/filter/useSavedSearches.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/Sidebar/Cards/CardTitle.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/TransformationEditorRenderer.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/layout-rows/RowsLayoutManager.tsx` | verified |  |
| grafana | `public/app/features/logs/components/panel/LogListContext.tsx` | verified |  |
| grafana | `public/app/features/serviceaccounts/ServiceAccountPermissions.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/LogsQueryBuilder/AggregationSection.tsx` | verified |  |
| grafana | `public/app/plugins/panel/nodeGraph/ViewControls.tsx` | verified |  |
| grafana | `public/app/plugins/panel/nodeGraph/layeredLayout.worker.js` | verified |  |
| grafana | `public/app/plugins/panel/state-timeline/styles.ts` | verified |  |
| grafana | `public/test/mocks/getGrafanaContextMock.ts` | verified |  |
| prysm | `beacon-chain/db/kv/migration_state_validators_test.go` | verified |  |
| prysm | `beacon-chain/rpc/metrics.go` | verified |  |
| prysm | `beacon-chain/rpc/prysm/v1alpha1/validator/status_test.go` | verified |  |
| prysm | `cmd/validator/accounts/import_test.go` | verified |  |
| prysm | `monitoring/clientstats/types.go` | verified |  |
| prysm | `testing/spectest/mainnet/bellatrix__epoch_processing__slashings_test.go` | verified |  |
| prysm | `testing/spectest/mainnet/electra__epoch_processing__pending_consolidations_test.go` | verified |  |
| prysm | `testing/spectest/shared/electra/operations/proposer_slashing.go` | verified |  |
| prysm | `testing/spectest/shared/electra/sanity/block_processing.yaml.go` | verified |  |
| prysm | `validator/helpers/metadata.go` | verified |  |
