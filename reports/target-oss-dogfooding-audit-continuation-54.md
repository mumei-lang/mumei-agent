# Target OSS no-LLM dogfooding audit — continuation 54 (batch 55)

Run: 2026-07-21T13:30:41.639412+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All 50 sampled files passed no-LLM verification.

## Tool-side fixes in this batch

No new mumei-agent false positives were identified in this batch.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| influxdb | `core/iox_query/src/analyzer/handle_gapfill/virtual_function.rs` | verified | |
| influxdb | `core/iox_query/src/lib.rs` | verified | |
| prysm | `beacon-chain/db/log.go` | verified | |
| prysm | `beacon-chain/core/epoch/epoch_processing_fuzz_test.go` | verified | |
| grafana | `apps/provisioning/pkg/repository/context.go` | verified | |
| uniswap-contracts | `script/util/regenerate_deployment_markdown.py` | verified | |
| prysm | `beacon-chain/p2p/encoder/varint.go` | verified | |
| go | `test/fixedbugs/issue4316.go` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/ERC165/ERC165InterfacesSupported.sol` | verified | |
| uniswap-contracts | `src/briefcase/protocols/calibur/interfaces/IValidationHook.sol` | verified | |
| influxdb | `core/iox_query/src/provider/deduplicate/algo.rs` | verified | |
| influxdb | `core/iox_query/src/test.rs` | verified | |
| go | `src/net/textproto/header_test.go` | verified | |
| go | `src/cmd/compile/internal/ssa/rewritedivisible.go` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/token/ERC1155/extensions/IERC1155MetadataURI.sol` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/utils/cryptography/SignatureChecker.sol` | verified | |
| prysm | `validator/client/beacon-api/propose_attestation.go` | verified | |
| grafana | `public/app/features/transformers/calculateHeatmap/applicability.ts` | verified | |
| go | `src/cmd/cgo/internal/test/issue76023.go` | verified | |
| go | `src/internal/syscall/unix/pty_darwin.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v4-hooks-public/aggregator-hooks/implementations/TempoExchange/interfaces/ITempoExchange.sol` | verified | |
| prysm | `validator/db/kv/eip_blacklisted_keys_test.go` | verified | |
| uniswap-contracts | `script/cli/src/screens/shared/mod.rs` | verified | |
| prysm | `monitoring/prometheus/content_negotiation.go` | verified | |
| influxdb | `core/influxdb_line_protocol/src/builder.rs` | verified | |
| go | `src/syscall/syscall_netbsd.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v4-core/libraries/LiquidityMath.sol` | verified | |
| influxdb | `core/partition/src/template/bucket.rs` | verified | |
| prysm | `testing/spectest/shared/fulu/epoch_processing/slashings.go` | verified | |
| go | `test/codegen/load_type_from_itab.go` | verified | |
| grafana | `public/app/features/transformers/editors/SortByTransformerEditor.tsx` | verified | |
| influxdb | `core/tracker/src/task/history.rs` | verified | |
| influxdb | `influxdb3_catalog/src/catalog/versions/v3/ops/test_util.rs` | verified | |
| go | `src/cmd/api/api_test.go` | verified | |
| influxdb | `influxdb3_cache/src/parquet_cache/mod.rs` | verified | |
| grafana | `public/app/features/expressions/components/ClassicConditions.tsx` | verified | |
| go | `test/typeparam/issue49667.go` | verified | |
| grafana | `packages/grafana-runtime/src/components/QueryEditorWithMigration.tsx` | verified | |
| prysm | `testing/spectest/minimal/fulu__epoch_processing__justification_and_finalization_test.go` | verified | |
| grafana | `packages/grafana-ui/src/components/PanelChrome/PanelMenu.tsx` | verified | |
| uniswap-contracts | `lib/oz-v3.4-solc-0.7/contracts/utils/Context.sol` | verified | |
| go | `src/os/root_test.go` | verified | |
| prysm | `testing/spectest/mainnet/gloas__epoch_processing__slashings_test.go` | verified | |
| grafana | `pkg/tests/apis/alerting/notifications/inhibitionrule/inhibition_rule_test.go` | verified | |
| prysm | `testing/spectest/shared/capella/epoch_processing/slashings_reset.go` | verified | |
| influxdb | `influxdb3_catalog/src/catalog/versions/v3/ops/database.rs` | verified | |
| grafana | `public/app/features/logs/components/panel/popoverMenuTypes.ts` | verified | |
| grafana | `packages/grafana-data/src/transformations/matchers/valueMatchers/nullMatchers.ts` | verified | |
| grafana | `public/app/core/utils/applyStateChanges.ts` | verified | |
| uniswap-contracts | `src/briefcase/protocols/util-contracts/interfaces/IFeeCollector.sol` | verified | |
