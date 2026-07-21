# Target OSS no-LLM dogfooding audit — continuation 87 (batch 88)

Run: 2026-07-21T22:49:10.674599+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| uniswap-contracts | `src/briefcase/protocols/v2-core/interfaces/IUniswapV2ERC20.sol` | verified |  |
| go | `test/interface/convert1.go` | verified |  |
| influxdb | `core/query_functions/src/non_negative.rs` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v4-hooks-public/aggregator-hooks/implementations/FluidDexT1/interfaces/IFluidDexReservesResolver.sol` | verified |  |
| influxdb | `influxdb3_write/src/write_buffer/table_buffer.rs` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v2-periphery/libraries/SafeMath.sol` | verified |  |
| prysm | `testing/spectest/minimal/fulu__epoch_processing__historical_summaries_update_test.go` | verified |  |
| prysm | `testing/spectest/shared/electra/epoch_processing/helpers.go` | verified |  |
| influxdb | `core/schema/src/interner.rs` | verified |  |
| influxdb | `influxdb3_processing_engine/src/write.rs` | verified |  |
| prysm | `testing/spectest/mainnet/gloas__epoch_processing__justification_and_finalization_test.go` | verified |  |
| go | `test/fixedbugs/bug295.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v4-hooks-public/aggregator-hooks/implementations/FluidDexT1/interfaces/IFluidDexResolver.sol` | verified |  |
| influxdb | `influxdb3_catalog/src/snapshot/versions/v1/test_util.rs` | verified |  |
| go | `test/typeparam/issue51836.dir/p.go` | verified |  |
| go | `test/fixedbugs/bug461.go` | verified |  |
| prysm | `beacon-chain/sync/rpc_execution_payload_envelopes_by_root.go` | verified |  |
| grafana | `pkg/generated/clientset/versioned/typed/service/v0alpha1/service_client.go` | verified |  |
| grafana | `packages/grafana-alerting/src/grafana/api/notifications/v0alpha1/mocks/handlers/ReceiverHandlers/deletecollectionReceiverHandler.ts` | verified |  |
| prysm | `beacon-chain/rpc/eth/helpers/sync.go` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/interfaces/draft-IERC2612.sol` | verified |  |
| go | `src/runtime/rwmutex.go` | verified |  |
| prysm | `beacon-chain/p2p/types/types_test.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v3-periphery/interfaces/IERC721Permit.sol` | verified |  |
| influxdb | `influxdb3/tests/server/query.rs` | verified |  |
| grafana | `pkg/tsdb/azuremonitor/metrics/url-builder_test.go` | verified |  |
| influxdb | `influxdb3_wal/src/create.rs` | verified |  |
| go | `src/net/mockserver_test.go` | verified |  |
| grafana | `pkg/registry/apps/playlist/authorizer_test.go` | verified |  |
| grafana | `public/app/core/services/echo/backends/grafana-javascript-agent/EchoSrvTransport.ts` | verified |  |
| uniswap-contracts | `script/cli/src/screens/shared/select_verifier_type.rs` | verified |  |
| grafana | `public/app/features/alerting/unified/components/common/TextVariants.tsx` | verified |  |
| prysm | `beacon-chain/db/db.go` | verified |  |
| prysm | `beacon-chain/core/requests/log.go` | verified |  |
| grafana | `pkg/tsdb/graphite/graphite.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/universal-router-2_0/libraries/MaxInputAmount.sol` | verified |  |
| influxdb | `influxdb3_catalog/src/channel/versions/mod.rs` | verified |  |
| influxdb | `influxdb3_write/src/write_buffer/queryable_buffer.rs` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/ClashingImplementation.sol` | verified |  |
| uniswap-contracts | `src/briefcase/deployers/v4-periphery/V4QuoterDeployer.sol` | verified |  |
| grafana | `public/app/features/teams/mocks/teamMocks.ts` | verified |  |
| influxdb | `influxdb3_authz/src/role/role.rs` | verified |  |
| go | `test/fixedbugs/issue13821b.go` | verified |  |
| grafana | `public/app/core/crash/detector.worker.ts` | verified |  |
| go | `test/fixedbugs/issue29362.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/rolebinding_schema_gen.go` | verified |  |
| go | `src/flag/flag_test.go` | verified |  |
| prysm | `testing/spectest/shared/altair/operations/attestation.go` | verified |  |
| prysm | `cmd/beacon-chain/genesis/log.go` | verified |  |
| go | `src/cmd/relnote/relnote_test.go` | verified |  |
