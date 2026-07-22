# Target OSS no-LLM dogfooding audit — continuation 280 (batch 281)

Run: 2026-07-22T16:49:30.347556+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/rttype/rttype.go` | verified |  |
| go | `src/cmd/compile/internal/walk/temp.go` | verified |  |
| go | `src/cmd/trace/viewer.go` | verified |  |
| go | `src/crypto/rsa/pss_test.go` | verified |  |
| go | `src/encoding/json/jsontext/decode_test.go` | verified |  |
| go | `src/internal/abi/abi_amd64.go` | verified |  |
| go | `src/internal/sysinfo/sysinfo_test.go` | verified |  |
| go | `src/math/big/internal/asmgen/main_test.go` | verified |  |
| go | `src/net/http/internal/common.go` | verified |  |
| go | `src/runtime/gomaxprocs_windows_test.go` | verified |  |
| go | `src/strings/clone.go` | verified |  |
| go | `test/fixedbugs/bug385_32.go` | verified |  |
| go | `test/fixedbugs/issue14725.go` | verified |  |
| go | `test/fixedbugs/issue42790.go` | verified |  |
| grafana | `apps/live/pkg/apis/live/v1alpha1/channel_client_gen.go` | verified |  |
| grafana | `packages/grafana-data/src/monaco/languageRegistry.ts` | verified |  |
| grafana | `packages/grafana-runtime/src/services/pluginMeta/test-fixtures/v0alpha1Response.ts` | verified |  |
| grafana | `pkg/api/pluginproxy/settings.go` | verified |  |
| grafana | `pkg/registry/apps/alerting/notifications/receiver/subresource.go` | verified |  |
| grafana | `pkg/registry/apps/live/register.go` | verified |  |
| grafana | `pkg/services/accesscontrol/checker_test.go` | verified |  |
| grafana | `pkg/services/dashboards/dashboard_service_mock.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/pluginsso/pluginsso.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrator/column.go` | verified |  |
| grafana | `pkg/storage/unified/apistore/watcher_test.go` | verified |  |
| grafana | `pkg/storage/unified/sql/bulk_test.go` | verified |  |
| grafana | `pkg/tests/apis/iam/resourcepermission/resourcepermission_test.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/log_anomalies_query_test.go` | verified |  |
| grafana | `pkg/util/xorm/engine.go` | verified |  |
| grafana | `public/app/features/alerting/unified/mocks/grafanaRulerApi.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/mocks/server/handlers/folders.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelDataPane/utils.ts` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/TracePageHeader/SpanGraph/TickLabels.tsx` | verified |  |
| grafana | `public/app/features/explore/hooks/useStateSync/migrators/types.ts` | verified |  |
| grafana | `public/app/features/plugins/extensions/registry/ExposedComponentsRegistry.ts` | verified |  |
| grafana | `public/app/features/query/state/DashboardQueryRunner/utils.ts` | verified |  |
| grafana | `public/app/features/scopes/tests/utils/render.tsx` | verified |  |
| grafana | `public/app/features/transformers/suggestionsInput/SuggestionsInput.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/mocks/timeRange.ts` | verified |  |
| grafana | `public/app/plugins/datasource/graphite/gfunc.ts` | verified |  |
| prysm | `beacon-chain/blockchain/currently_syncing_block.go` | verified |  |
| prysm | `beacon-chain/core/blocks/withdrawals.go` | verified |  |
| prysm | `beacon-chain/operations/attestations/kv/forkchoice_test.go` | verified |  |
| prysm | `beacon-chain/p2p/peers/scorers/block_providers_test.go` | verified |  |
| prysm | `crypto/bls/blst/signature_test.go` | verified |  |
| prysm | `encoding/ssz/query/list.go` | verified |  |
| prysm | `proto/prysm/v1alpha1/gloas.ssz.go` | verified |  |
| prysm | `testing/spectest/mainnet/fulu__operations__voluntary_exit_test.go` | verified |  |
| prysm | `testing/spectest/minimal/capella__epoch_processing__registry_updates_test.go` | verified |  |
| prysm | `testing/spectest/minimal/fulu__epoch_processing__randao_mixes_reset_test.go` | verified |  |
