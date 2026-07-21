# Target OSS no-LLM dogfooding audit — continuation 45 (batch 46)

Run: 2026-07-21T11:37:12.681029+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All 50 sampled files passed no-LLM verification.

## Tool-side fixes in this batch

- Solidity >=0.8 default division/modulo-by-zero checks are now respected; no spurious non-zero contract is required for `div`/`mod` without explicit `require`.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| grafana | `pkg/services/ngalert/models/admin_configuration.go` | verified | |
| influxdb | `core/influxdb_influxql_parser/src/show.rs` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v4-periphery/libraries/ActionConstants.sol` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/interfaces/IERC777Sender.sol` | verified | |
| grafana | `pkg/services/ngalert/notifier/legacy_storage/testing.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v3-periphery/interfaces/IPoolInitializer.sol` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/utils/math/SignedSafeMath.sol` | verified | |
| prysm | `beacon-chain/operations/slashings/pool.go` | verified | |
| go | `src/cmd/compile/internal/inline/inlheur/eclassify.go` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/ERC1271WalletMock.sol` | verified | |
| prysm | `validator/graffiti/parse_graffiti.go` | verified | |
| go | `src/internal/goarch/goarch_arm.go` | verified | |
| prysm | `validator/client/beacon-api/doppelganger_test.go` | verified | |
| grafana | `apps/dashvalidator/pkg/validator/prometheus/parser.go` | verified | |
| go | `src/cmd/compile/internal/ssa/sccp.go` | verified | |
| grafana | `pkg/util/tls_test.go` | verified | |
| grafana | `pkg/storage/unified/search/embed/embedder/batch_embedder_test.go` | verified | |
| go | `src/cmd/internal/buildid/rewrite.go` | verified | |
| influxdb | `influxdb3_commands/src/query.rs` | verified | |
| prysm | `beacon-chain/p2p/peers/scorers/service_test.go` | verified | |
| influxdb | `core/influxdb_influxql_parser/src/keywords.rs` | verified | |
| grafana | `apps/provisioning/pkg/repository/github/validator.go` | verified | |
| influxdb | `core/catalog_cache/src/api/quorum.rs` | verified | |
| go | `src/maps/maps.go` | verified | |
| influxdb | `influxdb3_catalog/src/snapshot/versions/v1/conversion.rs` | verified | |
| grafana | `public/app/plugins/panel/timeseries/plugins/ExemplarMarker.tsx` | verified | |
| uniswap-contracts | `script/cli/src/errors.rs` | verified | |
| grafana | `public/app/features/dashboard/components/PanelEditor/state/actions.ts` | verified | |
| go | `src/runtime/vdso_linux_arm64.go` | verified | |
| prysm | `consensus-types/light-client/header.go` | verified | |
| influxdb | `core/linear_buffer/src/linear_buffer.rs` | verified | |
| grafana | `public/app/plugins/panel/logstable/fields/logs.ts` | verified | |
| uniswap-contracts | `script/util/process_briefcase_files.py` | verified | |
| prysm | `beacon-chain/blockchain/receive_execution_payload_envelope.go` | verified | |
| influxdb | `core/parquet_file/src/lib.rs` | verified | |
| influxdb | `influxdb3_processing_engine/src/tests.rs` | verified | |
| prysm | `proto/engine/v1/export_test.go` | verified | |
| prysm | `testing/spectest/minimal/deneb__epoch_processing__inactivity_updates_test.go` | verified | |
| influxdb | `core/iox_query_influxql/src/frontend/mod.rs` | verified | |
| go | `src/runtime/os_linux_noauxv.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v2-core/libraries/UQ112x112.sol` | verified | |
| go | `src/strings/reader_test.go` | verified | |
| influxdb | `core/query_functions/src/gapfill.rs` | verified | |
| go | `test/fixedbugs/issue59334.go` | verified | |
| prysm | `beacon-chain/sync/validate_execution_payload_bid_test.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v4-hooks-public/aggregator-hooks/implementations/UniswapV3/interfaces/IUniswapV3SwapCallback.sol` | verified | |
| grafana | `public/app/features/alerting/unified/rule-list/DataSourceRuleListItem.tsx` | verified | |
| go | `src/cmd/cover/testdata/test.go` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/utils/escrow/RefundEscrow.sol` | verified | |
| prysm | `proto/prysm/v1alpha1/validator.go` | verified | |
