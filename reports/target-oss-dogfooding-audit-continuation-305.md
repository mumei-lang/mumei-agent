# Target OSS no-LLM dogfooding audit — continuation 305 (batch 306)

Run: 2026-07-22T18:32:33.731451+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/go/internal/load/path.go` | verified |  |
| go | `src/cmd/internal/telemetry/counter/counter_bootstrap.go` | verified |  |
| go | `src/go/types/format.go` | verified |  |
| go | `src/go/types/methodset_test.go` | verified |  |
| go | `src/internal/routebsd/message.go` | verified |  |
| go | `src/internal/trace/testtrace/format.go` | verified |  |
| go | `src/net/http/cgi/child_test.go` | verified |  |
| go | `src/regexp/syntax/perl_groups.go` | verified |  |
| go | `src/runtime/tracetime.go` | verified |  |
| go | `src/simd/internal/bridge/tofrom_128.go` | verified |  |
| go | `src/syscall/syscall_linux_riscv64.go` | verified |  |
| go | `src/syscall/types_openbsd.go` | verified |  |
| go | `test/eof1.go` | verified |  |
| go | `test/fixedbugs/bug140.go` | verified |  |
| go | `test/fixedbugs/bug191.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue43677.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v1beta1/routingtree_spec_gen.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/utils.go` | verified |  |
| grafana | `packages/grafana-alerting/src/grafana/api/notifications/v0alpha1/mocks/handlers/ReceiverHandlers/deleteReceiverHandler.ts` | verified |  |
| grafana | `packages/grafana-data/src/transformations/transformers/joinByField.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/VizTooltip/VizTooltipContent.tsx` | verified |  |
| grafana | `pkg/api/folder_permission.go` | verified |  |
| grafana | `pkg/api/response/response_test.go` | verified |  |
| grafana | `pkg/expr/threshold.go` | verified |  |
| grafana | `pkg/registry/apis/datasource/migration_registrar.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/sync/incremental.go` | verified |  |
| grafana | `pkg/services/cleanup/cleanup.go` | verified |  |
| grafana | `pkg/services/cloudmigration/resource_dependency_test.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/org_email_validator.go` | verified |  |
| grafana | `pkg/services/ngalert/provisioning/validation/errors.go` | verified |  |
| grafana | `pkg/services/ngalert/state/historian/testing.go` | verified |  |
| grafana | `pkg/storage/legacysql/dualwrite/mock.go` | verified |  |
| grafana | `pkg/storage/unified/search/embed/reconciler/reconciler_test.go` | verified |  |
| grafana | `pkg/tests/apis/iam/user/user_teams_search_integration_test.go` | verified |  |
| grafana | `pkg/tsdb/influxdb/mocks_test.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rules/deleted-rules/DeletedRulesPage.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/insights/grafana/EvalSuccessVsFailuresScene.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/sharing/ShareButton/share-externally/EmailShare/EmailSharing.tsx` | verified |  |
| grafana | `public/app/features/plugins/admin/helpers.ts` | verified |  |
| grafana | `public/app/plugins/datasource/influxdb/influxql_metadata_query.ts` | verified |  |
| prysm | `beacon-chain/core/helpers/legacy_test.go` | verified |  |
| prysm | `beacon-chain/forkchoice/doubly-linked-tree/on_tick_test.go` | verified |  |
| prysm | `beacon-chain/rpc/testutil/mock_blocker.go` | verified |  |
| prysm | `beacon-chain/state/state-native/getters_validator_test.go` | verified |  |
| prysm | `beacon-chain/state/stateutil/compact_validator_test.go` | verified |  |
| prysm | `testing/spectest/mainnet/electra__forkchoice__forkchoice_test.go` | verified |  |
| prysm | `testing/spectest/mainnet/phase0__operations__proposer_slashing_test.go` | verified |  |
| prysm | `testing/spectest/minimal/fulu__ssz_static__ssz_static_test.go` | verified |  |
| prysm | `testing/spectest/shared/electra/operations/bls_to_execution_changes.go` | verified |  |
| prysm | `time/slots/slottime.go` | verified |  |
