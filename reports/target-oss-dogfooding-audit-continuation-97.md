# Target OSS no-LLM dogfooding audit — continuation 97 (batch 98)

Run: 2026-07-21T23:41:19.202099+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification.

- Solidity constant expression resolution now supports composite constants (e.g. ``NEXT_OFFSET = ADDR_SIZE + FEE_SIZE``).
- Solidity files under ``mocks/`` directories are skipped from reentrancy/access-control contract-issue checks.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| prysm | `beacon-chain/sync/initial-sync/downscore_test.go` | verified |  |
| prysm | `validator/accounts/accounts_list_test.go` | verified |  |
| go | `src/os/exec/internal_test.go` | verified |  |
| influxdb | `influxdb3_types/src/http.rs` | verified |  |
| go | `test/fixedbugs/issue32901.dir/c.go` | verified |  |
| go | `src/internal/trace/traceviewer/histogram.go` | verified |  |
| grafana | `pkg/tsdb/influxdb/influxql/parser_bench_test.go` | verified |  |
| uniswap-contracts | `lib/oz-v3.4-solc-0.7/contracts/utils/Address.sol` | verified |  |
| go | `test/fixedbugs/issue9604.go` | verified |  |
| grafana | `pkg/tsdb/influxdb/models/query_part_test.go` | verified |  |
| grafana | `public/app/features/provisioning/Repository/RepositoryPullStatusCard.tsx` | verified |  |
| prysm | `beacon-chain/sync/validate_aggregate_proof.go` | verified |  |
| prysm | `testing/spectest/mainnet/altair__epoch_processing__registry_updates_test.go` | verified |  |
| influxdb | `core/object_store_mem_cache/src/cache_system/hook/chain.rs` | verified |  |
| go | `src/testing/slogtest/slogtest.go` | verified |  |
| go | `test/fixedbugs/issue20174.go` | verified |  |
| grafana | `pkg/infra/leaderelection/leader_election_test.go` | verified |  |
| grafana | `public/app/features/transformers/partitionByValues/partition.ts` | verified |  |
| influxdb | `core/influxdb2_client/src/models/ast/string_literal.rs` | verified |  |
| prysm | `testing/spectest/minimal/bellatrix__epoch_processing__randao_mixes_reset_test.go` | verified |  |
| prysm | `testing/spectest/minimal/gloas__epoch_processing__pending_consolidations_test.go` | verified |  |
| influxdb | `core/dml/src/lib.rs` | verified |  |
| prysm | `testing/spectest/mainnet/gloas__operations__block_header_test.go` | verified |  |
| influxdb | `core/influxdb_influxql_parser/src/simple_from_clause.rs` | verified |  |
| go | `src/net/mptcpsock_linux_test.go` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/crosschain/errors.sol` | verified |  |
| influxdb | `influxdb3_catalog/src/catalog/versions/v3/inner/enterprise.rs` | verified |  |
| go | `test/fixedbugs/issue30087.go` | verified |  |
| grafana | `apps/quotas/plugin/src/generated/quota/v0alpha1/types.status.gen.ts` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/swap-router-contracts/interfaces/IMulticallExtended.sol` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v3-core/interfaces/pool/IUniswapV3PoolActions.sol` | verified |  |
| uniswap-contracts | `script/cli/src/screens/shared/generic_select.rs` | verified |  |
| influxdb | `core/mutable_batch_pb/benches/write_table_batch.rs` | verified |  |
| influxdb | `core/influxdb_line_protocol/src/lib.rs` | verified |  |
| prysm | `testing/spectest/shared/gloas/operations/bls_to_execution_changes.go` | verified |  |
| go | `src/encoding/json/internal/jsontest/testdata.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/lib-external/solidity-lib/contracts/libraries/FixedPoint.sol` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/NavToolbarActions.tsx` | verified |  |
| influxdb | `influxdb3/src/commands/update.rs` | verified |  |
| grafana | `apps/alerting/rules/pkg/app/rulesequence/validator.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/calibur/interfaces/ICalibur.sol` | verified |  |
| go | `test/fixedbugs/issue71225.go` | verified |  |
| grafana | `public/app/features/visualization/data-hover/renderValue.tsx` | verified |  |
| prysm | `cmd/prysmctl/validator/withdraw.go` | verified |  |
| influxdb | `core/executor/src/lib.rs` | verified |  |
| prysm | `beacon-chain/sync/validate_bls_to_execution_change_test.go` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/crosschain/bridges.sol` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v3-periphery/libraries/Path.sol` | verified |  |
| uniswap-contracts | `script/cli/src/screens/deploy_contracts/execute_deploy_script.rs` | verified |  |
| grafana | `public/app/plugins/datasource/jaeger/jest-setup.js` | verified |  |
