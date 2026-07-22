# Target OSS no-LLM dogfooding audit — continuation 341 (batch 342)

Run: 2026-07-22T20:47:27.595405+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/container/heap/heap_test.go` | verified |  |
| go | `src/os/stat_unix.go` | verified |  |
| go | `test/codegen/copy.go` | verified |  |
| go | `test/deferprint.go` | verified |  |
| go | `test/fixedbugs/bug317.go` | verified |  |
| go | `test/fixedbugs/bug336.go` | verified |  |
| go | `test/fixedbugs/issue15071.dir/exp.go` | verified |  |
| go | `test/fixedbugs/issue24651a.go` | verified |  |
| go | `test/fixedbugs/issue29870b.go` | verified |  |
| go | `test/fixedbugs/issue58572.go` | verified |  |
| go | `test/fixedbugs/issue8280.dir/a.go` | verified |  |
| go | `test/ken/cplx2.go` | verified |  |
| go | `test/linkname.dir/linkname2.go` | verified |  |
| go | `test/typeparam/issue54135.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/migrations.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/role_client_gen.go` | verified |  |
| grafana | `apps/plugins/pkg/app/meta/manager_test.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/applyconfiguration/provisioning/v0alpha1/connectionsecure.go` | verified |  |
| grafana | `packages/grafana-ui/src/components/ContextMenu/ContextMenuStoryHelper.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/RefreshPicker/RefreshPicker.tsx` | verified |  |
| grafana | `pkg/apimachinery/errutil/status.go` | verified |  |
| grafana | `pkg/expr/sql/frame_table.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/resources/object.go` | verified |  |
| grafana | `pkg/registry/apps/alerting/notifications/receiver/subresource_test.go` | verified |  |
| grafana | `pkg/registry/apps/annotation/grpc_store.go` | verified |  |
| grafana | `pkg/services/apiserver/builder/scheme.go` | verified |  |
| grafana | `pkg/services/folder/model_test.go` | verified |  |
| grafana | `pkg/services/live/telemetry/converter.go` | verified |  |
| grafana | `pkg/storage/unified/resource/search_client_test.go` | verified |  |
| grafana | `pkg/storage/unified/search/embed/embedder/vertex/embed_dense.go` | verified |  |
| grafana | `pkg/storage/unified/sql/db/otel/otel.go` | verified |  |
| grafana | `pkg/tests/apis/plugins/metas_test.go` | verified |  |
| grafana | `public/app/core/components/Page/types.ts` | verified |  |
| grafana | `public/app/core/services/context_srv.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/utils/settings.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/NewAlertRuleDrawer.tsx` | verified |  |
| grafana | `public/app/features/dashboard/dashgrid/DashboardLibrary/hooks/useTemplateDashboardsAvailability.ts` | verified |  |
| grafana | `public/app/features/plugins/pluginPreloader.ts` | verified |  |
| grafana | `public/app/features/variables/switch/SwitchVariablePicker.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/components/VariableQueryEditor/VariableTextField.tsx` | verified |  |
| prysm | `beacon-chain/p2p/utils_test.go` | verified |  |
| prysm | `beacon-chain/rpc/eth/beacon/handlers_equivocation_test.go` | verified |  |
| prysm | `beacon-chain/rpc/lookup/stater_test.go` | verified |  |
| prysm | `beacon-chain/state/stategen/init_test.go` | verified |  |
| prysm | `beacon-chain/sync/backfill/log_test.go` | verified |  |
| prysm | `beacon-chain/sync/initial-sync/log.go` | verified |  |
| prysm | `internal/logrusadapter/log.go` | verified |  |
| prysm | `testing/endtoend/evaluators/finality.go` | verified |  |
| prysm | `testing/spectest/minimal/altair__ssz_static__ssz_static_test.go` | verified |  |
| prysm | `testing/spectest/shared/gloas/epoch_processing/effective_balance_updates.go` | verified |  |
