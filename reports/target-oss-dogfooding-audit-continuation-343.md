# Target OSS no-LLM dogfooding audit — continuation 343 (batch 344)

Run: 2026-07-22T20:51:20.439463+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/midway/midway.go` | verified |  |
| go | `src/cmd/internal/pgo/deserialize.go` | verified |  |
| go | `src/cmd/link/internal/ld/macho_test.go` | verified |  |
| go | `src/crypto/dsa/dsa_wycheproof_test.go` | verified |  |
| go | `src/crypto/sha3/sha3_test.go` | verified |  |
| go | `src/crypto/tls/handshake_client_test.go` | verified |  |
| go | `src/go/ast/import_test.go` | verified |  |
| go | `src/internal/goarch/goarch_386.go` | verified |  |
| go | `src/internal/routebsd/sys_darwin.go` | verified |  |
| go | `src/runtime/rdebug.go` | verified |  |
| go | `test/fixedbugs/bug349.go` | verified |  |
| go | `test/fixedbugs/issue49005a.go` | verified |  |
| go | `test/typeparam/sets.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v18.go` | verified |  |
| grafana | `apps/preferences/pkg/apis/preferences/v1/preferences_object_gen.go` | verified |  |
| grafana | `apps/preferences/pkg/apis/preferences/v1/zz_generated.defaults.go` | verified |  |
| grafana | `packages/grafana-plugin-configs/constants.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Forms/Legacy/Select/Select.tsx` | verified |  |
| grafana | `pkg/registry/apis/secret/service/secure_value.go` | verified |  |
| grafana | `pkg/server/doc.go` | verified |  |
| grafana | `pkg/services/accesscontrol/dualwrite/collectors_test.go` | verified |  |
| grafana | `pkg/services/accesscontrol/models.go` | verified |  |
| grafana | `pkg/services/live/pipeline/frame_output_changelog_test.go` | verified |  |
| grafana | `pkg/services/ngalert/accesscontrol/fakes/routes.go` | verified |  |
| grafana | `pkg/services/ngalert/api/ruler_history.go` | verified |  |
| grafana | `pkg/services/queryhistory/queryhistory_search_test.go` | verified |  |
| grafana | `pkg/tests/api/publicdashboards/public_dashboard_query_test.go` | verified |  |
| grafana | `pkg/tsdb/azuremonitor/schema_test.go` | verified |  |
| grafana | `pkg/tsdb/sqlmacro/sqlmacro.go` | verified |  |
| grafana | `public/app/core/services/FetchQueue.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/api/timeIntervalsApi.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rules/state-history/LogTimelineViewer.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/VizAndDataPaneNext.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/DashboardMutationClientSetter.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/variables/VariableEditorForm.tsx` | verified |  |
| grafana | `public/app/features/home/AlertsIncidents/FiringAlertsCard.tsx` | verified |  |
| grafana | `public/app/features/transformers/prepareTimeSeries/prepareTimeSeries.ts` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/TracesQueryEditor/Filters.tsx` | verified |  |
| grafana | `public/test/core/thunk/thunkTester.ts` | verified |  |
| grafana | `scripts/codeowners-manifest/metadata.js` | verified |  |
| prysm | `beacon-chain/core/altair/upgrade.go` | verified |  |
| prysm | `beacon-chain/db/kv/lightclient_test.go` | verified |  |
| prysm | `beacon-chain/rpc/eth/validator/handlers.go` | verified |  |
| prysm | `beacon-chain/state/stategen/service.go` | verified |  |
| prysm | `beacon-chain/state/stateutil/state_root_test.go` | verified |  |
| prysm | `beacon-chain/sync/initial-sync/blocks_queue_utils.go` | verified |  |
| prysm | `testing/spectest/minimal/deneb__operations__bls_to_execution_change_test.go` | verified |  |
| prysm | `testing/spectest/minimal/electra__epoch_processing__slashings_test.go` | verified |  |
| prysm | `testing/spectest/shared/deneb/sanity/slot_processing.go` | verified |  |
| prysm | `testing/spectest/shared/electra/epoch_processing/effective_balance_updates.go` | verified |  |
