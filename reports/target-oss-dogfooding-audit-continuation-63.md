# Target OSS no-LLM dogfooding audit — continuation 63 (batch 64)

Run: 2026-07-21T14:12:31.652539+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All 50 sampled files passed no-LLM verification.

## Tool-side fixes in this batch

- Go runtime: treat ``pageSize``/``pallocChunkBytes``/``pallocChunkPages`` as non-zero constants and ``level`` indexing ``levelShift`` as bounds-safe.
- Go: treat ``*FooAlloc`` receivers as non-nil containers (e.g. ``runtime.pageAlloc``).

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `test/typeparam/metrics.go` | verified | |
| go | `src/runtime/mpagealloc.go` | verified | |
| prysm | `testing/spectest/shared/phase0/operations/deposit.go` | verified | |
| prysm | `testing/spectest/minimal/gloas__epoch_processing__slashings_reset_test.go` | verified | |
| grafana | `public/app/features/expressions/components/SqlExpressions/SqlEditor/completionSituation.ts` | verified | |
| grafana | `apps/annotation/pkg/apis/annotation/v0alpha1/creategraphite_response_object_types_gen.go` | verified | |
| prysm | `consensus-types/primitives/kzg.go` | verified | |
| grafana | `pkg/apimachinery/utils/meta_mock.go` | verified | |
| grafana | `public/app/features/alerting/unified/rule-list/ruleMatching.ts` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/governance/extensions/GovernorPreventLateQuorum.sol` | verified | |
| grafana | `pkg/infra/kvstore/sql.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v4-core/libraries/StateLibrary.sol` | verified | |
| uniswap-contracts | `src/briefcase/protocols/calibur/interfaces/IERC7914.sol` | verified | |
| go | `src/syscall/zsysnum_freebsd_arm.go` | verified | |
| prysm | `beacon-chain/core/feed/state/events.go` | verified | |
| prysm | `beacon-chain/rpc/eth/shared/testing/json_mainnet.go` | verified | |
| go | `test/fixedbugs/issue22351.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/lib-external/openzeppelin-contracts/contracts/utils/Panic.sol` | verified | |
| influxdb | `influxdb3/src/commands/create.rs` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v4-periphery/libraries/SVG.sol` | verified | |
| go | `src/crypto/internal/fips140/nistec/_asm/p256_asm.go` | verified | |
| influxdb | `influxdb3/tests/server/ping.rs` | verified | |
| go | `src/cmd/go/internal/imports/testdata/illumos/g.go` | verified | |
| prysm | `beacon-chain/sync/subscriber_signed_proposer_preferences.go` | verified | |
| influxdb | `influxdb3_catalog/src/channel.rs` | verified | |
| grafana | `public/app/plugins/datasource/influxdb/webpack.config.ts` | verified | |
| go | `test/ken/ptrfun.go` | verified | |
| influxdb | `core/tracker/src/task/registry.rs` | verified | |
| prysm | `beacon-chain/node/shutdown_proposals.go` | verified | |
| go | `src/internal/types/testdata/fixedbugs/issue51139.go` | verified | |
| influxdb | `influxdb3_wal/src/serialize.rs` | verified | |
| uniswap-contracts | `script/cli/src/workflows/verify/verify_contract.rs` | verified | |
| influxdb | `influxdb3_catalog/src/snapshot/versions/mod.rs` | verified | |
| influxdb | `core/iox_query/src/exec/gapfill/params.rs` | verified | |
| go | `test/fixedbugs/bug479.dir/a.go` | verified | |
| influxdb | `core/object_store_mem_cache/src/cache_system/reactor/reaction.rs` | verified | |
| influxdb | `influxdb3_commands/src/disable.rs` | verified | |
| prysm | `proto/prysm/v1alpha1/data_columns.pb.go` | verified | |
| uniswap-contracts | `src/briefcase/deployers/v3-periphery/NFTDescriptorDeployer.sol` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v4-core/libraries/CurrencyReserves.sol` | verified | |
| go | `src/cmd/cgo/internal/testshared/testdata/issue62277/p/p.go` | verified | |
| grafana | `pkg/apiserver/registry/generic/store.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v3-core/libraries/Tick.sol` | verified | |
| prysm | `beacon-chain/slasher/chunks_test.go` | verified | |
| grafana | `public/app/features/alerting/unified/components/contact-points/utils.ts` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/token/ERC20/presets/ERC20PresetMinterPauser.sol` | verified | |
| grafana | `public/app/plugins/panel/geomap/editor/StyleEditor.tsx` | verified | |
| influxdb | `influxdb3_catalog/src/snapshot/versions/v3.rs` | verified | |
| grafana | `apps/quotas/pkg/apis/quotas/v0alpha1/getusage_request_params_types_gen.go` | verified | |
| prysm | `beacon-chain/core/epoch/epoch_processing.go` | verified | |
