# Target OSS no-LLM dogfooding audit — continuation 98 (batch 99)

Run: 2026-07-21T23:43:47.765149+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification with no new tool-side fixes.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| prysm | `testing/spectest/mainnet/electra__operations__withdrawals_test.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v4-core/libraries/Hooks.sol` | verified |  |
| go | `src/cmd/link/cgo_test.go` | verified |  |
| go | `test/fixedbugs/issue63462.go` | verified |  |
| influxdb | `core/iox_query/src/exec/split.rs` | verified |  |
| go | `src/os/eloop_other.go` | verified |  |
| prysm | `beacon-chain/state/state-native/custom-types/state_roots.go` | verified |  |
| prysm | `testing/spectest/shared/common/ssz_static/ssz_static_example_test.go` | verified |  |
| grafana | `pkg/apimachinery/utils/meta_test.go` | verified |  |
| prysm | `beacon-chain/p2p/subnets_test.go` | verified |  |
| go | `test/live1.go` | verified |  |
| prysm | `validator/client/beacon-api/attestation_data.go` | verified |  |
| grafana | `pkg/services/loginattempt/loginattemptimpl/login_attempt_test.go` | verified |  |
| go | `src/internal/oserror/errors.go` | verified |  |
| go | `test/fixedbugs/issue52673.go` | verified |  |
| grafana | `packages/grafana-data/src/utils/fuzzySearch.ts` | verified |  |
| go | `test/fixedbugs/issue19182.go` | verified |  |
| influxdb | `core/mutable_batch/src/writer.rs` | verified |  |
| influxdb | `core/iox_system_tables/src/lib.rs` | verified |  |
| influxdb | `core/influxdb_influxql_parser/src/explain.rs` | verified |  |
| prysm | `beacon-chain/state/stateutil/field_root_eth1.go` | verified |  |
| go | `test/fixedbugs/issue74379.go` | verified |  |
| go | `src/cmd/internal/obj/objfile.go` | verified |  |
| grafana | `public/app/core/components/RolePicker/RoleMenuOption.tsx` | verified |  |
| go | `src/runtime/os_linux.go` | verified |  |
| grafana | `packages/grafana-ui/src/utils/storybook/DashboardStoryCanvas.tsx` | verified |  |
| influxdb | `core/iox_query_influxql/src/plan/test_utils.rs` | verified |  |
| influxdb | `influxdb3_clap_blocks/src/socket_addr.rs` | verified |  |
| grafana | `public/app/features/notebook/pages/NotebookScenePage.tsx` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/interfaces/IERC1155MetadataURI.sol` | verified |  |
| grafana | `public/app/plugins/datasource/alertmanager/consts.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/saved-searches/SavedSearches.tsx` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/annotation_query_test.go` | verified |  |
| grafana | `public/app/plugins/panel/geomap/layers/basemaps/maplibre.ts` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `src/net/sockopt_aix.go` | verified |  |
| grafana | `pkg/storage/unified/client_test.go` | verified |  |
| influxdb | `influxdb3_telemetry/src/stats.rs` | verified |  |
| influxdb | `core/iox_query_influxql/src/plan/planner/metadata.rs` | verified |  |
| grafana | `public/app/features/explore/state/query.ts` | verified |  |
| prysm | `beacon-chain/cache/sync_committee_head_state_test.go` | verified |  |
| influxdb | `core/object_store_metrics/src/log.rs` | verified |  |
| grafana | `pkg/api/static/static_test.go` | verified |  |
| prysm | `validator/keymanager/local/doc.go` | verified |  |
| uniswap-contracts | `script/cli/src/util/deployment_log.rs` | verified |  |
| influxdb | `influxdb3_catalog/src/catalog/versions/v3/transaction.rs` | verified |  |
| go | `src/runtime/stubs3.go` | verified |  |
| prysm | `testing/endtoend/evaluators/slashing.go` | verified |  |
| prysm | `crypto/ecdsa/utils.go` | verified |  |
| go | `test/fixedbugs/issue47317.dir/x.go` | verified |  |
| go | `src/internal/syscall/execenv/execenv_default.go` | verified |  |
