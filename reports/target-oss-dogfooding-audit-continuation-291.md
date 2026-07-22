# Target OSS no-LLM dogfooding audit — continuation 291 (batch 292)

Run: 2026-07-22T17:29:55.343402+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/test/sigaltstack.go` | verified |  |
| go | `src/cmd/compile/internal/ir/scc.go` | verified |  |
| go | `src/cmd/internal/obj/riscv/obj_test.go` | verified |  |
| go | `src/cmd/internal/obj/s390x/condition_code.go` | verified |  |
| go | `src/cmd/link/internal/ld/macho_update_uuid.go` | verified |  |
| go | `src/database/sql/convert_test.go` | verified |  |
| go | `src/internal/goarch/goarch_ppc64le.go` | verified |  |
| go | `src/internal/sync/hashtriemap.go` | verified |  |
| go | `src/log/slog/example_multi_handler_test.go` | verified |  |
| go | `src/syscall/fs_js.go` | verified |  |
| go | `src/syscall/zsysnum_linux_loong64.go` | verified |  |
| go | `src/time/genzabbrs.go` | verified |  |
| go | `test/fixedbugs/issue15838.go` | verified |  |
| go | `test/fixedbugs/issue77635.go` | verified |  |
| go | `test/fixedbugs/issue9521.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/app/config.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v2.go` | verified |  |
| grafana | `apps/provisioning/pkg/apis/apifmt/error.go` | verified |  |
| grafana | `packages/grafana-schema/rollup.config.ts` | verified |  |
| grafana | `pkg/api/pluginproxy/utils.go` | verified |  |
| grafana | `pkg/apiserver/registry/generic/storage.go` | verified |  |
| grafana | `pkg/plugins/manager/pipeline/termination/steps.go` | verified |  |
| grafana | `pkg/registry/apis/iam/sso/mtsettings_store.go` | verified |  |
| grafana | `pkg/services/folder/store.go` | verified |  |
| grafana | `pkg/services/login/authinfoimpl/store.go` | verified |  |
| grafana | `pkg/services/ngalert/models/instance.go` | verified |  |
| grafana | `pkg/services/ngalert/prom/models_test.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/accesscontrol/disabled_migration.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/dashboard_acl.go` | verified |  |
| grafana | `pkg/util/retryer/retryer_test.go` | verified |  |
| grafana | `public/app/features/alerting/state/query_part.ts` | verified |  |
| grafana | `public/app/features/plugins/admin/components/PluginListItem.tsx` | verified |  |
| grafana | `public/app/features/scopes/dashboards/ScopesDashboardsTreeFolderItem.tsx` | verified |  |
| grafana | `public/app/features/stars/analytics/types.ts` | verified |  |
| grafana | `public/app/features/teams/create-team/CreateTeamAPICalls.tsx` | verified |  |
| grafana | `public/app/features/transformers/regression/regressionEditor.tsx` | verified |  |
| grafana | `public/app/features/variables/inspect/reducer.ts` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/LogsQueryEditor/LogsQueryEditor.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/mocks/cloudwatch-logs-test-data/singleLineFullQuery.ts` | verified |  |
| grafana | `public/app/plugins/panel/logstable/LogDetailsContext.tsx` | verified |  |
| prysm | `beacon-chain/blockchain/mock_test.go` | verified |  |
| prysm | `beacon-chain/monitor/service_test.go` | verified |  |
| prysm | `beacon-chain/operations/blstoexec/pool_test.go` | verified |  |
| prysm | `beacon-chain/rpc/prysm/v1alpha1/beacon/committees_test.go` | verified |  |
| prysm | `beacon-chain/sync/initial-sync/blocks_fetcher_test.go` | verified |  |
| prysm | `testing/spectest/minimal/altair__operations__attester_slashing_test.go` | verified |  |
| prysm | `testing/spectest/minimal/phase0__epoch_processing__epoch_processing_test.go` | verified |  |
| prysm | `testing/spectest/shared/bellatrix/fork/transition.go` | verified |  |
| prysm | `testing/spectest/shared/gloas/operations/consolidations.go` | verified |  |
| prysm | `tools/analyzers/comparesame/analyzer_test.go` | verified |  |
