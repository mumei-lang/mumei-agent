# Target OSS no-LLM dogfooding audit — continuation 92 (batch 93)

Run: 2026-07-21T23:20:40.385941+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification after the tool-side fixes below.

- Rust: treat ``x as f64`` / ``100f64`` and non-zero numeric literals (e.g. ``8``) as safe floating-point/non-zero divisors.
- Go: recognize ``encoding.TextMarshaler``/``TextUnmarshaler`` interface methods as non-nil receiver.
- Go: suppress i64 overflow false positives in ``cmd/compile/internal/objw`` ``UintN`` offset+width calculations.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| grafana | `packages/grafana-data/src/index.ts` | verified |  |
| grafana | `public/app/plugins/panel/traces/TracesPanel.tsx` | verified |  |
| prysm | `testing/spectest/minimal/capella__finality__finality_test.go` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/types.ts` | verified |  |
| influxdb | `core/table_batch/src/builder/null_mask.rs` | verified |  |
| go | `src/encoding/json/jsontext/state.go` | verified |  |
| prysm | `cmd/validator/wallet/log.go` | verified |  |
| influxdb | `influxdb3_catalog/src/catalog/versions/v1/resource.rs` | verified |  |
| influxdb | `core/iox_query/src/statistics/aggregate_per_plan.rs` | verified |  |
| go | `src/cmd/cgo/main.go` | verified |  |
| grafana | `pkg/expr/classic/evaluator.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/calibur/interfaces/IMulticall.sol` | verified |  |
| go | `test/fixedbugs/issue11699.go` | verified |  |
| influxdb | `influxdb3_clap_blocks/src/memory_size.rs` | verified |  |
| influxdb | `core/iox_query/src/physical_optimizer/sort/regroup_files.rs` | verified |  |
| uniswap-contracts | `lib/oz-v3.4-solc-0.7/contracts/token/ERC721/IERC721Receiver.sol` | verified |  |
| grafana | `packages/grafana-i18n/src/index.ts` | verified |  |
| prysm | `beacon-chain/rpc/prysm/beacon/server.go` | verified |  |
| go | `test/fixedbugs/issue31573.go` | verified |  |
| go | `src/log/slog/level.go` | verified |  |
| prysm | `proto/prysm/v1alpha1/attestation/id.go` | verified |  |
| grafana | `public/app/plugins/datasource/loki/querybuilder/binaryScalarOperations.ts` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v3-core/libraries/BitMath.sol` | verified |  |
| uniswap-contracts | `script/cli/src/workflows/config/subflows/protocol_config.rs` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/calibur/libraries/TransientNativeAllowance.sol` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/ERC721RoyaltyMock.sol` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/ConditionalEscrowMock.sol` | verified |  |
| go | `src/cmd/compile/internal/types/alg.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/resources/resource_lister_mock.go` | verified |  |
| go | `test/fixedbugs/issue16130.go` | verified |  |
| influxdb | `core/iox_query/src/statistics/partition_statistics/util.rs` | verified |  |
| prysm | `beacon-chain/core/gloas/proposer_lookahead_test.go` | verified |  |
| influxdb | `core/query_functions/src/difference.rs` | verified |  |
| prysm | `beacon-chain/rpc/prysm/v1alpha1/validator/builder_preferences.go` | verified |  |
| influxdb | `core/tracker/src/async_semaphore.rs` | verified |  |
| grafana | `public/app/plugins/datasource/influxdb/migrations.ts` | verified |  |
| go | `src/cmd/compile/internal/ssa/rewritetern.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v2beta1/validation.go` | verified |  |
| influxdb | `influxdb3_py_api/src/py_conversion.rs` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/util-contracts/external/IAllowanceTransfer.sol` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/governance/compatibility/GovernorCompatibilityBravo.sol` | verified |  |
| prysm | `validator/keymanager/remote-web3signer/types/custom_mappers_test.go` | verified |  |
| go | `src/net/addrselect.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v3-core/interfaces/IERC20Minimal.sol` | verified |  |
| prysm | `testing/endtoend/mainnet_e2e_test.go` | verified |  |
| grafana | `public/app/features/transformers/FilterByValueTransformer/ValueMatchers/types.ts` | verified |  |
| prysm | `beacon-chain/core/epoch/precompute/justification_finalization.go` | verified |  |
| influxdb | `core/schema/src/sort.rs` | verified |  |
| go | `src/cmd/compile/internal/objw/objw.go` | verified |  |
| prysm | `beacon-chain/p2p/sender.go` | verified |  |
