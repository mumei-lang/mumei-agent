# Target OSS no-LLM dogfooding audit — continuation 269 (batch 270)

Run: 2026-07-22T15:58:12.681528+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/asm/internal/arch/arm.go` | verified |  |
| go | `src/cmd/compile/internal/syntax/issues_test.go` | verified |  |
| go | `src/crypto/internal/sysrand/rand_plan9.go` | verified |  |
| go | `src/crypto/x509/sec1.go` | verified |  |
| go | `src/internal/strconv/atoc.go` | verified |  |
| go | `src/internal/trace/traceviewer/mmu.go` | verified |  |
| go | `src/log/slog/example_level_handler_test.go` | verified |  |
| go | `src/net/iprawsock_plan9.go` | verified |  |
| go | `src/net/netip/slow_test.go` | verified |  |
| go | `src/runtime/libfuzzer.go` | verified |  |
| go | `src/runtime/mgcpacer_test.go` | verified |  |
| go | `test/fixedbugs/issue4313.go` | verified |  |
| go | `test/fixedbugs/issue56778.go` | verified |  |
| go | `test/typeparam/issue47514b.go` | verified |  |
| go | `test/typeparam/sliceimp.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/metrics.go` | verified |  |
| grafana | `packages/grafana-data/src/transformations/transformers/limit.ts` | verified |  |
| grafana | `packages/grafana-o11y-ds-frontend/src/pyroscope/types.ts` | verified |  |
| grafana | `packages/grafana-schema/src/raw/composable/candlestick/panelcfg/x/types.gen.ts` | verified |  |
| grafana | `packages/grafana-schema/src/schema/dashboard/v1beta1/types.status.gen.ts` | verified |  |
| grafana | `packages/grafana-sql/src/utils/testHelpers.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/FileDropzone/FileListItem.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/VizTooltip/utils.ts` | verified |  |
| grafana | `pkg/codegen/jenny_tsveneerindex.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/export/mock_export_fn.go` | verified |  |
| grafana | `pkg/registry/apps/playlist/accesscontrol.go` | verified |  |
| grafana | `pkg/services/accesscontrol/acimpl/zanzana_resolver.go` | verified |  |
| grafana | `pkg/services/accesscontrol/ossaccesscontrol/folder.go` | verified |  |
| grafana | `pkg/services/libraryelements/libraryelements_test.go` | verified |  |
| grafana | `pkg/services/publicdashboards/internal/api/api.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/apikey_mig.go` | verified |  |
| grafana | `pkg/tests/apis/helper.go` | verified |  |
| grafana | `public/app/features/alerting/unified/rule-editor/clone.utils.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/triage/instance-details/InstanceTimelineSection.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/inspect/InspectErrorsAndNoticesTab.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/mutation-api/commands/panelSerialization.ts` | verified |  |
| grafana | `public/app/features/dashboard/state/DashboardModel.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/language/metric-math/completion/suggestionKind.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/language/metric-math/definition.ts` | verified |  |
| prysm | `beacon-chain/blockchain/head_sync_committee_info.go` | verified |  |
| prysm | `beacon-chain/core/peerdas/validator_test.go` | verified |  |
| prysm | `beacon-chain/das/availability_columns.go` | verified |  |
| prysm | `beacon-chain/light-client/store.go` | verified |  |
| prysm | `beacon-chain/operations/synccommittee/message_test.go` | verified |  |
| prysm | `beacon-chain/p2p/gossip_scoring_params_test.go` | verified |  |
| prysm | `beacon-chain/rpc/eth/beacon/handlers_state_test.go` | verified |  |
| prysm | `beacon-chain/rpc/prysm/v1alpha1/validator/proposer_slashings_test.go` | verified |  |
| prysm | `beacon-chain/state/stateutil/proposer_lookahead_root_test.go` | verified |  |
| prysm | `cmd/beacon-chain/sync/checkpoint/options.go` | verified |  |
| prysm | `testing/spectest/shared/electra/operations/execution_payload.go` | verified |  |
