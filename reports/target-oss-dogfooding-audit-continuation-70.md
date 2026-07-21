# Target OSS no-LLM dogfooding audit — continuation 70 (batch 71)

Run: 2026-07-21T14:46:55.371084+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification.

## Tool-side fixes in this batch

- Go: treat `Fake*` generated test-double receivers/parameters as non-nil.
- Go: infer `string` return type when a function with an integer-typed named return type returns a string literal (e.g. `backendplugin.Target`).

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| influxdb | `core/influxdb2_client/src/models/mod.rs` | verified |  |
| prysm | `beacon-chain/core/transition/state.go` | verified |  |
| influxdb | `core/influxdb_iox_client/src/client/delete.rs` | verified |  |
| prysm | `beacon-chain/core/altair/epoch_spec.go` | verified |  |
| grafana | `pkg/registry/apps/shorturl/migrator/migrator_test.go` | verified |  |
| grafana | `pkg/services/authapi/fake/authapistub.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v4-hooks-public/utils/HookMiner.sol` | verified |  |
| go | `src/math/big/intmarsh_test.go` | verified |  |
| prysm | `testing/spectest/mainnet/deneb__epoch_processing__registry_updates_test.go` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/EtherReceiverMock.sol` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v3-core/libraries/SwapMath.sol` | verified |  |
| grafana | `packages/grafana-data/src/datetime/moment_wrapper.ts` | verified |  |
| prysm | `validator/db/filesystem/proposer_settings.go` | verified |  |
| prysm | `beacon-chain/execution/payload_body_test.go` | verified |  |
| grafana | `pkg/plugins/manager/pluginfakes/fakes.go` | verified |  |
| prysm | `crypto/bls/blst/init.go` | verified |  |
| prysm | `testing/spectest/shared/altair/epoch_processing/eth1_data_reset.go` | verified |  |
| influxdb | `influxdb3/tests/server/system_tables.rs` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/OwnableMock.sol` | verified |  |
| influxdb | `core/partition/src/traits.rs` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v4-periphery/libraries/BipsLibrary.sol` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v4-core/libraries/Pool.sol` | verified |  |
| prysm | `beacon-chain/state/stategen/mock/replayer.go` | verified |  |
| go | `src/runtime/os_freebsd_arm64.go` | verified |  |
| go | `test/typeparam/lockable.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/rewriteARM64.go` | verified |  |
| go | `src/internal/strconv/export_test.go` | verified |  |
| prysm | `validator/client/beacon-api/sync_committee_selections_test.go` | verified |  |
| grafana | `apps/provisioning/pkg/connection/github/factory_test.go` | verified |  |
| go | `src/net/http/jar.go` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/getPanelFrameOptions.tsx` | verified |  |
| influxdb | `core/object_store_mem_cache/src/buffer_channel.rs` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/ERC165/ERC165NotSupported.sol` | verified |  |
| grafana | `public/app/plugins/panel/news/useNewsFeed.tsx` | verified |  |
| go | `test/nilptr2.go` | verified |  |
| influxdb | `core/influxdb_iox_client/src/client/query_log.rs` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/ERC20DecimalsMock.sol` | verified |  |
| influxdb | `influxdb3/tests/cli/db_retention.rs` | verified |  |
| grafana | `pkg/services/libraryelements/api_test.go` | verified |  |
| influxdb | `influxdb3_authz/src/permissions.rs` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v2-core/interfaces/IUniswapV2Factory.sol` | verified |  |
| prysm | `testing/spectest/mainnet/capella__ssz_static__ssz_static_test.go` | verified |  |
| go | `src/os/signal/signal_cgo_test.go` | verified |  |
| go | `src/io/example_test.go` | verified |  |
| go | `test/typeparam/issue49309.go` | verified |  |
| influxdb | `core/sharder/src/lib.rs` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/ERC721URIStorageMock.sol` | verified |  |
| grafana | `pkg/services/anonymous/anonimpl/anonstore/fake.go` | verified |  |
| grafana | `pkg/services/live/pipeline/frame_output_remote_write_test.go` | verified |  |
| influxdb | `core/table_batch/src/builder/mod.rs` | verified |  |
