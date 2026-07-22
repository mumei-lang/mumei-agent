# Target OSS no-LLM dogfooding audit — continuation 102 (batch 103)

Run: 2026-07-22T00:01:47.830048+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All 50 sampled files passed no-LLM verification with no agent-side fixes.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| prysm | `proto/ssz_query/response.pb.go` | verified |  |
| go | `src/internal/goexperiment/exp_randomizedheapbase64_on.go` | verified |  |
| go | `src/net/fd_fake.go` | verified |  |
| go | `src/crypto/internal/constanttime/constant_time.go` | verified |  |
| go | `test/simd.go` | verified |  |
| prysm | `testing/spectest/minimal/fulu__epoch_processing__sync_committee_updates_test.go` | verified |  |
| go | `src/syscall/syscall_netbsd_amd64.go` | verified |  |
| influxdb | `core/trace_exporters/src/thrift/zipkincore.rs` | verified |  |
| go | `src/syscall/zsyscall_netbsd_arm.go` | verified |  |
| grafana | `public/app/plugins/panel/nodeGraph/layout.ts` | verified |  |
| influxdb | `influxdb3_catalog/src/catalog/versions/v3/ops/config.rs` | verified |  |
| grafana | `pkg/services/sqlstore/bulk.go` | verified |  |
| prysm | `beacon-chain/operations/attestations/log.go` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/UnlinkModal.tsx` | verified |  |
| prysm | `testing/benchmark/pregen_test.go` | verified |  |
| grafana | `public/app/features/datasources/components/DataSourcesList.tsx` | verified |  |
| go | `src/internal/goexperiment/exp_boringcrypto_off.go` | verified |  |
| influxdb | `influxdb3_types/src/lib.rs` | verified |  |
| prysm | `beacon-chain/sync/initial-sync/service.go` | verified |  |
| go | `src/runtime/write_err.go` | verified |  |
| prysm | `beacon-chain/sync/validate_sync_committee_message_test.go` | verified |  |
| grafana | `public/app/features/explore/RecentQueries/recentQueriesSortOptions.ts` | verified |  |
| prysm | `beacon-chain/node/shutdown_proposals_test.go` | verified |  |
| prysm | `validator/client/propose_gloas_test.go` | verified |  |
| influxdb | `core/influxdb_influxql_parser/src/common.rs` | verified |  |
| influxdb | `influxdb3_catalog/src/catalog/versions/v3/ops/query_group.rs` | verified |  |
| influxdb | `core/datafusion_util/src/watch.rs` | verified |  |
| go | `test/fixedbugs/bug506.dir/main.go` | verified |  |
| prysm | `testing/endtoend/mainnet_scenario_e2e_test.go` | verified |  |
| influxdb | `core/influxdb2_client/src/models/resource.rs` | verified |  |
| go | `src/cmd/link/internal/ld/heap.go` | verified |  |
| influxdb | `core/iox_query_influxql/src/error.rs` | verified |  |
| grafana | `e2e-playwright/test-plugins/grafana-extensionstest-app/webpack.config.ts` | verified |  |
| grafana | `pkg/plugins/manager/pipeline/bootstrap/bootstrap.go` | verified |  |
| grafana | `public/app/features/admin/UserCreatePage.tsx` | verified |  |
| prysm | `testing/spectest/minimal/altair__epoch_processing__justification_and_finalization_test.go` | verified |  |
| grafana | `public/app/features/org/OrgProfile.tsx` | verified |  |
| prysm | `beacon-chain/forkchoice/doubly-linked-tree/reorg_late_blocks_test.go` | verified |  |
| influxdb | `core/iox_v1_query_api/src/value.rs` | verified |  |
| go | `test/makeslice.go` | verified |  |
| grafana | `public/app/features/bookmarks/BookmarksPage.tsx` | verified |  |
| influxdb | `influxdb3_system_tables/src/lib.rs` | verified |  |
| grafana | `packages/grafana-ui/src/components/RenderUserContentAsHTML/RenderUserContentAsHTML.tsx` | verified |  |
| grafana | `public/app/features/invites/InviteeRow.tsx` | verified |  |
| grafana | `pkg/storage/unified/sql/sqltemplate/mocks/test_snapshots.go` | verified |  |
| grafana | `public/app/plugins/panel/candlestick/suggestions.ts` | verified |  |
| grafana | `packages/grafana-o11y-ds-frontend/src/TraceToProfiles/TraceToProfilesSettings.tsx` | verified |  |
| grafana | `public/app/features/explore/FlameGraph/FlameGraphExploreContainer.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/MetricsQueryEditor/TimeGrainField.tsx` | verified |  |
| grafana | `packages/grafana-runtime/src/utils/toDataQueryError.ts` | verified |  |
