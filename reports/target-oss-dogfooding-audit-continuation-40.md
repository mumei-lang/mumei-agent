# Target OSS no-LLM dogfooding audit — continuation 40 (batch 41)

Run: 2026-07-21T09:48:21.949597+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All 50 sampled files passed no-LLM verification.

## Tool-side fixes in this batch

- Go generic instantiation with builtin type arguments (``rangeNum[int]``) is no longer mistaken for an index access.
- Go interval-math functions treat integer time-quantum parameters (``seconds``, ``period``, ``interval``, ``duration``, ``rate``, ``tick``) as non-zero, suppressing divide-by-zero false positives in functions like ``intervalNumber(t, seconds int64)``.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| grafana | `public/app/features/alerting/unified/components/export/GrafanaReceiverExporter.tsx` | verified | |
| prysm | `testing/spectest/minimal/capella__epoch_processing__inactivity_updates_test.go` | verified | |
| uniswap-contracts | `src/briefcase/deployers/calibur/CaliburEntryDeployer.sol` | verified | |
| prysm | `beacon-chain/core/peerdas/reconstruction_test.go` | verified | |
| influxdb | `core/generated_types/src/google.rs` | verified | |
| influxdb | `core/influxdb2_client/examples/ready.rs` | verified | |
| grafana | `pkg/services/live/orgchannel/orgchannel_test.go` | verified | |
| go | `src/reflect/iter.go` | verified | |
| prysm | `testing/spectest/minimal/phase0__epoch_processing__slashings_reset_test.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/universal-router/interfaces/IUniversalRouter.sol` | verified | |
| prysm | `testing/spectest/shared/deneb/epoch_processing/slashings_reset.go` | verified | |
| grafana | `pkg/services/kmsproviders/kmsproviders.go` | verified | |
| go | `src/cmd/link/internal/ld/errors.go` | verified | |
| prysm | `testing/spectest/mainnet/altair__epoch_processing__participation_flag_updates_test.go` | verified | |
| grafana | `packages/grafana-data/src/themes/createTransitions.test.ts` | verified | |
| grafana | `apps/example/pkg/apis/example/v1alpha1/example_spec_gen.go` | verified | |
| prysm | `testing/spectest/shared/fulu/operations/bls_to_execution_changes.go` | verified | |
| influxdb | `core/mutable_batch_pb/tests/encode.rs` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/token/ERC777/IERC777Sender.sol` | verified | |
| grafana | `public/app/plugins/panel/traces/module.tsx` | verified | |
| uniswap-contracts | `src/briefcase/deployers/universal-router/SwapProxyDeployer.sol` | verified | |
| uniswap-contracts | `lib/oz-v3.4-solc-0.7/contracts/token/ERC721/IERC721Enumerable.sol` | verified | |
| go | `test/fixedbugs/issue45804.go` | verified | |
| go | `src/net/netip/netip.go` | verified | |
| go | `src/cmd/go/internal/modload/buildlist.go` | verified | |
| grafana | `pkg/services/ngalert/notifier/legacy_storage/v1/compat_validation_test.go` | verified | |
| influxdb | `influxdb3_catalog/src/format/view/tests.rs` | verified | |
| uniswap-contracts | `src/briefcase/protocols/uniswapx/base/ReactorStructs.sol` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/access/AccessControlEnumerable.sol` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v4-core/types/Slot0.sol` | verified | |
| prysm | `beacon-chain/sync/batch_verifier_test.go` | verified | |
| go | `src/runtime/pprof/proto.go` | verified | |
| grafana | `public/app/features/alerting/unified/hooks/useIsRuleEditable.test.tsx` | verified | |
| prysm | `testing/spectest/minimal/electra__fork__upgrade_to_electra_test.go` | verified | |
| go | `test/fixedbugs/issue18808.go` | verified | |
| influxdb | `influxdb3_catalog/src/log/versions/v2.rs` | verified | |
| uniswap-contracts | `src/briefcase/protocols/uniswapx/v4/hooks/dca/DCAStructs.sol` | verified | |
| influxdb | `core/service_grpc_flight/src/keep_alive.rs` | verified | |
| influxdb | `influxdb3_authz/src/permissions/tests.rs` | verified | |
| grafana | `packages/grafana-ui/src/components/Combobox/MultiCombobox.story.tsx` | verified | |
| influxdb | `core/influxdb2_client/src/models/ast/property.rs` | verified | |
| go | `src/text/template/exec_test.go` | verified | |
| prysm | `beacon-chain/sync/backfill/log_helpers.go` | verified | |
| influxdb | `core/influxdb_iox_client/src/client/test.rs` | verified | |
| uniswap-contracts | `src/briefcase/protocols/lib-external/oz-v3.4-solc-0.7/contracts/utils/Strings.sol` | verified | |
| grafana | `public/app/plugins/datasource/influxdb/fsql/datasource.flightsql.test.ts` | verified | |
| go | `src/os/removeall_unix.go` | verified | |
| go | `test/fixedbugs/bug486.go` | verified | |
| influxdb | `influxdb3_catalog/src/catalog/versions/v3/catalog/tests.rs` | verified | |
| prysm | `io/logs/stream.go` | verified | |
