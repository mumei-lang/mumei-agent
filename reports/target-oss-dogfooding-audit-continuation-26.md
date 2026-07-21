# Target OSS Dogfooding Audit - Continuation 25 (Batch 27)

## Summary

- **Date**: 2026-07-19
- **Method**: no-LLM batch sampling
- **Sample size**: 50 files
- **Result**: **50 verified / 0 refuted / 0 unverifiable**

## Tool improvement in this batch

### Go switch-case return expression over-capture

`go/src/go/types/builtins.go` was `unverifiable` because `builtin` contains many `return` statements inside `switch` cases. The return-expression extractor scanned until the next `}` at depth 0, which does not exist until the end of the `switch` block, so it captured entire switch bodies including comments. The regex safety fallback then interpreted URLs such as `https://play.golang.org/p/...` and `go/types` as division operators, producing bogus preconditions `p != 0 && types != 0` that could not be lowered.

`_extract_return_expression` now also terminates at `case` and `default` labels (depth 0, outside ternaries), so switch-case returns are captured correctly and comments inside switch bodies are no longer pulled into return expressions.

## Per-file results

| Repository | File | Language | Status |
|---|---|---|---|
| go | `src/debug/elf/reader.go` | go | verified |
| go | `src/cmd/objdump/objdump_test.go` | go | verified |
| go | `src/runtime/os_workdir_ios_arm64.go` | go | verified |
| go | `src/encoding/json/v2_stream.go` | go | verified |
| go | `src/internal/diff/diff_test.go` | go | verified |
| go | `src/cmd/go/internal/auth/userauth_test.go` | go | verified |
| go | `src/syscall/wtf8_windows_test.go` | go | verified |
| go | `src/go/types/builtins.go` | go | verified |
| go | `src/os/root_unix.go` | go | verified |
| go | `src/cmd/go/internal/auth/netrc_test.go` | go | verified |
| prysm | `validator/accounts/wallet/wallet_test.go` | go | verified |
| prysm | `cmd/beacon-chain/db/db.go` | go | verified |
| prysm | `testing/spectest/mainnet/capella__operations__voluntary_exit_test.go` | go | verified |
| prysm | `beacon-chain/sync/validate_sync_committee_message.go` | go | verified |
| prysm | `consensus-types/light-client/finality_update.go` | go | verified |
| prysm | `beacon-chain/rpc/endpoints_test.go` | go | verified |
| prysm | `beacon-chain/execution/service_test.go` | go | verified |
| prysm | `beacon-chain/cache/attestation_data.go` | go | verified |
| prysm | `beacon-chain/verification/execution_payload_bid_test.go` | go | verified |
| prysm | `testing/spectest/mainnet/gloas__operations__builder_deposit_request_test.go` | go | verified |
| grafana | `public/app/features/alerting/unified/api/integrationSchemasApi.test.ts` | typescript | verified |
| grafana | `packages/grafana-data/src/valueFormats/arithmeticFormatters.ts` | typescript | verified |
| grafana | `public/app/features/alerting/unified/navigation/extensions.ts` | typescript | verified |
| grafana | `packages/grafana-data/src/datetime/formats.ts` | typescript | verified |
| grafana | `packages/grafana-ui/src/graveyard/GraphNG/utils.test.ts` | typescript | verified |
| grafana | `packages/grafana-data/src/valueFormats/dateTimeFormatters.test.ts` | typescript | verified |
| grafana | `public/app/plugins/panel/canvas/migrations.test.ts` | typescript | verified |
| grafana | `packages/grafana-ui/src/themes/getTheme.ts` | typescript | verified |
| grafana | `public/app/features/alerting/unified/utils/templates.test.ts` | typescript | verified |
| grafana | `public/app/features/alerting/unifie...ry/historyResultToDataFrame.test.ts` | typescript | verified |
| influxdb | `core/iox_query/src/exec/cross_rt_stream.rs` | rust | verified |
| influxdb | `core/generated_types/src/google.rs` | rust | verified |
| influxdb | `influxdb3_shutdown/src/tests.rs` | rust | verified |
| influxdb | `influxdb3_clap_blocks/src/socket_addr/tests.rs` | rust | verified |
| influxdb | `core/iox_query/src/exec/split.rs` | rust | verified |
| influxdb | `core/iox_query/src/statistics/aggregate_per_plan.rs` | rust | verified |
| influxdb | `influxdb3_write/src/chunk.rs` | rust | verified |
| influxdb | `influxdb3/tests/cli/admin_token.rs` | rust | verified |
| influxdb | `core/trogging/src/config.rs` | rust | verified |
| influxdb | `core/influxdb2_client/src/models/ast/mod.rs` | rust | verified |
| uniswap-contracts | `lib/oz-v3.4-solc-0.7/contracts/token/ERC721/ERC721.sol` | solidity | verified |
| uniswap-contracts | `src/briefcase/protocols/v3-periphery/interfaces/IMulticall.sol` | solidity | verified |
| uniswap-contracts | `src/briefcase/protocols/v3-periphery/interfaces/IERC721Permit.sol` | solidity | verified |
| uniswap-contracts | `src/briefcase/protocols/v4-core/types/PoolId.sol` | solidity | verified |
| uniswap-contracts | `lib/oz-v3.4-solc-0.7/contracts/utils/Counters.sol` | solidity | verified |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/interfaces/IERC721Enumerable.sol` | solidity | verified |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/ERC721EnumerableMock.sol` | solidity | verified |
| uniswap-contracts | `src/briefcase/protocols/v3-periphery/interfaces/ITickLens.sol` | solidity | verified |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/ERC20FlashMintMock.sol` | solidity | verified |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/proxy/utils/Initializable.sol` | solidity | verified |
