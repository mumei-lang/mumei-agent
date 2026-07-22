# Target OSS no-LLM dogfooding audit — continuation 313 (batch 314)

Run: 2026-07-22T18:54:18.571399+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/go/internal/load/printer.go` | verified |  |
| go | `src/crypto/internal/fips140/aes/aes_generic.go` | verified |  |
| go | `src/encoding/json/v2_scanner_test.go` | verified |  |
| go | `src/go/ast/commentmap.go` | verified |  |
| go | `src/mime/multipart/multipart_test.go` | verified |  |
| go | `src/os/dirent_openbsd.go` | verified |  |
| go | `src/runtime/set_vma_name_linux.go` | verified |  |
| go | `src/syscall/types_illumos_amd64.go` | verified |  |
| go | `src/text/scanner/scanner_test.go` | verified |  |
| go | `test/fixedbugs/bug371.go` | verified |  |
| go | `test/fixedbugs/bug480.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue4663.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/externalgroupmapping_schema_gen.go` | verified |  |
| grafana | `pkg/apis/service/v0alpha1/types.go` | verified |  |
| grafana | `pkg/registry/apis/folders/cascade_delete_test.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/expired_job_cleanup_test.go` | verified |  |
| grafana | `pkg/services/apiserver/auth/authorizer/role.go` | verified |  |
| grafana | `pkg/services/cloudmigration/cloudmigrationimpl/xorm_store_test.go` | verified |  |
| grafana | `pkg/services/featuremgmt/openfeature.go` | verified |  |
| grafana | `pkg/services/ngalert/api/tooling/definitions/admin.go` | verified |  |
| grafana | `pkg/setting/setting_smtp_test.go` | verified |  |
| grafana | `pkg/setting/setting_unified_storage.go` | verified |  |
| grafana | `pkg/storage/secret/metadata/metrics/metrics.go` | verified |  |
| grafana | `pkg/storage/unified/migrations/service.go` | verified |  |
| grafana | `pkg/storage/unified/resourcepb/blob_grpc.pb.go` | verified |  |
| grafana | `pkg/storage/unified/search/builders/alertingrules_test.go` | verified |  |
| grafana | `pkg/tests/api/correlations/correlations_create_test.go` | verified |  |
| grafana | `pkg/tests/apis/preferences/legacy_preferences_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/git/folder_file_rejection_test.go` | verified |  |
| grafana | `pkg/tsdb/loki/frame_test.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/GrafanaAlertStatePicker.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/reducers/alertmanager/notificationTemplates.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/rule-editor/ExistingRuleEditor.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/triage/instance-details/InstanceDetailsDrawerTitle.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/variables/editors/CustomVariableEditor/ModalEditor.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/utils/getVariablesCompatibility.ts` | verified |  |
| grafana | `public/app/features/dashboard/state/getPanelPluginToMigrateTo.ts` | verified |  |
| grafana | `public/app/features/expressions/components/SqlExpressions/CompletionProvider/sqlCompletionProvider.ts` | verified |  |
| grafana | `public/app/features/provisioning/Shared/CommitSigningInfo.tsx` | verified |  |
| prysm | `api/client/builder/types_test.go` | verified |  |
| prysm | `beacon-chain/cache/doc.go` | verified |  |
| prysm | `beacon-chain/core/altair/block_test.go` | verified |  |
| prysm | `beacon-chain/core/peerdas/p2p_interface_test.go` | verified |  |
| prysm | `beacon-chain/db/kv/custody.go` | verified |  |
| prysm | `beacon-chain/state/stateutil/unrealized_justification_test.go` | verified |  |
| prysm | `beacon-chain/sync/initial-sync/blocks_fetcher.go` | verified |  |
| prysm | `consensus-types/interfaces/light_client.go` | verified |  |
| prysm | `contracts/deposit/contract.go` | verified |  |
| prysm | `testing/spectest/minimal/electra__operations__deposit_test.go` | verified |  |
| prysm | `testing/spectest/shared/altair/epoch_processing/rewards_and_penalties.go` | verified |  |
