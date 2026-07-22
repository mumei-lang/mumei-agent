# Target OSS no-LLM dogfooding audit — continuation 337 (batch 338)

Run: 2026-07-22T20:35:28.251508+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/link/internal/loader/loader.go` | verified |  |
| go | `src/fmt/errors_test.go` | verified |  |
| go | `src/go/doc/example_internal_test.go` | verified |  |
| go | `src/internal/trace/testtrace/validation.go` | verified |  |
| go | `src/math/lgamma.go` | verified |  |
| go | `src/simd/archsimd/internal/simd_test/compare_helpers_128_test.go` | verified |  |
| go | `src/syscall/zsysnum_freebsd_386.go` | verified |  |
| go | `src/syscall/zsysnum_linux_s390x.go` | verified |  |
| go | `test/fixedbugs/issue5260.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue5910.go` | verified |  |
| go | `test/fixedbugs/issue7884.go` | verified |  |
| go | `test/typeparam/issue49497.go` | verified |  |
| go | `test/typeparam/issue49524.dir/a.go` | verified |  |
| go | `test/typeparam/issue51521.go` | verified |  |
| go | `test/typeparam/valimp.dir/a.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/versioned_mock.go` | verified |  |
| grafana | `packages/grafana-ui/src/components/Input/AutoSizeInputContext.ts` | verified |  |
| grafana | `pkg/api/api.go` | verified |  |
| grafana | `pkg/plugins/codegen/pfs/decl_parser.go` | verified |  |
| grafana | `pkg/registry/apis/ofrep/proxy.go` | verified |  |
| grafana | `pkg/registry/apps/annotation/postgres_partitioned.go` | verified |  |
| grafana | `pkg/services/accesscontrol/resourcepermissions/store.go` | verified |  |
| grafana | `pkg/services/accesscontrol/resourcepermissions/store_bench_test.go` | verified |  |
| grafana | `pkg/services/apikey/apikeyimpl/xorm_store.go` | verified |  |
| grafana | `pkg/services/notifications/send_email_integration_test.go` | verified |  |
| grafana | `pkg/storage/unified/resourcewatch/subject_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/jobs/orphanjob_get_test.go` | verified |  |
| grafana | `public/app/api/clients/roles/index.ts` | verified |  |
| grafana | `public/app/core/services/echo/backends/analytics/PostHogBackend.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/initAlerting.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/edit-pane/DashboardEditPaneSplitter.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/useTrackDashboardVariableValueChange.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/sharing/ShareButton/ShareButton.tsx` | verified |  |
| grafana | `public/app/features/dashboard/components/ShareModal/SharePublicDashboard/ModalAlerts/SaveDashboardChangesAlert.tsx` | verified |  |
| grafana | `public/app/features/explore/QueriesDrawer/QueriesDrawerContext.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/CriticalPath/utils/findLastFinishingChildSpan.tsx` | verified |  |
| grafana | `public/app/features/plugins/admin/tracking.ts` | verified |  |
| grafana | `public/app/features/plugins/extensions/registry/AddedLinksRegistry.ts` | verified |  |
| grafana | `public/app/features/provisioning/Wizard/hooks/useSyncJob.ts` | verified |  |
| grafana | `public/app/plugins/datasource/grafana/types.ts` | verified |  |
| prysm | `api/server/structs/other.go` | verified |  |
| prysm | `beacon-chain/cache/depositsnapshot/merkle_tree_test.go` | verified |  |
| prysm | `beacon-chain/core/gloas/payload_attestation_test.go` | verified |  |
| prysm | `beacon-chain/das/blob_cache_test.go` | verified |  |
| prysm | `beacon-chain/p2p/info.go` | verified |  |
| prysm | `consensus-types/helpers/comparisons.go` | verified |  |
| prysm | `testing/spectest/mainnet/fulu__rewards__rewards_test.go` | verified |  |
| prysm | `testing/spectest/minimal/fulu__finality__finality_test.go` | verified |  |
| prysm | `validator/db/migrate.go` | verified |  |
| prysm | `validator/rpc/handler_wallet_test.go` | verified |  |
