# Target OSS no-LLM dogfooding audit — continuation 66 (batch 67)

Run: 2026-07-21T14:24:07.886485+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All 50 sampled files passed no-LLM verification.

## Tool-side fixes in this batch

- Sampling exclusion updated to skip Rust ``tests.rs``/``test.rs`` test module files.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| grafana | `pkg/services/ngalert/schedule/retry_test.go` | verified | |
| grafana | `public/app/features/plugins/admin/mocks/catalogPlugin.mock.ts` | verified | |
| prysm | `testing/spectest/mainnet/fulu__operations__proposer_slashing_test.go` | verified | |
| grafana | `public/app/plugins/panel/live/LivePublish.tsx` | verified | |
| grafana | `public/app/plugins/panel/stat/StatPanel.tsx` | verified | |
| prysm | `container/leaky-bucket/collector_test.go` | verified | |
| influxdb | `core/influxdb_iox_client/src/format/influxql.rs` | verified | |
| influxdb | `core/iox_query_influxql/src/window/integral.rs` | verified | |
| go | `src/internal/asan/doc.go` | verified | |
| go | `src/cmd/go/internal/modcmd/init.go` | verified | |
| go | `src/internal/runtime/atomic/atomic_ppc64x.go` | verified | |
| grafana | `public/app/plugins/panel/news/feed.ts` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/proxy/beacon/IBeacon.sol` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v4-periphery/interfaces/IUnorderedNonce.sol` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/ERC721EnumerableMock.sol` | verified | |
| influxdb | `influxdb3_authz/src/role/role_defaults.rs` | verified | |
| grafana | `public/app/features/dashboard/components/TransformationsEditor/TransformationEditorHelpDisplay.tsx` | verified | |
| influxdb | `core/object_store_metrics/src/multipart_upload.rs` | verified | |
| go | `src/runtime/sys_darwin.go` | verified | |
| prysm | `validator/client/beacon-api/beacon_api_node_client.go` | verified | |
| influxdb | `core/arrow_util/src/lib.rs` | verified | |
| go | `src/math/big/floatmarsh.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/calibur/interfaces/IHook.sol` | verified | |
| grafana | `pkg/services/ngalert/state/historian/annotation.go` | verified | |
| grafana | `public/app/features/alerting/unified/insights/mimir/rules/MostFiredRules.tsx` | verified | |
| influxdb | `core/object_store_mem_cache/src/cache_system/s3_fifo_cache/ordered_set.rs` | verified | |
| go | `src/runtime/signal_netbsd.go` | verified | |
| go | `test/fixedbugs/issue19911.go` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/crosschain/optimism/LibOptimism.sol` | verified | |
| grafana | `packages/grafana-ui/src/components/Table/Cells/DefaultCell.tsx` | verified | |
| prysm | `beacon-chain/sync/validate_data_column_gloas_test.go` | verified | |
| go | `test/fixedbugs/issue11590.go` | verified | |
| influxdb | `core/iox_query/src/exec/gapfill/stream.rs` | verified | |
| influxdb | `influxdb3_load_generator/src/report.rs` | verified | |
| uniswap-contracts | `src/briefcase/protocols/universal-router-2_0/types/RouterParameters.sol` | verified | |
| prysm | `testing/spectest/mainnet/gloas__operations__withdrawal_request_test.go` | verified | |
| influxdb | `influxdb3_catalog/src/object_store/versions/v1.rs` | verified | |
| prysm | `beacon-chain/p2p/gossip_scoring_params.go` | verified | |
| uniswap-contracts | `script/cli/src/screens/shared/rpc_url.rs` | verified | |
| prysm | `consensus-types/interfaces/execution_payload_envelope.go` | verified | |
| go | `src/os/stat_freebsd.go` | verified | |
| influxdb | `core/iox_query/src/exec/series_limit/physical.rs` | verified | |
| go | `test/fixedbugs/issue43962.go` | verified | |
| grafana | `pkg/services/dashboardsnapshots/service/service_test.go` | verified | |
| prysm | `async/event/feed.go` | verified | |
| prysm | `cmd/prysmctl/db/cmd.go` | verified | |
| prysm | `beacon-chain/node/log.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v4-core/interfaces/IProtocolFees.sol` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/EIP712External.sol` | verified | |
| uniswap-contracts | `src/briefcase/protocols/uniswapx/v4/interfaces/IReactor.sol` | verified | |
