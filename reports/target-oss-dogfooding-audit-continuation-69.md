# Target OSS no-LLM dogfooding audit — continuation 69 (batch 70)

Run: 2026-07-21T14:36:23.420230+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification.

## Tool-side fixes in this batch

- Go: treat standard library container types ``Transport``/``Conn``/``Stream``/``ReadLoop`` and request DTOs ``Request``/``ClientRequest`` as non-nil to suppress http2 internal false positives.
- Sampling exclusions: skip ``testdata/`` directories and Rust ``tests.rs``/``test.rs`` module files.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/UUPS/UUPSLegacy.sol` | verified |  |
| influxdb | `influxdb3_types/src/logging.rs` | verified |  |
| grafana | `packages/grafana-ui/src/utils/storybook/ExampleFrame.tsx` | verified |  |
| prysm | `tools/analyzers/cryptorand/analyzer_test.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v4-periphery/libraries/VanityAddressLib.sol` | verified |  |
| influxdb | `core/iox_v1_query_api/src/response/stream.rs` | verified |  |
| influxdb | `influxdb3_load_generator/src/specs/one_mil.rs` | verified |  |
| uniswap-contracts | `script/cli/src/libs/web3.rs` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v1beta1/templategroup_codec_gen.go` | verified |  |
| go | `src/internal/runtime/wasitest/host_test.go` | verified |  |
| grafana | `public/app/features/variables/state/helpers.ts` | verified |  |
| uniswap-contracts | `src/briefcase/deployers/view-quoter-v3/QuoterDeployer.sol` | verified |  |
| prysm | `validator/client/validator.go` | verified |  |
| prysm | `beacon-chain/execution/testing/mock_execution_chain.go` | verified |  |
| influxdb | `core/iox_query/src/logical_optimizer/influx_regex_to_datafusion_regex.rs` | verified |  |
| prysm | `testing/spectest/minimal/gloas__operations__proposer_slashing_test.go` | verified |  |
| prysm | `validator/client/beacon-api/duties_test.go` | verified |  |
| prysm | `crypto/bls/bls_test.go` | verified |  |
| go | `test/fixedbugs/issue78641.go` | verified |  |
| prysm | `testing/spectest/minimal/electra__operations__attestation_test.go` | verified |  |
| influxdb | `core/sharder/benches/sharder.rs` | verified |  |
| grafana | `pkg/services/ngalert/notifier/email_test.go` | verified |  |
| influxdb | `core/test_helpers/src/tracing.rs` | verified |  |
| prysm | `beacon-chain/node/config_test.go` | verified |  |
| influxdb | `core/query_functions/src/regex.rs` | verified |  |
| go | `src/cmd/go/internal/toolchain/path_windows.go` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/Sidebar/Cards/QueryCard.tsx` | verified |  |
| go | `src/os/sys_aix.go` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/wizard/MyGovernor3.sol` | verified |  |
| uniswap-contracts | `script/cli/src/debug.rs` | verified |  |
| go | `src/net/http/internal/http2/transport.go` | verified |  |
| go | `test/fixedbugs/issue57955.go` | verified |  |
| prysm | `beacon-chain/core/blocks/attestation_regression_test.go` | verified |  |
| go | `src/cmd/cgo/internal/testnocgo/nocgo_test.go` | verified |  |
| grafana | `pkg/services/preference/prefimpl/pref.go` | verified |  |
| go | `src/cmd/compile/internal/noder/noder.go` | verified |  |
| prysm | `cmd/prysmctl/validator/withdraw_test.go` | verified |  |
| grafana | `pkg/tsdb/grafana-testdata-datasource/conversion_handler.go` | verified |  |
| go | `src/cmd/compile/internal/syntax/operator_string.go` | verified |  |
| go | `src/html/template/template_test.go` | verified |  |
| influxdb | `core/iox_query/src/exec.rs` | verified |  |
| grafana | `public/app/plugins/datasource/loki/components/LokiContextUi.tsx` | verified |  |
| uniswap-contracts | `lib/oz-v3.4-solc-0.7/contracts/math/SignedSafeMath.sol` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/lib-external/openzeppelin-contracts/contracts/utils/Errors.sol` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/NeedHelpInfo.tsx` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v4-periphery/interfaces/IImmutableState.sol` | verified |  |
| grafana | `pkg/services/libraryelements/model/model.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/universal-router/modules/uniswap/v3/BytesLib.sol` | verified |  |
| influxdb | `core/iox_query/src/physical_optimizer/union/mod.rs` | verified |  |
| influxdb | `core/iox_query_influxql/src/window/cumulative_sum.rs` | verified |  |
