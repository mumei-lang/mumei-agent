# Target OSS no-LLM dogfooding audit — continuation 358 (batch 359)

Run: 2026-07-22T21:29:16.003412+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/test/issue27340.go` | verified |  |
| go | `src/compress/flate/flate_test.go` | verified |  |
| go | `src/go/types/trie_test.go` | verified |  |
| go | `src/image/png/example_test.go` | verified |  |
| go | `src/internal/runtime/maps/runtime_hash32.go` | verified |  |
| go | `src/math/rand/v2/export_test.go` | verified |  |
| go | `src/runtime/defs_dragonfly.go` | verified |  |
| go | `src/runtime/mem_wasip1.go` | verified |  |
| go | `test/fixedbugs/bug191.go` | verified |  |
| go | `test/fixedbugs/issue45503.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue6513.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue66575.go` | verified |  |
| go | `test/gc.go` | verified |  |
| grafana | `.github/actions/changelog/index.js` | verified |  |
| grafana | `apps/alerting/rules/pkg/app/validation/builder.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/conversion/v2alpha1_to_v1_test.go` | verified |  |
| grafana | `packages/grafana-alerting/src/grafana/api/notifications/v0alpha1/mocks/handlers/ReceiverHandlers/listReceiverHandler.ts` | verified |  |
| grafana | `packages/grafana-alerting/src/grafana/contactPoints/components/ContactPointSelector/ContactPointSelector.scenario.ts` | verified |  |
| grafana | `packages/grafana-api-clients/rollup.config.ts` | verified |  |
| grafana | `packages/grafana-runtime/src/services/user.ts` | verified |  |
| grafana | `packages/grafana-sql/src/components/QueryHeader.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Monaco/suggestions.ts` | verified |  |
| grafana | `pkg/plugins/manager/installer_test.go` | verified |  |
| grafana | `pkg/plugins/manager/loader/angular/angularinspector/angularinspector.go` | verified |  |
| grafana | `pkg/services/featuremgmt/usage_stats.go` | verified |  |
| grafana | `pkg/services/ngalert/backtesting/eval_data_test.go` | verified |  |
| grafana | `pkg/services/provisioning/alerting/types.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/accesscontrol/alerting.go` | verified |  |
| grafana | `pkg/services/stats/models.go` | verified |  |
| grafana | `pkg/util/scheduler/queue.go` | verified |  |
| grafana | `public/app/features/alerting/unified/NewSilencePage.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/import-to-gma/ImportToGMARules.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/labels/LabelsButtons.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/query-and-alert-condition/QueryAndExpressionsStep.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/mutation-api/commands/getSpec.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/layout-rows/RowsLayoutManagerRenderer.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/serialization/const.ts` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/CriticalPath/testCases/test3.ts` | verified |  |
| grafana | `public/app/features/provisioning/mocks/server/index.ts` | verified |  |
| grafana | `public/test/jest-setup.ts` | verified |  |
| prysm | `beacon-chain/core/helpers/validator_churn_test.go` | verified |  |
| prysm | `beacon-chain/db/kv/backfill.go` | verified |  |
| prysm | `beacon-chain/execution/service_test.go` | verified |  |
| prysm | `beacon-chain/rpc/prysm/v1alpha1/validator/proposer_bellatrix.go` | verified |  |
| prysm | `beacon-chain/state/state-native/getters_consolidation.go` | verified |  |
| prysm | `beacon-chain/sync/validate_proposer_slashing_test.go` | verified |  |
| prysm | `cmd/completion_test.go` | verified |  |
| prysm | `config/features/deprecated_flags_test.go` | verified |  |
| prysm | `testing/util/lightclient.go` | verified |  |
| prysm | `validator/db/kv/graffiti_test.go` | verified |  |
