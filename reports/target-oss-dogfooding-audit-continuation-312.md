# Target OSS no-LLM dogfooding audit — continuation 312 (batch 313)

Run: 2026-07-22T18:51:40.239322+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/asm/internal/lex/input.go` | verified |  |
| go | `src/cmd/go/internal/lockedfile/lockedfile_test.go` | verified |  |
| go | `src/crypto/internal/fips140deps/cpu/cpu.go` | verified |  |
| go | `src/debug/pe/file_cgo_test.go` | verified |  |
| go | `src/net/url/gen_encoding_table.go` | verified |  |
| go | `src/runtime/badlinkname_linux.go` | verified |  |
| go | `src/runtime/extern.go` | verified |  |
| go | `src/runtime/lockrank.go` | verified |  |
| go | `src/runtime/mcentral.go` | verified |  |
| go | `src/runtime/semasleep_test.go` | verified |  |
| go | `test/fixedbugs/issue11326.go` | verified |  |
| go | `test/fixedbugs/issue11369.go` | verified |  |
| go | `test/fixedbugs/issue55122.go` | verified |  |
| go | `test/fixedbugs/issue7023.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue78599.go` | verified |  |
| grafana | `apps/logsdrilldown/plugin/src/generated/logsdrilldown/v1alpha1/types.status.gen.ts` | verified |  |
| grafana | `packages/grafana-data/src/transformations/transformers/transpose.ts` | verified |  |
| grafana | `packages/grafana-data/src/utils/tests/mockStandardProperties.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/DataSourceSettings/HttpProxySettings.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/InputControl.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/TableNG/components/RowExpander.tsx` | verified |  |
| grafana | `pkg/infra/remotecache/remotecache_test.go` | verified |  |
| grafana | `pkg/services/ngalert/api/prometheus/api_prometheus.go` | verified |  |
| grafana | `pkg/services/queryhistory/queryhistory_star_test.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/plugin_setting.go` | verified |  |
| grafana | `public/app/core/components/Layers/types.ts` | verified |  |
| grafana | `public/app/core/services/meticulous.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/receivers/form/notifiers.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-viewer/RuleViewerLayout.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/triage/hooks/useApplyDefaultTriageSearch.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/Header/SaveButton.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/useScrollReflowLimit.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/annotations/AnnotationBasicOptions.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/sharing/ShareDrawer/ShareDrawerContext.tsx` | verified |  |
| grafana | `public/app/features/dashboard/containers/types.ts` | verified |  |
| grafana | `public/app/features/datasources/components/DataSourceTabPage.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/demo/trace-generators.ts` | verified |  |
| grafana | `public/app/features/playlist/PlaylistNewPage.tsx` | verified |  |
| grafana | `public/app/features/variables/editor/LegacyVariableQueryEditor.tsx` | verified |  |
| prysm | `api/apiutil/header_test.go` | verified |  |
| prysm | `beacon-chain/blockchain/kzg/validation_test.go` | verified |  |
| prysm | `beacon-chain/cache/attestation.go` | verified |  |
| prysm | `beacon-chain/rpc/eth/rewards/service.go` | verified |  |
| prysm | `beacon-chain/rpc/prysm/v1alpha1/validator/blocks_test.go` | verified |  |
| prysm | `beacon-chain/sync/subscriber_handlers.go` | verified |  |
| prysm | `cmd/prysmctl/p2p/log.go` | verified |  |
| prysm | `proto/engine/v1/json_marshal_unmarshal_test.go` | verified |  |
| prysm | `testing/slasher/simulator/block_generator.go` | verified |  |
| prysm | `testing/spectest/mainnet/capella__random__random_test.go` | verified |  |
| prysm | `validator/db/kv/migration.go` | verified |  |
