# Target OSS no-LLM dogfooding audit — continuation 55 (batch 56)

Run: 2026-07-21T13:39:24.717561+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All 50 sampled files passed no-LLM verification.

## Tool-side fixes in this batch

No new mumei-agent false positives were identified in this batch.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| influxdb | `influxdb3_write/src/write_buffer/persisted_files/tests.rs` | verified | |
| influxdb | `core/iox_v1_query_api/src/response/json.rs` | verified | |
| prysm | `beacon-chain/sync/rpc_chunked_response.go` | verified | |
| go | `src/cmd/compile/internal/loopvar/testdata/for_complicated_esc_address.go` | verified | |
| grafana | `pkg/registry/apis/secret/secretkeeper/sqlkeeper/keeper_test.go` | verified | |
| prysm | `beacon-chain/slasher/queue.go` | verified | |
| go | `src/cmd/compile/internal/ssa/print.go` | verified | |
| go | `src/syscall/mkasm.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/universal-router/libraries/Constants.sol` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/proxy/ERC1967/ERC1967Upgrade.sol` | verified | |
| go | `src/internal/trace/testdata/testprog/gomaxprocs.go` | verified | |
| prysm | `consensus-types/light-client/optimistic_update.go` | verified | |
| uniswap-contracts | `script/smoke/V4SmokeTest.s.sol` | verified | |
| grafana | `pkg/plugins/manager/pipeline/termination/termination.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v4-core/interfaces/callback/IUnlockCallback.sol` | verified | |
| uniswap-contracts | `src/briefcase/protocols/uniswapx/v4/base/ReactorStructs.sol` | verified | |
| grafana | `pkg/services/provisioning/values/values.go` | verified | |
| go | `src/cmd/pack/doc.go` | verified | |
| grafana | `public/app/plugins/datasource/loki/mocks/metadataRequest.ts` | verified | |
| go | `src/runtime/netpoll_os_test.go` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/interfaces/IERC1363Receiver.sol` | verified | |
| influxdb | `core/query_functions/src/tz.rs` | verified | |
| influxdb | `core/partition/benches/partitioner.rs` | verified | |
| uniswap-contracts | `script/cli/src/libs/mod.rs` | verified | |
| grafana | `public/app/features/explore/TraceView/components/TraceTimelineViewer/ListView/index.tsx` | verified | |
| go | `test/fixedbugs/issue41736.go` | verified | |
| grafana | `packages/grafana-runtime/src/utils/useFavoriteDatasources.ts` | verified | |
| go | `src/internal/testpty/pty_darwin.go` | verified | |
| influxdb | `core/influxdb_influxql_parser/src/drop.rs` | verified | |
| influxdb | `influxdb3_catalog/src/channel/versions/v2.rs` | verified | |
| prysm | `beacon-chain/db/filesystem/layout_by_epoch.go` | verified | |
| grafana | `packages/grafana-test-utils/src/fixtures/teams.ts` | verified | |
| prysm | `testing/spectest/shared/phase0/shuffling/core/shuffle/shuffle_test_format.go` | verified | |
| grafana | `public/app/features/explore/hooks/useStateSync/internal.utils.ts` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v3-core/libraries/UnsafeMath.sol` | verified | |
| uniswap-contracts | `lib/oz-v3.4-solc-0.7/contracts/utils/EnumerableSet.sol` | verified | |
| prysm | `beacon-chain/cache/payload_id_test.go` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/access/IAccessControl.sol` | verified | |
| influxdb | `core/iox_http_util/src/lib.rs` | verified | |
| go | `src/runtime/testdata/testgoroutineleakprofile/goker/moby17176.go` | verified | |
| influxdb | `influxdb3_types/src/write.rs` | verified | |
| prysm | `testing/util/merge.go` | verified | |
| influxdb | `core/influxdb2_client/src/models/ast/duration.rs` | verified | |
| prysm | `validator/accounts/wallet_recover_test.go` | verified | |
| go | `test/inline_math_bits_rotate.go` | verified | |
| prysm | `api/jwt.go` | verified | |
| grafana | `pkg/codegen/astmanip_test.go` | verified | |
| grafana | `pkg/tsdb/grafana-testdata-datasource/kinds/routes.go` | verified | |
| prysm | `testing/spectest/minimal/phase0__epoch_processing__rewards_and_penalties_test.go` | verified | |
| influxdb | `core/metric/src/duration.rs` | verified | |
