# Target OSS no-LLM dogfooding audit — continuation 61 (batch 62)

Run: 2026-07-21T14:03:48.548530+00:00

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
| go | `test/fixedbugs/bug247.go` | verified | |
| go | `src/net/http/pprof/testdata/delta_mutex.go` | verified | |
| prysm | `encoding/bytesutil/eth_types.go` | verified | |
| prysm | `validator/client/beacon-api/status_test.go` | verified | |
| influxdb | `core/influxdb_influxql_parser/src/functions.rs` | verified | |
| uniswap-contracts | `src/briefcase/deployers/v4-periphery/PositionManagerDeployer.sol` | verified | |
| go | `src/strings/search.go` | verified | |
| influxdb | `influxdb3_catalog/src/snapshot/versions/v1.rs` | verified | |
| prysm | `genesis/internal/embedded/lookup.go` | verified | |
| grafana | `public/app/plugins/panel/timeseries/LineStyleEditor.tsx` | verified | |
| grafana | `pkg/services/pluginsintegration/loader/loader_test.go` | verified | |
| grafana | `pkg/registry/apis/provisioning/jobs/sync/sync_test.go` | verified | |
| grafana | `pkg/services/serviceaccounts/extsvcaccounts/models.go` | verified | |
| uniswap-contracts | `lib/oz-v3.4-solc-0.7/contracts/token/ERC721/ERC721.sol` | verified | |
| uniswap-contracts | `script/cli/src/screens/deploy_contracts/mod.rs` | verified | |
| go | `src/runtime/signal_openbsd_arm.go` | verified | |
| go | `test/recover4.go` | verified | |
| go | `test/utf.go` | verified | |
| prysm | `runtime/tos/tos_test.go` | verified | |
| grafana | `pkg/tests/apis/provisioning/jobs/export_folders_flag_disabled_test.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v4-core/libraries/TickMath.sol` | verified | |
| go | `test/func2.go` | verified | |
| influxdb | `core/iox_query_influxql/src/plan/mod.rs` | verified | |
| grafana | `public/app/features/sandbox/BenchmarksPage.tsx` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/utils/cryptography/ECDSA.sol` | verified | |
| influxdb | `influxdb3_catalog/src/enterprise/format/records/retention.rs` | verified | |
| prysm | `testing/spectest/minimal/electra__operations__block_header_test.go` | verified | |
| prysm | `api/rest/rest_handler_test.go` | verified | |
| grafana | `scripts/codeowners-manifest/utils.js` | verified | |
| influxdb | `core/iox_query_influxql/src/lib.rs` | verified | |
| influxdb | `influxdb3_catalog/src/format/records/mod.rs` | verified | |
| influxdb | `core/mutable_batch/src/payload.rs` | verified | |
| go | `src/cmd/internal/osinfo/os_wasip1.go` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/proxy/Proxy.sol` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/token/ERC721/extensions/IERC721Metadata.sol` | verified | |
| uniswap-contracts | `script/cli/src/workflows/deploy/deploy_contracts.rs` | verified | |
| go | `src/internal/runtime/sys/sys.go` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/ERC1155Mock.sol` | verified | |
| prysm | `testing/bls/deserialization_G1_test.go` | verified | |
| grafana | `packages/grafana-ui/src/components/Table/ActionsCell.tsx` | verified | |
| go | `test/typeparam/issue47877.go` | verified | |
| prysm | `beacon-chain/p2p/pubsub_tracer.go` | verified | |
| grafana | `pkg/tsdb/mysql/proxy_test.go` | verified | |
| prysm | `validator/client/grpc-api/grpc_node_client_test.go` | verified | |
| influxdb | `core/authz/src/authorization.rs` | verified | |
| prysm | `config/params/config_utils_develop.go` | verified | |
| influxdb | `core/tower_trailer/src/lib.rs` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/proxy/beacon/BeaconProxy.sol` | verified | |
| influxdb | `influxdb3_catalog/src/format/records/token.rs` | verified | |
| grafana | `pkg/services/correlations/accesscontrol.go` | verified | |
