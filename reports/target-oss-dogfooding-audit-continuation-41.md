# Target OSS no-LLM dogfooding audit — continuation 41 (batch 42)

Run: 2026-07-21T10:25:59.793104+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All 50 sampled files passed no-LLM verification.

## Tool-side fixes in this batch

- Go ``float32``/``float64`` parameters are now treated as float variables, so ``fdiv(a, b float64)`` no longer triggers an integer divide-by-zero false positive.
- Rust ``#[tokio::test] async fn ...`` test functions are now recognized as tests and skipped when checking whether a file has any non-test declarations.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| grafana | `pkg/plugins/manager/pipeline/discovery/steps.go` | verified | |
| go | `src/runtime/testdata/testgoroutineleakprofile/goker/cockroach6181.go` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/token/ERC1155/extensions/ERC1155URIStorage.sol` | verified | |
| prysm | `config/params/values.go` | verified | |
| prysm | `validator/client/iface/node_client.go` | verified | |
| prysm | `runtime/interop/premine-state_test.go` | verified | |
| grafana | `pkg/tsdb/graphite/standalone/main.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v4-core/libraries/FixedPoint96.sol` | verified | |
| influxdb | `core/test_helpers/src/lib.rs` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/token/ERC1155/utils/ERC1155Holder.sol` | verified | |
| grafana | `pkg/services/authn/clients/ext_jwt_test.go` | verified | |
| go | `test/fixedbugs/issue4365.go` | verified | |
| influxdb | `core/datafusion_util/src/sender.rs` | verified | |
| uniswap-contracts | `test/SwapProxyDeployer.t.sol` | verified | |
| grafana | `apps/dashboard/pkg/apis/dashboard/v2beta1/zz_generated.deepcopy.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/calibur/libraries/HooksLib.sol` | verified | |
| grafana | `public/app/features/dimensions/scale.test.ts` | verified | |
| influxdb | `core/influxdb_influxql_parser/src/select.rs` | verified | |
| influxdb | `influxdb3_load_generator/src/specs/example.rs` | verified | |
| prysm | `testing/spectest/mainnet/gloas__random_test.go` | verified | |
| prysm | `validator/db/kv/db.go` | verified | |
| prysm | `testing/spectest/mainnet/electra__rewards__rewards_test.go` | verified | |
| prysm | `beacon-chain/slasher/receive_test.go` | verified | |
| grafana | `apps/alerting/rules/pkg/apis/alerting/v0alpha1/alertrule_status_gen.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v4-hooks-public/aggregator-hooks/implementations/Slipstream/interfaces/ISlipstreamFactory.sol` | verified | |
| go | `src/go/internal/srcimporter/srcimporter.go` | verified | |
| grafana | `public/app/features/alerting/unified/hooks/useCombinedRule.ts` | verified | |
| go | `test/live_uintptrkeepalive.go` | verified | |
| go | `src/html/template/html.go` | verified | |
| influxdb | `influxdb3_write/src/retention_period_handler/tests.rs` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v4-periphery/interfaces/ISubscriber.sol` | verified | |
| go | `src/cmd/compile/internal/noder/types.go` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/UUPS/UUPSUpgradeableMock.sol` | verified | |
| grafana | `public/app/features/dashboard-scene/settings/links/DashboardLinkForm.tsx` | verified | |
| prysm | `beacon-chain/verification/data_column_gloas.go` | verified | |
| influxdb | `core/influxdb_influxql_parser/src/expression.rs` | verified | |
| influxdb | `influxdb3_catalog/src/catalog/versions/v3/ops/config/tests.rs` | verified | |
| prysm | `beacon-chain/core/helpers/weak_subjectivity.go` | verified | |
| grafana | `public/app/features/dashboard/dashgrid/DashboardLibrary/DashboardCard.test.tsx` | verified | |
| go | `src/math/big/floatconv_test.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v4-hooks-public/aggregator-hooks/implementations/TempoExchange/interfaces/ITIP20.sol` | verified | |
| prysm | `testing/spectest/minimal/bellatrix__epoch_processing__effective_balance_updates_test.go` | verified | |
| go | `src/mime/quotedprintable/writer.go` | verified | |
| influxdb | `influxdb3_catalog/src/format/reader/tests.rs` | verified | |
| go | `src/internal/runtime/wasitest/testdata/nonblock.go` | verified | |
| uniswap-contracts | `src/briefcase/deployers/v4-periphery/PermissionsAdapterFactoryDeployer.sol` | verified | |
| influxdb | `influxdb3_catalog/src/log/versions/v4/retention_period_tests.rs` | verified | |
| influxdb | `influxdb3_write/src/write_buffer/metrics.rs` | verified | |
| grafana | `pkg/services/authz/zanzana/client/shadow_client.go` | verified | |
| go | `test/typeparam/mdempsky/17.go` | verified | |
