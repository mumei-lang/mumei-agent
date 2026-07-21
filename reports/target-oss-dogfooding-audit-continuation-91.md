# Target OSS no-LLM dogfooding audit — continuation 91 (batch 92)

Run: 2026-07-21T23:13:01.074587+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification after three tool-side fixes.

- Go: `_is_go_compiler_test` also skips `// compile` compiler tests (e.g. `go/test/fixedbugs/issue77868.go`).
- Go: `_go_float_casts` treats `float64(x)` / `float32(x)` divisors as floating-point, suppressing integer divide-by-zero false positives in `cmd/trace` byte formatting.
- Go: `_go_is_known_interface_method` recognizes `Upload(ctx context.Context, ...) (..., error)` as an interface method, suppressing nil-receiver false positives for S3/image uploader wrappers.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| uniswap-contracts | `src/briefcase/protocols/v3-periphery/libraries/ChainId.sol` | verified |  |
| go | `src/sync/atomic/doc_64.go` | verified |  |
| prysm | `beacon-chain/db/filters/filter_test.go` | verified |  |
| go | `src/cmd/trace/main.go` | verified |  |
| prysm | `testing/spectest/shared/common/ssz_static/types.go` | verified |  |
| influxdb | `influxdb3/tests/server/auth.rs` | verified |  |
| go | `src/crypto/subtle/dit.go` | verified |  |
| go | `src/debug/pe/file_test.go` | verified |  |
| prysm | `beacon-chain/operations/attestations/prune_expired_test.go` | verified |  |
| prysm | `beacon-chain/sync/pending_payload_attestation.go` | verified |  |
| prysm | `beacon-chain/rpc/prysm/v1alpha1/validator/proposer_payload_attestation.go` | verified |  |
| prysm | `api/client/beacon/client_test.go` | verified |  |
| grafana | `packages/grafana-schema/src/raw/composable/cloudwatch/dataquery/x/types.gen.ts` | verified |  |
| influxdb | `core/authz/src/http.rs` | verified |  |
| go | `test/fixedbugs/issue78297.go` | verified |  |
| go | `test/fixedbugs/issue77868.go` | verified |  |
| grafana | `public/app/features/live/live.ts` | verified |  |
| go | `src/errors/errors.go` | verified |  |
| influxdb | `core/catalog_cache/src/api/mod.rs` | verified |  |
| go | `test/fixedbugs/bug437.go` | verified |  |
| influxdb | `core/mutable_batch/src/lib.rs` | verified |  |
| grafana | `public/app/features/alerting/unified/notifications/constants.ts` | verified |  |
| prysm | `validator/client/beacon-api/submit_aggregate_selection_proof.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v4-core/interfaces/IExttload.sol` | verified |  |
| uniswap-contracts | `script/cli/src/util/screen_util.rs` | verified |  |
| prysm | `tools/analyzers/recursivelock/analyzer_test.go` | verified |  |
| influxdb | `influxdb3_load_generator/src/line_protocol_generator.rs` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v4-core/libraries/BitMath.sol` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/interfaces/IERC1271.sol` | verified |  |
| grafana | `pkg/storage/unified/resource/limited_writer_test.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/lib-external/openzeppelin-contracts/contracts/token/ERC20/IERC20.sol` | verified |  |
| grafana | `pkg/tsdb/loki/flatten_tabular_test.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v4-periphery/interfaces/INotifier.sol` | verified |  |
| influxdb | `influxdb3_catalog/src/log/versions/v2/conversion.rs` | verified |  |
| go | `test/typeparam/mincheck.dir/a.go` | verified |  |
| prysm | `beacon-chain/rpc/prysm/v1alpha1/validator/proposer_test.go` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/DashboardDatasourceBehaviour.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/VariableControlsAddButton.tsx` | verified |  |
| grafana | `public/app/features/transformers/FilterByValueTransformer/ValueMatchers/RangeMatcherEditor.tsx` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v4-periphery/interfaces/IMsgSender.sol` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/accounts_test.go` | verified |  |
| influxdb | `core/iox_query/src/physical_optimizer/test_util.rs` | verified |  |
| go | `src/cmd/compile/internal/syntax/parser_test.go` | verified |  |
| influxdb | `core/influxdb_iox_client/src/client/store.rs` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v3-core/libraries/FixedPoint96.sol` | verified |  |
| grafana | `pkg/components/imguploader/s3uploader.go` | verified |  |
| influxdb | `core/iox_query_influxql/src/plan/planner.rs` | verified |  |
| uniswap-contracts | `script/cli/src/workflows/config/create_config.rs` | verified |  |
| prysm | `testing/spectest/shared/capella/epoch_processing/slashings.go` | verified |  |
| influxdb | `influxdb3/src/commands/serve/cli_params.rs` | verified |  |
