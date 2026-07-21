# Target OSS no-LLM dogfooding audit — continuation 78 (batch 79)

Run: 2026-07-21T22:08:59.336825+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification after fixing `prysm/validator/client/iface/validator_client.go`.

## Tool-side fixes in this batch

- Go: treat `MarshalJSON` / `UnmarshalJSON` pointer-receiver methods as `encoding/json` interface methods and suppress nil-receiver false positives.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/crypto/tls/generate_cert.go` | verified |  |
| grafana | `pkg/cmd/grafana-cli/commands/upgrade_all_command_test.go` | verified |  |
| prysm | `validator/client/iface/validator_client.go` | verified |  |
| grafana | `apps/logsdrilldown/pkg/apis/logsdrilldown/v1beta1/constants.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/lib-external/solmate/src/utils/CREATE3.sol` | verified |  |
| influxdb | `influxdb3_catalog/src/format/apply.rs` | verified |  |
| go | `src/internal/coverage/test/roundtrip_test.go` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/interfaces/IERC20Metadata.sol` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v4-periphery/interfaces/IV4Quoter.sol` | verified |  |
| uniswap-contracts | `script/smoke/V2SmokeTest.s.sol` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v4-core/libraries/ProtocolFeeLibrary.sol` | verified |  |
| grafana | `public/app/features/commandPalette/values.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Forms/InlineSegmentGroup.tsx` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/util-contracts/external/IEIP712.sol` | verified |  |
| influxdb | `influxdb3_cache/src/distinct_cache/table_function.rs` | verified |  |
| go | `test/abi/convT64_criteria.go` | verified |  |
| go | `src/encoding/binary/example_test.go` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/TableNG/refactored/RefactoredTableNG.tsx` | verified |  |
| prysm | `consensus-types/light-client/helpers.go` | verified |  |
| influxdb | `cli_types/src/lib.rs` | verified |  |
| go | `misc/ios/detect.go` | verified |  |
| prysm | `beacon-chain/sync/initial-sync/fsm_test.go` | verified |  |
| grafana | `pkg/services/ngalert/backtesting/eval_data.go` | verified |  |
| prysm | `tools/analyzers/modernize/mapsloop/analyzer.go` | verified |  |
| grafana | `pkg/registry/apis/collections/legacy/migrator.go` | verified |  |
| prysm | `testing/spectest/shared/fulu/epoch_processing/effective_balance_updates.go` | verified |  |
| prysm | `proto/prysm/v1alpha1/deneb.ssz.go` | verified |  |
| grafana | `packages/grafana-ui/src/components/DataSourceSettings/CertificationKey.tsx` | verified |  |
| influxdb | `core/influxdb2_client/src/models/retention_rule.rs` | verified |  |
| grafana | `pkg/tests/apis/alerting/notifications/templategroup/imported_test.go` | verified |  |
| influxdb | `core/influxdb2_client/src/api/health.rs` | verified |  |
| go | `src/cmp/cmp.go` | verified |  |
| grafana | `packages/grafana-ui/src/components/ValuePicker/ValuePicker.tsx` | verified |  |
| influxdb | `core/query_functions/src/sleep.rs` | verified |  |
| go | `src/crypto/internal/fips140/aes/aes_test.go` | verified |  |
| go | `src/math/rand/v2/auto_test.go` | verified |  |
| prysm | `testing/spectest/minimal/gloas__epoch_processing__proposer_lookahead_test.go` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/governance/extensions/GovernorVotes.sol` | verified |  |
| prysm | `beacon-chain/p2p/peers/scorers/service.go` | verified |  |
| influxdb | `influxdb3_write/src/paths.rs` | verified |  |
| go | `src/cmd/compile/internal/types2/typelists.go` | verified |  |
| go | `src/internal/runtime/cgroup/export_test.go` | verified |  |
| influxdb | `core/jemalloc_stats/tests/dump_heap_profile.rs` | verified |  |
| prysm | `encoding/ssz/query/vector.go` | verified |  |
| uniswap-contracts | `lib/oz-v3.4-solc-0.7/contracts/token/ERC20/IERC20.sol` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/ERC20CappedMock.sol` | verified |  |
| influxdb | `core/object_store_mem_cache/benches/s3_fifo_concurrency.rs` | verified |  |
| influxdb | `core/futures_test_utils/benches/buffered_stream.rs` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/ERC165/ERC165MissingData.sol` | verified |  |
| prysm | `beacon-chain/blockchain/receive_data_column.go` | verified |  |
