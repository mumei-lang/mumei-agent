# Target OSS no-LLM dogfooding audit — continuation 47 (batch 48)

Run: 2026-07-21T12:01:31.808430+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All 50 sampled files passed no-LLM verification.

## Tool-side fixes in this batch

- Rust lifetime-qualified string references are now mapped to Mumei `string`, preventing spurious int-ensures lowering failures on string-literal returns.
- Go word-size constants `_W` and `bits.UintSize` are now treated as guaranteed non-zero, suppressing divide-by-zero false positives in low-level arithmetic helpers such as `addMulVVW1024`.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| uniswap-contracts | `lib/oz-v4.7.0/contracts/interfaces/IERC2981.sol` | verified | |
| prysm | `tools/analyzers/modernize/stringsseq/analyzer.go` | verified | |
| go | `src/net/rpc/server.go` | verified | |
| influxdb | `core/influxdb2_client/examples/label.rs` | verified | |
| uniswap-contracts | `script/cli/src/workflows/config/mod.rs` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/ERC1155BurnableMock.sol` | verified | |
| grafana | `apps/folder/pkg/apis/folder/v1/register.go` | verified | |
| uniswap-contracts | `src/briefcase/deployers/v3-periphery/QuoterV2Deployer.sol` | verified | |
| influxdb | `influxdb3_catalog/src/catalog/versions/v2/metrics.rs` | verified | |
| prysm | `testing/spectest/mainnet/gloas__epoch_processing__inactivity_updates_test.go` | verified | |
| influxdb | `core/query_functions/src/lib.rs` | verified | |
| go | `src/crypto/internal/fips140/bigmod/nat_wasm.go` | verified | |
| prysm | `beacon-chain/rpc/eth/rewards/testing/mock.go` | verified | |
| influxdb | `core/iox_http/src/write/single_tenant/mod.rs` | verified | |
| go | `test/fixedbugs/issue30908.go` | verified | |
| grafana | `public/app/features/alerting/unified/components/rule-viewer/tabs/version-history/useRestoreVersion.ts` | verified | |
| grafana | `pkg/storage/unified/search/vector/provider.go` | verified | |
| go | `src/crypto/elliptic/params.go` | verified | |
| grafana | `public/app/plugins/datasource/cloudwatch/components/shared/LogGroups/LogGroupQueryScopeSelector.tsx` | verified | |
| grafana | `public/app/features/alerting/unified/components/AlertEnrichments.tsx` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/GovernorCompMock.sol` | verified | |
| influxdb | `core/influxdb2_client/src/models/ast/variable_assignment.rs` | verified | |
| influxdb | `core/sharder/src/round_robin.rs` | verified | |
| influxdb | `influxdb3_system_tables/src/tokens.rs` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v4-core/interfaces/external/IERC20Minimal.sol` | verified | |
| grafana | `public/app/plugins/datasource/grafana-postgresql-datasource/datasource.ts` | verified | |
| grafana | `public/app/core/internationalization/constants.ts` | verified | |
| influxdb | `core/iox_query/src/physical_optimizer/limits.rs` | verified | |
| go | `test/fixedbugs/issue27267.go` | verified | |
| grafana | `public/app/features/dashboard-scene/settings/DeleteDashboardButton.tsx` | verified | |
| prysm | `beacon-chain/state/state-native/getters_gloas.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v4-hooks-public/aggregator-hooks/implementations/UniswapV2/interfaces/IUniswapV2Pair.sol` | verified | |
| prysm | `validator/client/payload_availability.go` | verified | |
| prysm | `testing/spectest/minimal/altair__operations__block_header_test.go` | verified | |
| uniswap-contracts | `lib/oz-v3.4-solc-0.7/contracts/cryptography/ECDSA.sol` | verified | |
| uniswap-contracts | `src/briefcase/deployers/universal-router/UniversalRouterDeployer.sol` | verified | |
| go | `test/fixedbugs/issue61778.go` | verified | |
| prysm | `validator/db/kv/kv_test.go` | verified | |
| grafana | `packages/grafana-ui/src/components/Forms/Legacy/Select/IndicatorsContainer.tsx` | verified | |
| go | `test/fixedbugs/issue6140.go` | verified | |
| influxdb | `influxdb3_types/src/arrow_limits/mod.rs` | verified | |
| prysm | `validator/client/payload_attestation.go` | verified | |
| influxdb | `core/object_store_mem_cache/src/cache_system/reactor/mod.rs` | verified | |
| go | `test/codegen/memcse.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/calibur/libraries/KeyLib.sol` | verified | |
| go | `test/fixedbugs/issue44355.dir/a.go` | verified | |
| go | `test/ken/cplx3.go` | verified | |
| prysm | `testing/spectest/shared/bellatrix/epoch_processing/randao_mixes_reset.go` | verified | |
| prysm | `testing/spectest/shared/fulu/operations/proposer_slashing.go` | verified | |
| grafana | `public/app/plugins/panel/logstable/hooks/useOrganizeFields.tsx` | verified | |
