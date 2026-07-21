# Target OSS no-LLM dogfooding audit — continuation 94 (batch 95)

Run: 2026-07-21T23:28:41.050234+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification.

- Go: ``error`` interface methods ``Error``/``Unwrap`` are recognized as non-nil receiver interface methods.
- Go: parallel slice indexing is safe when ``if len(a) != len(b) { return }`` precedes ``for i := range a { b[i] }``.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| uniswap-contracts | `src/briefcase/protocols/v3-periphery/interfaces/IV3Migrator.sol` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/team_createteammember_response_body_types_gen.go` | verified |  |
| prysm | `consensus-types/types.go` | verified |  |
| influxdb | `core/influxdb_iox_client/src/lib.rs` | verified |  |
| go | `src/cmd/go/internal/vcweb/script.go` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/GovernorMock.sol` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/universal-router/modules/uniswap/v3/V3Path.sol` | verified |  |
| go | `test/fixedbugs/bug489.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v4-hooks-public/interfaces/IWstETH.sol` | verified |  |
| influxdb | `influxdb3_catalog/src/catalog/migrations/mod.rs` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v4-hooks-public/aggregator-hooks/implementations/FluidDexLite/interfaces/IFluidDexLite.sol` | verified |  |
| grafana | `packages/grafana-ui/src/components/Cascader/optionMappings.ts` | verified |  |
| go | `test/codegen/schedule.go` | verified |  |
| prysm | `beacon-chain/blockchain/pow_block_test.go` | verified |  |
| go | `src/runtime/cgo/clearenv.go` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/AddressImpl.sol` | verified |  |
| go | `src/time/zoneinfo_unix.go` | verified |  |
| influxdb | `influxdb3_server/src/unified_service/service.rs` | verified |  |
| influxdb | `core/tracker/src/lib.rs` | verified |  |
| grafana | `public/app/core/components/AppChrome/FeatureControl/FeatureControlButton.tsx` | verified |  |
| go | `src/cmd/go/internal/load/pkg.go` | verified |  |
| prysm | `crypto/keystore/log.go` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/token/ERC777/ERC777.sol` | verified |  |
| grafana | `pkg/registry/apis/provisioning/informer/historicjob.go` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/token/ERC20/extensions/ERC20Burnable.sol` | verified |  |
| go | `src/go/types/typeterm_test.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/lib-external/openzeppelin-contracts/contracts/utils/math/Math.sol` | verified |  |
| prysm | `tools/keystores/main.go` | verified |  |
| go | `src/net/http/httputil/reverseproxy.go` | verified |  |
| prysm | `testing/spectest/mainnet/fulu__networking__custody_groups_test.go` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/token/ERC721/ERC721.sol` | verified |  |
| prysm | `testing/spectest/minimal/bellatrix__epoch_processing__slashings_test.go` | verified |  |
| influxdb | `core/data_types/src/snapshot/hash.rs` | verified |  |
| prysm | `beacon-chain/node/node_test.go` | verified |  |
| prysm | `beacon-chain/forkchoice/doubly-linked-tree/forkchoice.go` | verified |  |
| influxdb | `core/arrow_util/src/bitset.rs` | verified |  |
| influxdb | `influxdb3_commands/src/write.rs` | verified |  |
| grafana | `public/app/features/logs/components/fieldSelector/FieldList.tsx` | verified |  |
| influxdb | `influxdb3_server/src/all_paths.rs` | verified |  |
| grafana | `public/app/plugins/panel/trend/module.tsx` | verified |  |
| grafana | `pkg/login/social/connectors/social_base.go` | verified |  |
| grafana | `apps/advisor/pkg/app/checks/datasourcecheck/check_test.go` | verified |  |
| prysm | `beacon-chain/execution/mock_test.go` | verified |  |
| prysm | `beacon-chain/core/helpers/beacon_committee.go` | verified |  |
| grafana | `pkg/generated/applyconfiguration/internal/internal.go` | verified |  |
| influxdb | `core/influxdb_influxql_parser/src/show_tag_keys.rs` | verified |  |
| go | `src/os/executable_solaris.go` | verified |  |
| go | `src/internal/syscall/unix/kernel_version_solaris.go` | verified |  |
| grafana | `public/app/features/explore/hooks/useStateSync/synchronizer/toURL.ts` | verified |  |
| influxdb | `influxdb3/tests/server/configure.rs` | verified |  |
