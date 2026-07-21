# Target OSS no-LLM dogfooding audit — continuation 84 (batch 85)

Run: 2026-07-21T22:44:35.124045+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification after fixing `uniswap-contracts/lib/oz-v4.7.0/contracts/governance/Governor.sol` (`bytes memory` return mapped to Mumei `string`).

## Tool-side fixes in this batch

- `_foreign_signature_type` maps Solidity `bytes` (dynamic byte array) to the Mumei `string` type so empty string return literals can be lowered.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `test/fixedbugs/issue37975.go` | verified |  |
| grafana | `pkg/generated/clientset/versioned/fake/register.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/permit2/interfaces/ISignatureTransfer.sol` | verified |  |
| influxdb | `influxdb3_catalog/src/catalog/versions/v1.rs` | verified |  |
| go | `src/runtime/pprof/rusage_test.go` | verified |  |
| go | `src/runtime/debug/mod_test.go` | verified |  |
| prysm | `testing/spectest/shared/altair/finality/finality.go` | verified |  |
| influxdb | `core/iox_v1_query_api/src/response/buffered.rs` | verified |  |
| influxdb | `core/influxdb2_client/src/models/ast/node.rs` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/calibur/libraries/WrappedSignatureLib.sol` | verified |  |
| influxdb | `core/trogging/src/config.rs` | verified |  |
| influxdb | `core/iox_http/src/write/v2.rs` | verified |  |
| grafana | `public/app/features/dashboard/dashgrid/DashboardLibrary/SuggestedDashboardsList/SuggestedDashboardsList.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/LogsQueryBuilder/KQLPreview.tsx` | verified |  |
| prysm | `beacon-chain/verification/result.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/universal-router/libraries/Locker.sol` | verified |  |
| uniswap-contracts | `script/cli/src/screens/types/select.rs` | verified |  |
| grafana | `public/app/features/alerting/unified/mocks/server/handlers/silences.ts` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v4-periphery/libraries/CalldataDecoder.sol` | verified |  |
| prysm | `testing/slasher/simulator/simulator_test.go` | verified |  |
| influxdb | `influxdb3_telemetry/src/metrics.rs` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v3-periphery/interfaces/IERC20Metadata.sol` | verified |  |
| grafana | `public/app/plugins/panel/table/cells/ImageCellOptionsEditor.tsx` | verified |  |
| influxdb | `core/influxdb_influxql_parser/src/show_tag_values.rs` | verified |  |
| prysm | `testing/spectest/mainnet/bellatrix__epoch_processing__historical_roots_update_test.go` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/governance/Governor.sol` | verified |  |
| prysm | `container/trie/zerohashes.go` | verified |  |
| go | `src/hash/crc32/crc32.go` | verified |  |
| go | `src/encoding/json/internal/jsonopts/options.go` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/ArraysImpl.sol` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/layout-tabs/TabItemRepeater.tsx` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/AccessControlEnumerableMock.sol` | verified |  |
| go | `src/go/types/sizeof_test.go` | verified |  |
| influxdb | `influxdb3_catalog/src/catalog/versions/v3/schema/retention.rs` | verified |  |
| grafana | `public/app/plugins/panel/debug/EventBusLogger.tsx` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/access/AccessControl.sol` | verified |  |
| grafana | `public/app/features/transformers/editors/OrganizeFieldsTransformerEditor.tsx` | verified |  |
| prysm | `tools/analyzers/shadowpredecl/analyzer_test.go` | verified |  |
| prysm | `beacon-chain/p2p/partialdatacolumnbroadcaster/partial.go` | verified |  |
| go | `test/fixedbugs/issue19667.go` | verified |  |
| go | `test/fixedbugs/issue41872.go` | verified |  |
| go | `test/fixedbugs/issue19028.dir/main.go` | verified |  |
| prysm | `testing/spectest/minimal/electra__epoch_processing__pending_deposits_updates_test.go` | verified |  |
| grafana | `public/app/plugins/panel/gettingstarted/components/Step.tsx` | verified |  |
| prysm | `beacon-chain/db/kv/backup.go` | verified |  |
| influxdb | `core/iox_query/src/provider/progressive_eval.rs` | verified |  |
| prysm | `api/client/builder/log.go` | verified |  |
| go | `test/fixedbugs/issue5698.go` | verified |  |
| influxdb | `influxdb3/tests/server/limits.rs` | verified |  |
| grafana | `public/app/features/alerting/unified/hooks/ruleGroup/useProduceNewRuleGroup.ts` | verified |  |
