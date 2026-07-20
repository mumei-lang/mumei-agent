# Target OSS Dogfooding Audit - Continuation 23 (Batch 24)

## Summary

- **Date**: 2026-07-21
- **Method**: no-LLM batch sampling
- **Sample size**: 50 files
- **Result**: **50 verified / 0 refuted / 0 unverifiable**

## Tool improvement in this batch

### Solidity index-bounds false positives in ERC721Enumerable

`uniswap-contracts/lib/oz-v4.7.0/contracts/token/ERC721/extensions/ERC721Enumerable.sol` was refuted because:

- `tokenByIndex(uint256 index)` returns `_allTokens[index]` after `require(index < totalSupply(), ...)`.
- `tokenOfOwnerByIndex(address owner, uint256 index)` returns `_ownedTokens[owner][index]`, where `_ownedTokens` is a nested mapping.

The safety checker did not recognize the `require` guard and did not skip mapping key access, so it reported spurious index-bounds counterexamples.

Three small changes fix this:

1. `_solidity_guarded_indices(body)` extracts parameter names that are upper-bounded by `require`/`assert` in the function body.
2. The guarded-index set is threaded through `_issues_for_expression` and `_issues_from_findings` to `_index_safety_issue`, which skips issues for guarded indices.
3. The regex fallback in `_issues_for_expression` now skips containers that appear in `_solidity_mapping_names`, matching the tree-sitter path.

Also, `_is_expression_lowerable` now rejects array indexing on unknown containers (e.g. `_allTokens[index]`), so unlowerable `ensures` clauses fall back to `true` instead of producing `spec_lowering_failed`.

## Per-file results

| # | repo | file | language | status | notes |
|---|------|------|----------|--------|-------|
| 1 | grafana | packages/grafana-sql/src/components/query-editor-raw/QueryValidator.tsx | typescript | verified | |
| 2 | go | src/net/iprawsock_test.go | go | verified | |
| 3 | prysm | api/server/httprest/log.go | go | verified | |
| 4 | prysm | testing/spectest/minimal/bellatrix__epoch_processing__participation_flag_updates_test.go | go | verified | |
| 5 | influxdb | core/iox_query/src/physical_optimizer/sort/lexical_range.rs | rust | verified | |
| 6 | uniswap-contracts | src/briefcase/protocols/permit2/libraries/SignatureVerification.sol | solidity | verified | |
| 7 | grafana | pkg/tests/apis/provisioning/git/metadata_name_change_test.go | go | verified | |
| 8 | go | src/cmd/internal/par/work_test.go | go | verified | |
| 9 | grafana | packages/grafana-ui/src/types/theme.ts | typescript | verified | |
| 10 | grafana | public/app/features/panel/panellinks/link_srv.ts | typescript | verified | |
| 11 | grafana | pkg/registry/apps/annotation/continue.go | go | verified | |
| 12 | go | src/internal/reflectlite/type.go | go | verified | |
| 13 | uniswap-contracts | src/briefcase/deployers/v3-periphery/NonfungiblePositionManagerDeployer.sol | solidity | verified | |
| 14 | go | src/internal/types/errors/codes.go | go | verified | |
| 15 | prysm | beacon-chain/db/kv/migration_block_slot_index_test.go | go | verified | |
| 16 | uniswap-contracts | lib/oz-v4.7.0/contracts/token/ERC721/extensions/ERC721Enumerable.sol | solidity | verified | |
| 17 | uniswap-contracts | script/cli/src/screens/types/enter_env_var.rs | rust | verified | |
| 18 | prysm | network/log.go | go | verified | |
| 19 | influxdb | core/partition/src/template/strftime.rs | rust | verified | |
| 20 | grafana | pkg/tests/apis/provisioning/jobs/pulljob_test.go | go | verified | |
| 21 | grafana | pkg/registry/apis/provisioning/webhooks/pullrequest/comment_test.go | go | verified | |
| 22 | uniswap-contracts | src/briefcase/protocols/util-contracts/interfaces/IERC7914.sol | solidity | verified | |
| 23 | grafana | packages/grafana-runtime/src/services/QueryRunner.ts | typescript | verified | |
| 24 | go | src/cmd/link/internal/sym/library.go | go | verified | |
| 25 | uniswap-contracts | lib/oz-v4.7.0/contracts/interfaces/IERC3156.sol | solidity | verified | |
| 26 | prysm | consensus-types/primitives/wei.go | go | verified | |
| 27 | influxdb | influxdb3_id/benches/serde_vec_map_comparison.rs | rust | verified | |
| 28 | prysm | testing/spectest/shared/fulu/epoch_processing/inactivity_updates.go | go | verified | |
| 29 | prysm | runtime/logging/blob.go | go | verified | |
| 30 | grafana | public/app/plugins/datasource/loki/mocks/createDetectedFieldsMetadataRequest.ts | typescript | verified | |
| 31 | uniswap-contracts | src/briefcase/protocols/v3-periphery/interfaces/ISelfPermit.sol | solidity | verified | |
| 32 | go | src/go/types/token_test.go | go | verified | |
| 33 | influxdb | influxdb3_load_generator/src/query_generator.rs | rust | verified | |
| 34 | go | src/syscall/dir_plan9.go | go | verified | |
| 35 | influxdb | influxdb3_catalog/src/catalog/versions/v3/ops/node/tests.rs | rust | verified | |
| 36 | influxdb | core/iox_query/src/exec/gapfill/exec_tests.rs | rust | verified | |
| 37 | prysm | testing/spectest/mainnet/capella__epoch_processing__registry_updates_test.go | go | verified | |
| 38 | uniswap-contracts | src/briefcase/protocols/permit2/interfaces/IAllowanceTransfer.sol | solidity | verified | |
| 39 | influxdb | influxdb3_write/src/async_collections/tests.rs | rust | verified | |
| 40 | grafana | public/app/features/alerting/unified/utils/url.ts | typescript | verified | |
| 41 | uniswap-contracts | src/briefcase/protocols/universal-router-2_0/libraries/Constants.sol | solidity | verified | |
| 42 | prysm | testing/spectest/mainnet/altair__operations__voluntary_exit_test.go | go | verified | |
| 43 | influxdb | core/iox_query/benches/deduplicate.rs | rust | verified | |
| 44 | influxdb | influxdb3_catalog/src/format/registry.rs | rust | verified | |
| 45 | prysm | runtime/version/fork_test.go | go | verified | |
| 46 | go | src/crypto/internal/fips140/aes/ctr.go | go | verified | |
| 47 | uniswap-contracts | src/briefcase/protocols/calibur/libraries/ERC7739Utils.sol | solidity | verified | |
| 48 | influxdb | influxdb3_telemetry/src/sampler/tests.rs | rust | verified | |
| 49 | go | src/cmd/go/internal/auth/auth.go | go | verified | |
| 50 | go | src/net/http/socks_bundle.go | go | verified | |

## Notes

All 50 sampled files passed no-LLM verification. No OSS-side issues were identified in this batch.
