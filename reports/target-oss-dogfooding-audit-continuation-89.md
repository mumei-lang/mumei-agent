# Target OSS no-LLM dogfooding audit — continuation 89 (batch 90)

Run: 2026-07-21T23:00:32.968045+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification after one tool-side fix.

- Go: `_strip_go_rust_literals_and_comments` now preserves string/char literal quote delimiters so tree-sitter can parse calls with empty or short string arguments (e.g. `time.FixedZone("", ...)`).
- Go: `_go_known_nonzero_selectors` recognizes imported `time.Second` / `time.Minute` / `math.Pi` etc. as non-zero divisors.
- Go: `_go_actor_nonnil_params` now requires the method to be named `Act`, have a receiver, and return `error`.
- Rust/Go: `_division_safety_issue` and the regex fallback division pattern handle `pkg.Const` selectors without treating `time` as a free variable.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| influxdb | `influxdb3_catalog/src/catalog/versions/v3/ops/node.rs` | verified |  |
| grafana | `public/app/features/annotations/standardAnnotationSupport.ts` | verified |  |
| go | `test/fixedbugs/issue21963.go` | verified |  |
| go | `test/typeparam/issue48962.go` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/token/ERC20/extensions/draft-ERC20Permit.sol` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/token/ERC20/extensions/ERC20Snapshot.sol` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v4-core/libraries/CustomRevert.sol` | verified |  |
| influxdb | `influxdb3_catalog/src/snapshot/versions/v2/conversion.rs` | verified |  |
| go | `src/runtime/zcallback_windows.go` | verified |  |
| influxdb | `core/iox_query/src/analyzer/handle_gapfill/range_predicate.rs` | verified |  |
| prysm | `testing/spectest/minimal/phase0__epoch_processing__justification_and_finalization_test.go` | verified |  |
| grafana | `pkg/storage/unified/resource/cdk_blob.go` | verified |  |
| go | `src/archive/zip/struct.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v4-core/interfaces/IExtsload.sol` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/governance/extensions/GovernorVotesQuorumFraction.sol` | verified |  |
| go | `src/cmd/go/internal/base/path.go` | verified |  |
| uniswap-contracts | `script/cli/src/screens/shared/test_connection.rs` | verified |  |
| uniswap-contracts | `script/cli/src/workflows/config/subflows/mod.rs` | verified |  |
| prysm | `testing/spectest/shared/electra/epoch_processing/slashings.go` | verified |  |
| influxdb | `core/iox_http/src/write.rs` | verified |  |
| grafana | `apps/annotation/pkg/apis/annotation/v0alpha1/getsearch_response_object_types_gen.go` | verified |  |
| go | `src/runtime/stubs_mips64x.go` | verified |  |
| go | `src/runtime/os_nonopenbsd.go` | verified |  |
| influxdb | `influxdb3_catalog/src/catalog/versions/v3/schema/table.rs` | verified |  |
| grafana | `pkg/services/sqlstore/sqlstore_metrics_test.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/lib-external/solmate/src/tokens/ERC20.sol` | verified |  |
| grafana | `public/app/plugins/datasource/influxdb/components/editor/config-v2/versions.ts` | verified |  |
| prysm | `beacon-chain/blockchain/process_attestation_helpers.go` | verified |  |
| go | `test/reflectmethod1.go` | verified |  |
| influxdb | `core/parquet_file/src/writer.rs` | verified |  |
| grafana | `pkg/apimachinery/errutil/template_test.go` | verified |  |
| go | `src/compress/gzip/gzip.go` | verified |  |
| influxdb | `core/object_store_metrics/src/cache_metrics.rs` | verified |  |
| prysm | `testing/spectest/mainnet/gloas__operations__builder_deposit_request_test.go` | verified |  |
| prysm | `testing/spectest/minimal/gloas__operations__voluntary_exit_churn_test.go` | verified |  |
| prysm | `beacon-chain/slasher/log.go` | verified |  |
| influxdb | `core/object_store_mem_cache/src/cache_system/hook/observer.rs` | verified |  |
| prysm | `beacon-chain/p2p/partialdatacolumnbroadcaster/gossip_logger_test.go` | verified |  |
| grafana | `pkg/apiserver/endpoints/request/accept_test.go` | verified |  |
| grafana | `public/app/plugins/panel/canvas/editor/LineStyleEditor.tsx` | verified |  |
| influxdb | `core/metric/src/cumulative.rs` | verified |  |
| influxdb | `influxdb3_catalog/src/catalog/migrations/v2.rs` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/calibur/libraries/EntrypointLib.sol` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/types/BulkActionElement.ts` | verified |  |
| prysm | `beacon-chain/blockchain/goroutine_count.go` | verified |  |
| grafana | `public/app/features/variables/adhoc/picker/ConditionSegment.tsx` | verified |  |
| prysm | `testing/spectest/shared/altair/epoch_processing/justification_and_finalization.go` | verified |  |
| prysm | `beacon-chain/rpc/prysm/v1alpha1/beacon/attestations_test.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v2-core/libraries/SafeMath.sol` | verified |  |
| go | `src/net/sockoptip6_posix.go` | verified |  |
