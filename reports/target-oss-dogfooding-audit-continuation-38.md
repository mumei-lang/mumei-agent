# Target OSS no-LLM dogfooding audit — continuation 38 (batch 39)

Run: 2026-07-21T08:26:25.245847+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All 50 sampled files passed no-LLM verification.

## Tool-side fixes in this batch

- Go scaling functions (e.g. `isScaledImmI`) treat an integer `scale` parameter as non-zero, suppressing divide-by-zero false positives.
- Rust local variables initialized with float literals (or `num::cast` of such literals) are tracked as float, so dividing by them is not flagged as a panic.
- Rust sources where every function is annotated with a test attribute (`#[test]`, `#[tokio::test]`, `#[test_log::test]`) are treated as having no user-facing function declarations, preventing spurious "No Mumei atoms" errors.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `test/fixedbugs/issue73180.go` | verified | |
| go | `src/runtime/race/race_darwin_arm64.go` | verified | |
| uniswap-contracts | `script/cli/src/workflows/register/mod.rs` | verified | |
| prysm | `beacon-chain/core/transition/altair_transition_no_verify_sig_test.go` | verified | |
| go | `src/cmd/compile/internal/types2/trie_test.go` | verified | |
| influxdb | `core/query_functions/src/coalesce_struct.rs` | verified | |
| influxdb | `influxdb3/src/commands/show/system.rs` | verified | |
| prysm | `runtime/interop/genesis.go` | verified | |
| prysm | `api/rest/rest_handler.go` | verified | |
| go | `src/crypto/tls/handshake_unix_test.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/permit2/libraries/SafeCast160.sol` | verified | |
| grafana | `public/app/plugins/panel/piechart/suggestions.ts` | verified | |
| go | `src/cmd/compile/internal/test/testdata/gen/copyGen.go` | verified | |
| go | `test/fixedbugs/issue26120.go` | verified | |
| prysm | `beacon-chain/core/transition/skip_slot_cache.go` | verified | |
| go | `src/os/readfrom_solaris_test.go` | verified | |
| uniswap-contracts | `src/briefcase/deployers/v4-periphery/StateViewDeployer.sol` | verified | |
| grafana | `public/app/plugins/datasource/cloudwatch/mocks/cloudwatch-logs-sql-test-data/singleLineFullQuery.ts` | verified | |
| influxdb | `influxdb3_clap_blocks/src/datafusion/tests.rs` | verified | |
| prysm | `async/event/example_scope_test.go` | verified | |
| prysm | `testing/spectest/shared/common/forkchoice/runner.go` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/token/ERC1155/IERC1155.sol` | verified | |
| influxdb | `influxdb3_cache/src/last_cache/cache.rs` | verified | |
| grafana | `pkg/plugins/manager/sources/source_local_disk_test.go` | verified | |
| go | `src/cmd/internal/obj/riscv/obj.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/swap-router-contracts/interfaces/IOracleSlippage.sol` | verified | |
| go | `test/fixedbugs/issue22962.dir/b.go` | verified | |
| go | `test/fixedbugs/issue23664.go` | verified | |
| prysm | `beacon-chain/rpc/prysm/v1alpha1/validator/validator_test.go` | verified | |
| influxdb | `core/mutable_batch_lp/src/lib.rs` | verified | |
| prysm | `beacon-chain/operations/attestations/kv/log.go` | verified | |
| influxdb | `influxdb3_telemetry/src/store.rs` | verified | |
| uniswap-contracts | `src/briefcase/protocols/lib-external/solidity-lib/contracts/libraries/FullMath.sol` | verified | |
| uniswap-contracts | `src/briefcase/protocols/util-contracts/interfaces/ICalibur.sol` | verified | |
| prysm | `tools/exploredb/main.go` | verified | |
| influxdb | `influxdb3_catalog/src/catalog/versions/v3/ops/user/tests.rs` | verified | |
| influxdb | `core/flightsql/src/cmd.rs` | verified | |
| grafana | `pkg/services/pluginsintegration/installsync/syncer.go` | verified | |
| prysm | `encoding/ssz/detect/fieldspec_test.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/view-quoter-v3/libraries/QuoterMath.sol` | verified | |
| grafana | `public/app/features/alerting/unified/components/receivers/form/ReceiverForm.tsx` | verified | |
| influxdb | `influxdb3_process/build.rs` | verified | |
| grafana | `packages/grafana-runtime/src/internal/index.ts` | verified | |
| grafana | `pkg/tsdb/grafanads/grafana.go` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/access/IAccessControlEnumerable.sol` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v4-core/libraries/Position.sol` | verified | |
| grafana | `public/app/plugins/panel/nodeGraph/NodeGraph.test.tsx` | verified | |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v4_test.go` | verified | |
| grafana | `packages/grafana-flamegraph/src/CallTree/utils.ts` | verified | |
| influxdb | `core/data_types/src/snapshot/root.rs` | verified | |
