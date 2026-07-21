# Target OSS no-LLM dogfooding audit — continuation 62 (batch 63)

Run: 2026-07-21T14:05:53.557418+00:00

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
| prysm | `proto/prysm/v1alpha1/finalized_block_root_container.pb.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v4-hooks-public/aggregator-hooks/implementations/PancakeSwapV3/interfaces/IPancakeSwapV3Callback.sol` | verified | |
| go | `test/interface/explicit.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/uniswapx/v4/interfaces/IDCAHook.sol` | verified | |
| influxdb | `influxdb3_catalog/src/format/header.rs` | verified | |
| go | `src/cmd/internal/obj/util.go` | verified | |
| go | `test/fixedbugs/issue19028.dir/a.go` | verified | |
| prysm | `testing/endtoend/components/eth1/helpers.go` | verified | |
| go | `src/net/http/internal/http2/writesched_priority_rfc9218_test.go` | verified | |
| go | `src/internal/runtime/sys/no_dit.go` | verified | |
| prysm | `testing/spectest/minimal/phase0__epoch_processing__participation_record_updates_test.go` | verified | |
| grafana | `public/app/features/admin/LicenseChrome.tsx` | verified | |
| go | `test/fixedbugs/issue18882.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v4-core/types/PoolId.sol` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/interfaces/IERC4626.sol` | verified | |
| influxdb | `influxdb3_cache/src/parquet_cache/metrics.rs` | verified | |
| go | `src/internal/types/testdata/fixedbugs/issue49179.go` | verified | |
| influxdb | `core/tracker/src/task/metrics.rs` | verified | |
| grafana | `public/app/features/alerting/unified/triage/instance-details/drawerTimeRangeUtils.ts` | verified | |
| uniswap-contracts | `script/smoke/native-is-erc20/V4SmokeNativeIsERC20.s.sol` | verified | |
| grafana | `public/app/features/alerting/unified/api/labelsApi.ts` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v3-periphery/interfaces/ISwapRouter.sol` | verified | |
| influxdb | `core/influxdb2_client/tests/health.rs` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v2-core/libraries/Math.sol` | verified | |
| grafana | `public/app/features/dashboard-scene/scene/dashboard-filters-overview/FiltersOverviewRow.tsx` | verified | |
| grafana | `devenv/docker/loadtest/annotations_by_tag_test.js` | verified | |
| grafana | `pkg/registry/apis/provisioning/jobs/progress_test.go` | verified | |
| prysm | `testing/spectest/mainnet/gloas__operations__attester_slashing_test.go` | verified | |
| grafana | `public/app/features/expressions/components/SqlExpressions/SqlQueryActions.tsx` | verified | |
| prysm | `api/client/event/event_stream.go` | verified | |
| grafana | `packages/grafana-plugin-configs/types/replace-in-webpack-plugin.d.ts` | verified | |
| influxdb | `core/data_types/src/snapshot/mask.rs` | verified | |
| prysm | `crypto/bls/common/error.go` | verified | |
| go | `test/codegen/simd_arm64.go` | verified | |
| influxdb | `influxdb3_catalog/src/object_store/versions/v3/tests.rs` | verified | |
| influxdb | `core/iox_query/src/physical_optimizer/dedup/test_util.rs` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/StringsMock.sol` | verified | |
| influxdb | `influxdb3_catalog/src/format/records/cache.rs` | verified | |
| go | `src/runtime/testdata/testgoroutineleakprofile/goker/cockroach16167.go` | verified | |
| prysm | `testing/spectest/mainnet/deneb__epoch_processing__effective_balance_updates_test.go` | verified | |
| influxdb | `core/influxdb2_client/examples/write.rs` | verified | |
| prysm | `beacon-chain/operations/voluntaryexits/doc.go` | verified | |
| prysm | `cmd/prysmctl/testnet/generate_genesis_test.go` | verified | |
| grafana | `public/app/features/templating/LegacyVariableWrapper.ts` | verified | |
| uniswap-contracts | `src/briefcase/protocols/mixed-quoter/libraries/V2Library.sol` | verified | |
| grafana | `packages/grafana-ui/src/components/Icon/utils.ts` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v3-periphery/libraries/NFTSVG.sol` | verified | |
| go | `test/fixedbugs/gcc61258.go` | verified | |
| influxdb | `core/iox_query/src/analyzer/extract_sleep.rs` | verified | |
| prysm | `testing/mock/beacon_altair_validator_server_mock.go` | verified | |
