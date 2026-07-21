# Target OSS no-LLM dogfooding audit — continuation 93 (batch 94)

Run: 2026-07-21T23:23:57.187040+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification.

- Solidity: constant exponentiation divisors such as ``(2**32)`` are recognized as compile-time non-zero.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| grafana | `pkg/tests/api/admin/encryption/reencrypt_enterprise_test.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v2-periphery/libraries/UniswapV2OracleLibrary.sol` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/lib-external/solady/src/utils/ECDSA.sol` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/calibur/libraries/PersonalSignLib.sol` | verified |  |
| influxdb | `influxdb3_wal/src/lib.rs` | verified |  |
| prysm | `validator/db/kv/backup.go` | verified |  |
| prysm | `beacon-chain/state/state-native/getters_block.go` | verified |  |
| prysm | `container/leaky-bucket/leakybucket.go` | verified |  |
| influxdb | `influxdb3_catalog/src/object_store/versions/mod.rs` | verified |  |
| prysm | `beacon-chain/core/altair/transition_test.go` | verified |  |
| go | `src/cmd/go/internal/vcs/discovery.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v4-periphery/libraries/Descriptor.sol` | verified |  |
| go | `test/fixedbugs/issue22904.go` | verified |  |
| prysm | `beacon-chain/p2p/peers/scorers/bad_responses_test.go` | verified |  |
| go | `test/abi/bad_internal_offsets.go` | verified |  |
| influxdb | `influxdb3_catalog/src/catalog/versions/v3/schema/role.rs` | verified |  |
| influxdb | `influxdb3/src/commands/create/token.rs` | verified |  |
| influxdb | `core/influxdb_iox_client/src/client/ingester.rs` | verified |  |
| influxdb | `influxdb3_catalog/src/catalog/versions/v3/schema/database.rs` | verified |  |
| uniswap-contracts | `script/cli/src/screens/shared/chain_id.rs` | verified |  |
| influxdb | `influxdb3_catalog/src/serialize.rs` | verified |  |
| go | `src/crypto/boring/boring_test.go` | verified |  |
| influxdb | `core/iox_v1_query_api/src/lib.rs` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/calibur/libraries/SignedBatchedCallLib.sol` | verified |  |
| grafana | `pkg/registry/apis/query/sql_schema.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v2-periphery/interfaces/IUniswapV2Router01.sol` | verified |  |
| grafana | `pkg/services/ssosettings/strategies/ldap_strategy.go` | verified |  |
| influxdb | `influxdb3/tests/server/plugin_restriction.rs` | verified |  |
| grafana | `apps/dashboard/pkg/migration/conversion/v2_to_v2alpha1.go` | verified |  |
| grafana | `packages/grafana-ui/src/components/ToolbarButton/ToolbarButton.tsx` | verified |  |
| go | `src/cmd/compile/internal/amd64/versions_nosimd_test.go` | verified |  |
| prysm | `testing/endtoend/components/eth1/node_set.go` | verified |  |
| prysm | `testing/spectest/mainnet/electra__epoch_processing__slashings_reset_test.go` | verified |  |
| go | `test/fixedbugs/issue19323.go` | verified |  |
| prysm | `beacon-chain/state/state-native/types/types.go` | verified |  |
| grafana | `public/app/features/plugins/admin/components/RoadmapLinks.tsx` | verified |  |
| prysm | `beacon-chain/core/signing/signing_root.go` | verified |  |
| grafana | `apps/plugins/pkg/app/meta/converter.go` | verified |  |
| go | `test/fixedbugs/issue52438.go` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/SafeMathMock.sol` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/token/ERC20/presets/ERC20PresetFixedSupply.sol` | verified |  |
| go | `src/runtime/minmax.go` | verified |  |
| prysm | `beacon-chain/p2p/partialdatacolumnbroadcaster/partial_test.go` | verified |  |
| go | `src/math/expm1.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v4-periphery/interfaces/IPermit2Forwarder.sol` | verified |  |
| grafana | `public/app/features/transformers/FilterByValueTransformer/ValueMatchers/valueMatchersUI.ts` | verified |  |
| grafana | `public/app/features/scopes/selector/useScopesHighlighting.tsx` | verified |  |
| influxdb | `core/iox_query/src/physical_optimizer/mod.rs` | verified |  |
| go | `test/import2.dir/import3.go` | verified |  |
| grafana | `pkg/services/store/types.go` | verified |  |
