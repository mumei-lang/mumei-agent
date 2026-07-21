# Target OSS no-LLM dogfooding audit — continuation 57 (batch 58)

Run: 2026-07-21T13:49:45.634801+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All 50 sampled files passed no-LLM verification.

## Tool-side fixes in this batch

- Go: treat ``proposerIdx, err := BeaconProposerIndex(...); if err != nil { return }`` as a bounds-safe index assignment.
- Go: treat cryptographic key types and ``big.Int`` as non-nil container parameters.
- Go: fix parameter-type parsing for grouped declarations ``a, b *T``.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `test/fixedbugs/bug305.go` | verified | |
| grafana | `public/app/features/explore/TraceView/components/Tween.tsx` | verified | |
| grafana | `public/app/features/provisioning/utils/selectors.ts` | verified | |
| influxdb | `object_store_utils/src/retryable_object_store.rs` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v4-core/libraries/TickBitmap.sol` | verified | |
| grafana | `apps/dashboard/pkg/apis/dashboard/v2beta1/variable_object_gen.go` | verified | |
| influxdb | `influxdb3_py_api/src/line_builder/mod.rs` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/proxy/transparent/ProxyAdmin.sol` | verified | |
| grafana | `pkg/services/ngalert/state/image_mock.go` | verified | |
| prysm | `testing/util/helpers.go` | verified | |
| influxdb | `core/iox_query/src/exec/sleep.rs` | verified | |
| influxdb | `influxdb3_write/src/write_buffer/persisted_files.rs` | verified | |
| influxdb | `core/iox_query/src/provider/physical.rs` | verified | |
| go | `src/syscall/mkpost.go` | verified | |
| go | `src/internal/types/testdata/fixedbugs/issue50427b.go` | verified | |
| uniswap-contracts | `script/cli/src/workflows/verifier_selection_workflow.rs` | verified | |
| influxdb | `influxdb3_catalog/src/object_store.rs` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v4-periphery/interfaces/IStateView.sol` | verified | |
| uniswap-contracts | `script/cli/src/util/mod.rs` | verified | |
| grafana | `public/app/plugins/panel/gauge/suggestions.ts` | verified | |
| prysm | `validator/client/registration_test.go` | verified | |
| prysm | `validator/client/factory.go` | verified | |
| prysm | `beacon-chain/core/electra/churn.go` | verified | |
| prysm | `testing/spectest/minimal/deneb__operations__execution_payload_test.go` | verified | |
| grafana | `packages/grafana-schema/src/schema/dashboard/v2alpha1/dashboard_object_gen.ts` | verified | |
| grafana | `packages/grafana-ui/src/components/DataLinks/DataLinksInlineEditor/DataLinksInlineEditorBase.tsx` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v4-periphery/interfaces/IUniswapV4DeployerCompetition.sol` | verified | |
| influxdb | `influxdb3/src/commands/create/tests.rs` | verified | |
| go | `src/internal/poll/writev.go` | verified | |
| prysm | `testing/spectest/shared/gloas/operations/sync_committee.go` | verified | |
| go | `test/fixedbugs/issue5259.dir/bug.go` | verified | |
| prysm | `testing/spectest/mainnet/altair__operations__deposit_test.go` | verified | |
| go | `src/runtime/stkframe.go` | verified | |
| go | `test/codegen/structs.go` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/GovernorPreventLateQuorumMock.sol` | verified | |
| grafana | `public/app/features/dashboard-scene/serialization/transformToV2TypesUtils.ts` | verified | |
| influxdb | `core/iox_query/src/ingester.rs` | verified | |
| go | `src/internal/cpu/cpu_arm64_other.go` | verified | |
| prysm | `beacon-chain/core/transition/benchmarks_test.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v4-core/libraries/LPFeeLibrary.sol` | verified | |
| prysm | `crypto/rand/rand_test.go` | verified | |
| grafana | `public/app/features/dashboard-scene/settings/variables/useVariableSelectionOptionsCategory.tsx` | verified | |
| uniswap-contracts | `lib/oz-v3.4-solc-0.7/contracts/token/ERC721/IERC721.sol` | verified | |
| go | `src/internal/coverage/slicewriter/slw_test.go` | verified | |
| grafana | `public/app/core/utils/roles.ts` | verified | |
| prysm | `config/params/configset_test.go` | verified | |
| go | `src/cmd/go/internal/modfetch/coderepo.go` | verified | |
| influxdb | `core/trace_exporters/src/lib.rs` | verified | |
| influxdb | `influxdb3_catalog/src/snapshot/versions/v4.rs` | verified | |
| uniswap-contracts | `script/cli/src/screens/verify_contract/mod.rs` | verified | |
