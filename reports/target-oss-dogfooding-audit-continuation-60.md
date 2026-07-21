# Target OSS no-LLM dogfooding audit — continuation 60 (batch 61)

Run: 2026-07-21T14:02:16.808589+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All 50 sampled files passed no-LLM verification.

## Tool-side fixes in this batch

- No new mumei-agent false positives in this batch.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/go/internal/run/run.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/calibur/libraries/CalldataDecoder.sol` | verified | |
| go | `src/os/user/lookup_stubs.go` | verified | |
| grafana | `pkg/infra/metrics/settings.go` | verified | |
| influxdb | `core/influxdb2_client/tests/common/mod.rs` | verified | |
| grafana | `pkg/services/sqlstore/sqlstore_metrics.go` | verified | |
| go | `src/runtime/mgcwork.go` | verified | |
| prysm | `beacon-chain/core/validators/slashing.go` | verified | |
| prysm | `beacon-chain/rpc/eth/events/events_test.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v4-periphery/libraries/ERC721PermitHash.sol` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/CountersImpl.sol` | verified | |
| influxdb | `core/object_store_mem_cache/src/cache_system/utils.rs` | verified | |
| uniswap-contracts | `src/briefcase/protocols/lib-external/oz-v3.4-solc-0.7/contracts/math/SignedSafeMath.sol` | verified | |
| prysm | `proto/engine/v1/execution_engine.pb.go` | verified | |
| go | `test/fixedbugs/issue47227.go` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/utils/introspection/IERC1820Implementer.sol` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/crosschain/arbitrum/LibArbitrumL2.sol` | verified | |
| grafana | `pkg/services/sqlstore/migrator/advisory_lock_id.go` | verified | |
| prysm | `beacon-chain/p2p/dial_relay_node_test.go` | verified | |
| go | `src/cmd/link/internal/benchmark/bench_test.go` | verified | |
| prysm | `testing/spectest/minimal/capella__operations__attestation_test.go` | verified | |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v33_test.go` | verified | |
| go | `src/internal/bytealg/bytealg.go` | verified | |
| prysm | `beacon-chain/state/state-native/setters_gloas.go` | verified | |
| influxdb | `influxdb3_authz/src/lib.rs` | verified | |
| influxdb | `influxdb3_sys_events/benches/store_benchmark.rs` | verified | |
| influxdb | `core/data_types/src/sequence_number_set.rs` | verified | |
| grafana | `apps/advisor/pkg/app/checktyperegisterer/checktyperegisterer.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v3-periphery/interfaces/INonfungiblePositionManager.sol` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/interfaces/IERC721Enumerable.sol` | verified | |
| influxdb | `influxdb3_startup/src/lib.rs` | verified | |
| influxdb | `influxdb3_catalog/src/catalog/versions/v3/ops/database/tests.rs` | verified | |
| influxdb | `core/mutable_batch/tests/extend.rs` | verified | |
| grafana | `public/app/features/transformers/spatial/models.gen.ts` | verified | |
| influxdb | `influxdb3_catalog/src/catalog/versions/v3/ops/feature_level/tests.rs` | verified | |
| go | `test/fixedbugs/issue55122b.go` | verified | |
| go | `test/fixedbugs/issue10320.go` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/interfaces/IERC777Recipient.sol` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/token/ERC20/extensions/ERC20Capped.sol` | verified | |
| influxdb | `core/iox_query/src/provider/record_batch_exec.rs` | verified | |
| go | `src/internal/trace/testdata/testprog/cpu-profile.go` | verified | |
| go | `src/mime/multipart/formdata_test.go` | verified | |
| grafana | `pkg/registry/apis/iam/team/legacy_members_search.go` | verified | |
| grafana | `public/app/features/provisioning/hooks/PushSuccessMessage.tsx` | verified | |
| prysm | `testing/spectest/mainnet/gloas__finality__finality_test.go` | verified | |
| grafana | `public/app/core/components/AppChrome/OrganizationSwitcher/OrganizationSelect.tsx` | verified | |
| prysm | `api/server/structs/conversions_block_execution.go` | verified | |
| prysm | `beacon-chain/rpc/eth/node/handlers_peers.go` | verified | |
| grafana | `public/app/plugins/datasource/cloudwatch/components/shared/DataSources/DataSourcesField.tsx` | verified | |
| prysm | `beacon-chain/p2p/encoder/snappy_test.go` | verified | |
