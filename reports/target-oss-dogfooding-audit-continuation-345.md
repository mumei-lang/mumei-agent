# Target OSS no-LLM dogfooding audit — continuation 345 (batch 346)

Run: 2026-07-22T20:55:04.951442+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/test/issue8148.go` | verified |  |
| go | `src/cmd/go/internal/fmtcmd/fmt.go` | verified |  |
| go | `src/cmd/link/internal/ld/stackcheck_test.go` | verified |  |
| go | `src/os/exec_nohandle.go` | verified |  |
| go | `src/os/zero_copy_solaris.go` | verified |  |
| go | `src/runtime/map.go` | verified |  |
| go | `src/simd/archsimd/_gen/unify/closure.go` | verified |  |
| go | `src/simd/archsimd/_gen/unify/dot.go` | verified |  |
| go | `src/testing/cryptotest/rand.go` | verified |  |
| go | `test/atomicload.go` | verified |  |
| go | `test/fixedbugs/bug169.go` | verified |  |
| go | `test/fixedbugs/issue39651.go` | verified |  |
| go | `test/typeparam/interfacearg.go` | verified |  |
| grafana | `apps/secret/pkg/apis/secret/v1beta1/securevalue_client_gen.go` | verified |  |
| grafana | `e2e-playwright/test-plugins/grafana-extensionstest-app/pages/AddedLinks.tsx` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/user/endpoints.gen.ts` | verified |  |
| grafana | `packages/grafana-schema/src/raw/composable/statushistory/panelcfg/x/types.gen.ts` | verified |  |
| grafana | `packages/grafana-ui/src/themes/selectThemeVariant.ts` | verified |  |
| grafana | `pkg/expr/sql_schema.go` | verified |  |
| grafana | `pkg/plugins/backendplugin/grpcplugin/client_proto.go` | verified |  |
| grafana | `pkg/plugins/pluginassets/localprovider.go` | verified |  |
| grafana | `pkg/registry/apis/collections/legacy/queries.go` | verified |  |
| grafana | `pkg/registry/apis/secret/testutils/noop_migration_executor.go` | verified |  |
| grafana | `pkg/registry/apis/userstorage/strategy.go` | verified |  |
| grafana | `pkg/services/ngalert/state/persister_async.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/clientmiddleware/metrics_middleware_test.go` | verified |  |
| grafana | `pkg/services/star/api/api.go` | verified |  |
| grafana | `pkg/storage/unified/resource/bleve_index_metrics.go` | verified |  |
| grafana | `pkg/storage/unified/resource/search_client.go` | verified |  |
| grafana | `pkg/storage/unified/resource/table_test.go` | verified |  |
| grafana | `public/app/core/components/AppChrome/TopBar/InviteUserButton.tsx` | verified |  |
| grafana | `public/app/features/admin/UserListPage.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/api/backtestApi.ts` | verified |  |
| grafana | `public/app/features/browse-dashboards/fixtures/state.fixtures.ts` | verified |  |
| grafana | `public/app/features/migrate-to-cloud/cloud/EmptyState/InfoPane.tsx` | verified |  |
| grafana | `public/app/features/provisioning/utils/markdownLinks.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/language/cloudwatch-sql/completion/suggestionKind.ts` | verified |  |
| grafana | `public/app/plugins/datasource/graphite/webpack.config.ts` | verified |  |
| grafana | `public/app/plugins/panel/timeseries/plugins/annotations/types.ts` | verified |  |
| grafana | `scripts/compare-coverage-by-codeowner.js` | verified |  |
| prysm | `api/server/middleware/middleware.go` | verified |  |
| prysm | `beacon-chain/blockchain/setup_forkchoice.go` | verified |  |
| prysm | `beacon-chain/core/epoch/precompute/justification_finalization_test.go` | verified |  |
| prysm | `beacon-chain/execution/graffiti_info_test.go` | verified |  |
| prysm | `beacon-chain/operations/voluntaryexits/mock/mock.go` | verified |  |
| prysm | `cmd/prysmctl/weaksubjectivity/cmd.go` | verified |  |
| prysm | `cmd/validator/usage_test.go` | verified |  |
| prysm | `config/features/filter_flags.go` | verified |  |
| prysm | `config/fieldparams/minimal_test.go` | verified |  |
| prysm | `testing/spectest/mainnet/deneb__sanity__blocks_test.go` | verified |  |
