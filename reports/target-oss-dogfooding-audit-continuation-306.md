# Target OSS no-LLM dogfooding audit — continuation 306 (batch 307)

Run: 2026-07-22T18:35:10.355394+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/test/issue27054/test27054.go` | verified |  |
| go | `src/cmd/compile/internal/types2/self_test.go` | verified |  |
| go | `src/crypto/internal/fips140/drbg/ctrdrbg.go` | verified |  |
| go | `src/internal/dag/alg.go` | verified |  |
| go | `src/io/fs/format_test.go` | verified |  |
| go | `src/math/cmplx/sqrt.go` | verified |  |
| go | `src/net/http/internal/chunked.go` | verified |  |
| go | `src/net/sockaddr_posix.go` | verified |  |
| go | `src/runtime/race/internal/amd64v1/doc.go` | verified |  |
| go | `src/runtime/timeasm.go` | verified |  |
| go | `test/fixedbugs/issue15042.go` | verified |  |
| go | `test/fixedbugs/issue40629.go` | verified |  |
| go | `test/fixedbugs/issue67190.go` | verified |  |
| go | `test/nilptr5_aix.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v0alpha1/timeinterval_object_gen.go` | verified |  |
| grafana | `apps/alerting/rules/pkg/app/util/group_validation_test.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v15.go` | verified |  |
| grafana | `packages/grafana-sql/src/components/QueryEditorLazy.tsx` | verified |  |
| grafana | `pkg/api/dashboard.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/register_authz_test.go` | verified |  |
| grafana | `pkg/registry/apps/playlist/migrator/migrator_test.go` | verified |  |
| grafana | `pkg/server/operator.go` | verified |  |
| grafana | `pkg/services/accesscontrol/metadata.go` | verified |  |
| grafana | `pkg/services/folder/foldertest/foldertest.go` | verified |  |
| grafana | `pkg/services/libraryelements/libraryelements_patch_test.go` | verified |  |
| grafana | `pkg/services/secrets/database/database.go` | verified |  |
| grafana | `pkg/services/supportbundles/supportbundlesimpl/db_collector.go` | verified |  |
| grafana | `pkg/storage/unified/resource/last_import_time_store.go` | verified |  |
| grafana | `pkg/storage/unified/sql/db/dbimpl/dbimpl.go` | verified |  |
| grafana | `pkg/tsdb/azuremonitor/resourcegraph/azure-resource-graph-datasource.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/models/resources/metrics_resource_request_test.go` | verified |  |
| grafana | `public/app/core/components/NativeScrollbar.tsx` | verified |  |
| grafana | `public/app/features/alerting/routes.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/api/alertSilencesApi.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/notifications/NotificationDetailHeader.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/variables/components/GroupByVariableForm.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/utils/collectAncestorSceneVariables.ts` | verified |  |
| grafana | `public/app/features/gops/configuration-tracker/alerting/utils.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/components/VariableQueryEditor/VariableQueryEditor.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/components/shared/DataSources/SelectedDataSources.tsx` | verified |  |
| prysm | `beacon-chain/core/blocks/eth1_data.go` | verified |  |
| prysm | `beacon-chain/core/epoch/precompute/attestation.go` | verified |  |
| prysm | `beacon-chain/core/signing/domain.go` | verified |  |
| prysm | `beacon-chain/db/kv/state_summary.go` | verified |  |
| prysm | `testing/spectest/mainnet/capella__operations__sync_committee_test.go` | verified |  |
| prysm | `testing/spectest/minimal/capella__fork__upgrade_to_capella_test.go` | verified |  |
| prysm | `testing/spectest/minimal/gloas__epoch_processing__inactivity_updates_test.go` | verified |  |
| prysm | `tools/gocovmerge/main.go` | verified |  |
| prysm | `validator/client/wait_for_activation.go` | verified |  |
| prysm | `validator/slashing-protection-history/format/format.go` | verified |  |
