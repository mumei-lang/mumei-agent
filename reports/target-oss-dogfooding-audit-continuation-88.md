# Target OSS no-LLM dogfooding audit — continuation 88 (batch 89)

Run: 2026-07-21T22:52:16.243489+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required. Foundry script files (`.s.sol`) were excluded from this batch after one was sampled.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/internal/syscall/unix/net_darwin.go` | verified |  |
| influxdb | `core/jemalloc_stats/src/lib.rs` | verified |  |
| prysm | `config/features/flags.go` | verified |  |
| prysm | `time/slots/slotutil_test.go` | verified |  |
| grafana | `e2e-playwright/test-plugins/grafana-test-datasource/variables.ts` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/security/Pausable.sol` | verified |  |
| go | `test/fixedbugs/issue44732.dir/main.go` | verified |  |
| influxdb | `influxdb3_catalog/src/catalog/versions/v3/ops/mod.rs` | verified |  |
| go | `test/fixedbugs/bug222.dir/chanbug.go` | verified |  |
| influxdb | `core/influxdb2_client/src/common.rs` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/ERC20VotesMock.sol` | verified |  |
| grafana | `public/app/features/alerting/unified/triage/instance-details/InstanceDetailsDrawer.tsx` | verified |  |
| go | `src/log/slog/text_handler_test.go` | verified |  |
| prysm | `validator/keymanager/derived/keymanager_test.go` | verified |  |
| go | `src/simd/archsimd/internal/simd_test/shift_helpers_arm64_test.go` | verified |  |
| prysm | `testing/spectest/mainnet/capella__rewards__rewards_test.go` | verified |  |
| influxdb | `core/data_types/src/snapshot/namespace.rs` | verified |  |
| influxdb | `influxdb3_startup/src/early_logging.rs` | verified |  |
| go | `src/internal/sysinfo/cpuinfo_bsd.go` | verified |  |
| go | `test/fixedbugs/issue73916b.go` | verified |  |
| prysm | `testing/spectest/minimal/bellatrix__operations__execution_payload_test.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v4-core/interfaces/IPoolManager.sol` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v3-core/interfaces/pool/IUniswapV3PoolOwnerActions.sol` | verified |  |
| influxdb | `core/iox_v1_query_api/src/response.rs` | verified |  |
| prysm | `beacon-chain/p2p/testing/mock_listener.go` | verified |  |
| uniswap-contracts | `src/briefcase/deployers/util-contracts/FeeCollectorDeployer.sol` | verified |  |
| prysm | `beacon-chain/core/helpers/genesis.go` | verified |  |
| prysm | `testing/spectest/shared/deneb/fork/upgrade_to_deneb.go` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/ERC721VotesMock.sol` | verified |  |
| grafana | `pkg/login/social/connectors/generic_oauth.go` | verified |  |
| grafana | `pkg/services/apiserver/auth/authorizer/impersonation.go` | verified |  |
| prysm | `testing/spectest/shared/deneb/ssz_static/ssz_static.go` | verified |  |
| go | `src/cmd/compile/internal/typecheck/target.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/git/validator.go` | verified |  |
| influxdb | `influxdb3_commands/src/debug/catalog/list.rs` | verified |  |
| grafana | `packages/grafana-runtime/src/services/pluginSettings/mappers/v0alpha1SettingsMapper.ts` | verified |  |
| grafana | `public/app/features/dashboard/components/PublicDashboard/usePublicDashboardConfig.tsx` | verified |  |
| go | `test/fixedbugs/issue54638.go` | verified |  |
| influxdb | `core/influxdb2_client/src/models/health.rs` | verified |  |
| grafana | `public/app/features/explore/NoData.tsx` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v4-core/libraries/Lock.sol` | verified |  |
| influxdb | `core/influxdb_iox_client/src/client.rs` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v4-core/libraries/FixedPoint128.sol` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/permit2/libraries/Allowance.sol` | verified |  |
| go | `src/math/big/internal/asmgen/s390x.go` | verified |  |
| grafana | `packages/grafana-data/src/utils/csv.ts` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/token/ERC721/utils/ERC721Holder.sol` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/get_metric_query_batches_test.go` | verified |  |
| prysm | `crypto/bls/blst/public_key_test.go` | verified |  |
| influxdb | `core/predicate/src/rpc_predicate/value_rewrite.rs` | verified |  |
