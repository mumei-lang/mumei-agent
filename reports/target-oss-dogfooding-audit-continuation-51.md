# Target OSS no-LLM dogfooding audit — continuation 51 (batch 52)

Run: 2026-07-21T13:12:38.954334+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All 50 sampled files passed no-LLM verification.

## Tool-side fixes in this batch

- Go: suppress nil-receiver false positives for pointer receivers that embed a `ComponentRunner` interface (Prysm E2E component runners).

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| grafana | `public/app/plugins/datasource/cloudwatch/language/utils.ts` | verified | |
| prysm | `genesis/embedded_test.go` | verified | |
| prysm | `testing/endtoend/components/eth1/proxy.go` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/CallReceiverMock.sol` | verified | |
| grafana | `public/app/features/provisioning/hooks/useResourceRepositorySelection.ts` | verified | |
| go | `src/compress/gzip/gunzip.go` | verified | |
| grafana | `public/app/features/alerting/unified/types/contact-points.ts` | verified | |
| influxdb | `influxdb3_write/src/lib.rs` | verified | |
| go | `test/typeparam/tparam1.go` | verified | |
| prysm | `validator/keymanager/local/delete_test.go` | verified | |
| go | `test/typeparam/issue50561.dir/diameter.go` | verified | |
| influxdb | `core/iox_query_influxql/src/plan/planner_rewrite_expression.rs` | verified | |
| uniswap-contracts | `src/briefcase/deployers/util-contracts/FeeOnTransferDetectorDeployer.sol` | verified | |
| go | `src/runtime/race/testdata/chan_test.go` | verified | |
| influxdb | `core/iox_query/src/physical_optimizer/dedup/split.rs` | verified | |
| grafana | `pkg/tsdb/cloudwatch/annotation_query.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/calibur/interfaces/IKeyManagement.sol` | verified | |
| influxdb | `object_store_limit/src/lib.rs` | verified | |
| prysm | `beacon-chain/rpc/core/service.go` | verified | |
| grafana | `public/app/plugins/panel/annolist/AnnotationListItem.tsx` | verified | |
| influxdb | `object_store_utils/src/adaptive_put.rs` | verified | |
| uniswap-contracts | `src/briefcase/protocols/calibur/libraries/PrefixedSaltLib.sol` | verified | |
| uniswap-contracts | `src/briefcase/protocols/permit2/interfaces/IERC1271.sol` | verified | |
| go | `test/codegen/rotate.go` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/interfaces/IERC721Receiver.sol` | verified | |
| go | `test/escape_iface.go` | verified | |
| influxdb | `influxdb3_catalog/src/catalog/versions/v3/inner.rs` | verified | |
| influxdb | `influxdb3/tests/server/flight.rs` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/token/ERC20/utils/TokenTimelock.sol` | verified | |
| go | `src/math/atan.go` | verified | |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/utils/Create2.sol` | verified | |
| prysm | `validator/client/registration.go` | verified | |
| grafana | `pkg/services/ngalert/state/historian/model/rule.go` | verified | |
| go | `src/cmd/compile/internal/test/lang_test.go` | verified | |
| prysm | `beacon-chain/cache/payload_attestation.go` | verified | |
| prysm | `testing/spectest/minimal/fulu__sanity__blocks_test.go` | verified | |
| go | `src/cmd/go/internal/modindex/build_read.go` | verified | |
| prysm | `testing/spectest/mainnet/deneb__fork_helper__upgrade_to_deneb_test.go` | verified | |
| go | `src/runtime/lockrank_test.go` | verified | |
| uniswap-contracts | `src/briefcase/protocols/v3-core/libraries/Oracle.sol` | verified | |
| grafana | `apps/logsdrilldown/pkg/apis/logsdrilldown/v1alpha1/logsdrilldowndefaults_schema_gen.go` | verified | |
| uniswap-contracts | `script/cli/src/state_manager.rs` | verified | |
| influxdb | `core/iox_query_influxql/src/aggregate/spread.rs` | verified | |
| grafana | `apps/provisioning/pkg/generated/clientset/versioned/typed/provisioning/v0alpha1/fake/doc.go` | verified | |
| prysm | `encoding/ssz/hashers_test.go` | verified | |
| grafana | `public/app/features/scopes/selector/ScopesSelectorService.ts` | verified | |
| grafana | `public/app/features/alerting/unified/components/alert-groups/AlertStateFilter.tsx` | verified | |
| influxdb | `core/influxdb_iox_client/src/client/catalog.rs` | verified | |
| prysm | `testing/spectest/mainnet/altair__operations__proposer_slashing_test.go` | verified | |
| influxdb | `core/iox_query/src/exec/series_limit/logical.rs` | verified | |
