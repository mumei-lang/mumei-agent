# Target OSS no-LLM dogfooding audit — continuation 44 (batch 45)

Run: 2026-07-21T11:32:23.965137+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All 50 sampled files passed no-LLM verification.

## Tool-side fixes in this batch

- Solidity >=0.8 default division/modulo-by-zero checks are now respected; no spurious non-zero contract is required.
- No-LLM dogfooding samples now exclude C/C++/Java files and test/spec/story files, avoiding unsupported or test-only sources.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `test/typeparam/issue53762.go` | verified | |
| prysm | `testing/spectest/shared/deneb/epoch_processing/randao_mixes_reset.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v4-core/libraries/TransientStateLibrary.sol` | verified | |
| grafana | `apps/provisioning/pkg/repository/github/connection_webhook_validator.go` | verified | |
| go | `src/structs/hostlayout.go` | verified | |
| grafana | `pkg/tsdb/cloudwatch/log_query_test.go` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/interfaces/IERC165.sol` | verified | |
| prysm | `validator/helpers/converts_test.go` | verified | |
| grafana | `packages/grafana-test-utils/src/handlers/apis/folder.grafana.app/v1beta1/handlers.ts` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v4-hooks-public/aggregator-hooks/implementations/UniswapV2/interfaces/IUniswapV2Factory.sol` | verified | |
| prysm | `testing/assert/assertions.go` | verified | |
| prysm | `encoding/bytesutil/integers_test.go` | verified | |
| go | `src/simd/archsimd/slicepart_amd64.go` | verified | |
| grafana | `public/app/features/logs/components/panel/links.ts` | verified | |
| go | `src/math/log1p.go` | verified | |
| go | `src/cmd/go/internal/modfetch/codehost/vcs.go` | verified | |
| grafana | `pkg/services/ldap/multildap/multidap_mock.go` | verified | |
| go | `src/maps/iter_test.go` | verified | |
| influxdb | `core/object_store_mem_cache/src/cache_system/loader.rs` | verified | |
| influxdb | `influxdb3_types/src/write/tests.rs` | verified | |
| influxdb | `influxdb3_server/tests/lib.rs` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/governance/extensions/GovernorProposalThreshold.sol` | verified | |
| influxdb | `core/catalog_cache/src/api/server.rs` | verified | |
| grafana | `apps/logsdrilldown/plugin/src/generated/logsdrilldowndefaultlabels/v1beta1/logsdrilldowndefaultlabels_object_gen.ts` | verified | |
| influxdb | `core/catalog_cache/benches/list_encode.rs` | verified | |
| prysm | `beacon-chain/state/stateutil/execution_payload_availability_root.go` | verified | |
| prysm | `beacon-chain/state/stateutil/reference_bench_test.go` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/interfaces/IERC1820Registry.sol` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v4-periphery/interfaces/IPoolInitializer_v4.sol` | verified | |
| go | `test/fixedbugs/bug498.go` | verified | |
| go | `test/fixedbugs/issue6703y.go` | verified | |
| prysm | `testing/spectest/shared/fulu/operations/deposit_request.go` | verified | |
| uniswap-contracts | `script/MineWETHHookSalt.s.sol` | verified | |
| influxdb | `influxdb3/src/main.rs` | verified | |
| influxdb | `influxdb3_catalog/src/catalog/versions/v3/ops/role.rs` | verified | |
| prysm | `validator/keymanager/remote-web3signer/keymanager.go` | verified | |
| influxdb | `core/influxdb2_client/src/models/ast/member_expression.rs` | verified | |
| grafana | `pkg/services/sqlstore/migrations/accesscontrol/datasource_type_migrator.go` | verified | |
| go | `test/fixedbugs/issue10332.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/lib-external/openzeppelin-contracts/contracts/utils/Base64.sol` | verified | |
| influxdb | `core/tracker/src/task/future.rs` | verified | |
| go | `src/hash/marshal_test.go` | verified | |
| grafana | `pkg/plugins/pluginassets/testdata/module-hash-valid-nested/panels/one/module.js` | verified | |
| prysm | `testing/spectest/mainnet/bellatrix__operations__attester_slashing_test.go` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/utils/introspection/IERC1820Registry.sol` | verified | |
| prysm | `internal/logrusadapter/adapter.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v3-periphery/interfaces/ITickLens.sol` | verified | |
| grafana | `public/app/core/components/Select/FolderPicker.tsx` | verified | |
| influxdb | `core/predicate/src/rpc_predicate/rewrite.rs` | verified | |
| grafana | `pkg/components/imguploader/localuploader_test.go` | verified | |
