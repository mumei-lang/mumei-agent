# Target OSS no-LLM dogfooding audit — continuation 56 (batch 57)

Run: 2026-07-21T13:44:18.735134+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All 50 sampled files passed no-LLM verification.

## Tool-side fixes in this batch

- Go: treat cryptographic key types (``PublicKey``/``PrivateKey``) and ``big.Int`` as non-nil container parameters.
- Go: fix parameter-type parsing for grouped declarations (``a, b *T``) so the leftmost identifier also receives the trailing type.
- Go: suppress nil-deref false positives for ``crypto.PublicKey``/``crypto.PrivateKey`` ``Equal`` interface methods.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| influxdb | `core/client_util/src/connection.rs` | verified | |
| prysm | `testing/endtoend/evaluators/data.go` | verified | |
| grafana | `pkg/storage/unified/search/bleve_integration_test.go` | verified | |
| prysm | `validator/client/log_test.go` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/token/ERC1155/IERC1155Receiver.sol` | verified | |
| go | `test/linkname.go` | verified | |
| grafana | `pkg/registry/apis/provisioning/jobs/migrate/exported_resource_collector_test.go` | verified | |
| go | `test/fixedbugs/issue19040.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v4-periphery/interfaces/IMulticall_v4.sol` | verified | |
| influxdb | `core/iox_query/src/exec/context.rs` | verified | |
| go | `src/cmd/link/internal/ld/dwarf.go` | verified | |
| prysm | `testing/util/electra_state.go` | verified | |
| influxdb | `influxdb3_catalog/src/format/records/role.rs` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/ClonesMock.sol` | verified | |
| influxdb | `influxdb3_commands/src/enable.rs` | verified | |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/dashboard/v2/baseAPI.ts` | verified | |
| go | `test/fixedbugs/bug290.go` | verified | |
| go | `src/encoding/xml/read.go` | verified | |
| grafana | `pkg/services/auth/jwt/auth_test.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v2-periphery/libraries/UniswapV2LiquidityMathLibrary.sol` | verified | |
| grafana | `public/app/features/alerting/unified/insights/grafana/AlertsByStateScene.tsx` | verified | |
| go | `test/fixedbugs/issue56778.dir/a.go` | verified | |
| influxdb | `core/query_functions/src/date_bin_wallclock.rs` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v3-periphery/libraries/CallbackValidation.sol` | verified | |
| grafana | `apps/plugins/pkg/app/meta/catalog_test.go` | verified | |
| prysm | `tools/analyzers/shadowpredecl/analyzer.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/swap-router-contracts/interfaces/IApproveAndCall.sol` | verified | |
| go | `test/fixedbugs/issue10958.go` | verified | |
| influxdb | `core/arrow_util/src/optimize.rs` | verified | |
| influxdb | `core/partition/src/traits/record_batch.rs` | verified | |
| prysm | `testing/spectest/mainnet/capella__fork_helper__upgrade_to_capella_test.go` | verified | |
| go | `test/fixedbugs/issue4847.go` | verified | |
| go | `src/log/slog/logger_test.go` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/token/ERC20/extensions/ERC20VotesComp.sol` | verified | |
| prysm | `testing/spectest/minimal/capella__light_client__single_merkle_proof_test.go` | verified | |
| prysm | `tools/nogo_config/hack.go` | verified | |
| grafana | `pkg/infra/nats/server_test.go` | verified | |
| prysm | `beacon-chain/blockchain/receive_payload_attestation_message.go` | verified | |
| uniswap-contracts | `script/cli/src/screens/shared/oklink_api_url.rs` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/utils/introspection/IERC165.sol` | verified | |
| influxdb | `core/trace_http/src/tower.rs` | verified | |
| go | `src/crypto/rsa/rsa.go` | verified | |
| grafana | `pkg/infra/filestorage/file_storage_mock.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v4-periphery/libraries/SafeCurrencyMetadata.sol` | verified | |
| grafana | `pkg/registry/apis/provisioning/utils/metrics.go` | verified | |
| prysm | `testing/util/state.go` | verified | |
| prysm | `tools/analyzers/modernize/any/analyzer.go` | verified | |
| influxdb | `influxdb3_server/src/unified_service/mod.rs` | verified | |
| grafana | `pkg/storage/unified/search/bleve_lifecycle_test.go` | verified | |
| influxdb | `influxdb3_catalog/src/catalog/versions/v3.rs` | verified | |
