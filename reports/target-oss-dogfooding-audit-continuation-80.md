# Target OSS no-LLM dogfooding audit — continuation 80 (batch 81)

Run: 2026-07-21T22:28:25.497972+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| influxdb | `core/trace_exporters/src/jaeger/span.rs` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/token/ERC721/ERC721.sol` | verified |  |
| prysm | `runtime/messagehandler/log.go` | verified |  |
| uniswap-contracts | `script/cli/src/screens/shared/generic_select.rs` | verified |  |
| grafana | `public/app/features/dashboard-scene/mutation-api/commands/addVariable.ts` | verified |  |
| prysm | `proto/prysm/v1alpha1/attestation/aggregation/testing/bitlistutils.go` | verified |  |
| go | `test/fixedbugs/issue43962.dir/b.go` | verified |  |
| influxdb | `influxdb3_cache/src/lib.rs` | verified |  |
| influxdb | `core/influxdb2_client/src/api/buckets.rs` | verified |  |
| prysm | `beacon-chain/rpc/prysm/v1alpha1/validator/proposer_deposits_test.go` | verified |  |
| influxdb | `influxdb3_sys_events/src/lib.rs` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/permit2/interfaces/ISignatureTransfer.sol` | verified |  |
| prysm | `testing/spectest/minimal/capella__epoch_processing__slashings_test.go` | verified |  |
| grafana | `pkg/services/dashboards/service/client/metrics.go` | verified |  |
| go | `src/runtime/os_linux_arm64.go` | verified |  |
| grafana | `pkg/services/ngalert/sender/sender.go` | verified |  |
| go | `src/io/fs/stat_test.go` | verified |  |
| influxdb | `core/mutable_batch/tests/writer_fuzz.rs` | verified |  |
| grafana | `public/app/features/alerting/unified/hooks/useGenericSavedSearches.ts` | verified |  |
| go | `src/runtime/pprof/defs_darwin.go` | verified |  |
| influxdb | `core/influxdb_influxql_parser/src/identifier.rs` | verified |  |
| grafana | `public/app/core/components/SharedPreferences/utils.ts` | verified |  |
| influxdb | `core/iox_query/src/pruning_oracle.rs` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v4-core/types/Currency.sol` | verified |  |
| prysm | `config/params/configset.go` | verified |  |
| grafana | `public/app/features/datasources/components/picker/DataSourceLogo.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/TableNG/legacy/LegacyTableNG.tsx` | verified |  |
| go | `src/encoding/gob/doc.go` | verified |  |
| influxdb | `core/trogging/src/lib.rs` | verified |  |
| prysm | `beacon-chain/core/helpers/block.go` | verified |  |
| prysm | `validator/keymanager/types_test.go` | verified |  |
| influxdb | `influxdb3_catalog/src/log/versions/v2/conversion.rs` | verified |  |
| go | `src/testing/example.go` | verified |  |
| go | `test/fixedbugs/issue49767.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v3-periphery/interfaces/IERC721Permit.sol` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/governance/extensions/GovernorVotesQuorumFraction.sol` | verified |  |
| prysm | `testing/spectest/minimal/capella__epoch_processing__justification_and_finalization_test.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/calibur/interfaces/ICalibur.sol` | verified |  |
| prysm | `consensus-types/primitives/committee_bits_minimal.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v3-core/interfaces/pool/IUniswapV3PoolDerivedState.sol` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/PullPaymentMock.sol` | verified |  |
| prysm | `beacon-chain/verification/data_column.go` | verified |  |
| go | `test/typeparam/issue51233.go` | verified |  |
| grafana | `pkg/tsdb/influxdb/settings.go` | verified |  |
| influxdb | `core/test_helpers_authz/src/authz.rs` | verified |  |
| grafana | `pkg/services/pluginsintegration/pluginstore/plugins_test.go` | verified |  |
| go | `src/crypto/internal/fips140deps/fipsdeps_test.go` | verified |  |
| grafana | `pkg/tsdb/influxdb/standalone/main.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/lib-external/solidity-lib/contracts/libraries/FixedPoint.sol` | verified |  |
| go | `src/syscall/fs_wasip1_test.go` | verified |  |
