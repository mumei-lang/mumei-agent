# Target OSS no-LLM dogfooding audit — continuation 67 (batch 68)

Run: 2026-07-21T14:26:30.747898+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0
- Files with non-atom warnings: 1

All sampled files passed no-LLM verification.

## Notes

- `src/internal/types/testdata/fixedbugs/issue64704.go`: No Mumei atoms were generated from the extracted forge task spec.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| influxdb | `core/object_store_mem_cache/src/cache_system/hook/notify/test_utils.rs` | verified |  |
| go | `test/fixedbugs/issue27289.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/swap-router-contracts/interfaces/IMixedRouteQuoterV1.sol` | verified |  |
| go | `src/cmd/compile/internal/ssa/rewrite386splitload.go` | verified |  |
| influxdb | `core/authz/src/instrumentation.rs` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v3-core/interfaces/IUniswapV3Pool.sol` | verified |  |
| influxdb | `influxdb3_catalog/src/catalog/versions/v3/schema/query_group.rs` | verified |  |
| prysm | `validator/client/beacon-api/prepare_beacon_proposer_test.go` | verified |  |
| go | `src/net/ip_test.go` | verified |  |
| grafana | `pkg/expr/mathexp/resample_test.go` | verified |  |
| prysm | `testing/spectest/shared/gloas/sanity/block_processing.go` | verified |  |
| prysm | `testing/spectest/shared/deneb/operations/voluntary_exit.go` | verified |  |
| go | `src/internal/types/testdata/fixedbugs/issue64704.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `test/codegen/clobberdeadreg.go` | verified |  |
| prysm | `beacon-chain/blockchain/service_test.go` | verified |  |
| influxdb | `core/metric_exporters/src/lib.rs` | verified |  |
| influxdb | `core/iox_query/src/exec.rs` | verified |  |
| influxdb | `core/predicate/src/lib.rs` | verified |  |
| go | `src/index/suffixarray/example_test.go` | verified |  |
| prysm | `beacon-chain/core/blocks/exit_test.go` | verified |  |
| influxdb | `core/iox_v1_query_api/src/response/chunked.rs` | verified |  |
| prysm | `proto/prysm/v1alpha1/log.go` | verified |  |
| prysm | `beacon-chain/operations/attestations/kv/block.go` | verified |  |
| influxdb | `core/influxdb_iox_client/src/client/table.rs` | verified |  |
| grafana | `pkg/tests/api/admin/encryption/reencrypt_test.go` | verified |  |
| uniswap-contracts | `src/briefcase/deployers/mixed-quoter/MixedRouteQuoterV2Deployer.sol` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/alert-rule-form/simplifiedRouting/contactPoint/ContactPointSelector.tsx` | verified |  |
| grafana | `apps/provisioning/pkg/apis/provisioning/v0alpha1/health.go` | verified |  |
| grafana | `public/app/features/plugins/loader/types.ts` | verified |  |
| influxdb | `core/parquet_file/src/metadata.rs` | verified |  |
| influxdb | `influxdb3_commands/src/common.rs` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/uniswapx/v4/interfaces/IAuctionResolver.sol` | verified |  |
| go | `src/internal/syscall/unix/syscall.go` | verified |  |
| prysm | `beacon-chain/core/altair/attestation_test.go` | verified |  |
| prysm | `config/params/config_utils_prod.go` | verified |  |
| grafana | `packages/grafana-ui/src/types/jquery.d.ts` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/utils/Arrays.sol` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/interfaces/draft-IERC1822.sol` | verified |  |
| go | `src/crypto/internal/fips140/hmac/cast.go` | verified |  |
| grafana | `public/app/features/provisioning/hooks/useCreateOrUpdateRepository.ts` | verified |  |
| grafana | `packages/grafana-ui/src/utils/storybook/ExampleFrame.tsx` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/SignedSafeMathMock.sol` | verified |  |
| go | `src/cmd/go/internal/workcmd/use.go` | verified |  |
| grafana | `public/app/features/alerting/unified/hooks/useIsRuleEditable.ts` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v3-periphery/libraries/BytesLib.sol` | verified |  |
| grafana | `public/app/features/explore/Logs/utils/LogsCrossFadeTransition.tsx` | verified |  |
| prysm | `network/httputil/errors.go` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/ERC20VotesCompMock.sol` | verified |  |
| uniswap-contracts | `script/cli/src/workflows/mod.rs` | verified |  |
| go | `test/fixedbugs/issue16133.dir/c.go` | verified |  |
