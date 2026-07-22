# Target OSS no-LLM dogfooding audit — continuation 268 (batch 269)

Run: 2026-07-22T15:54:59.564498+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification after fixing Go dual-len loop and binary search index guards.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/typecheck/iimport.go` | verified |  |
| go | `src/cmd/distpack/archive.go` | verified |  |
| go | `src/crypto/mldsa/mldsa_wycheproof_test.go` | verified |  |
| go | `src/internal/godebugs/table.go` | verified |  |
| go | `src/internal/routebsd/interface_freebsd.go` | verified |  |
| go | `src/internal/syscall/unix/fallocate_bsd_386.go` | verified |  |
| go | `src/math/cmplx/isinf.go` | verified |  |
| go | `test/fixedbugs/issue19699.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue33275.go` | verified |  |
| go | `test/fixedbugs/issue42032.go` | verified |  |
| go | `test/ken/interfun.go` | verified |  |
| go | `test/typeparam/issue49241.dir/c.go` | verified |  |
| grafana | `apps/example/pkg/apis/example/v0alpha1/example_status_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/connection/validator.go` | verified |  |
| grafana | `e2e-playwright/dashboard-new-layouts/page-objects/index.ts` | verified |  |
| grafana | `packages/grafana-test-utils/src/canvas/measureText.ts` | verified |  |
| grafana | `pkg/apiserver/registry/generic/key_test.go` | verified |  |
| grafana | `pkg/login/social/connectors/jwt_test_helpers_test.go` | verified |  |
| grafana | `pkg/plugins/httpresponsesender/http_response_sender_test.go` | verified |  |
| grafana | `pkg/registry/apis/folders/zanzana_permission_store.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/routes.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/webhooks/pullrequest/metrics.go` | verified |  |
| grafana | `pkg/registry/apps/alerting/notifications/templategroup/storage.go` | verified |  |
| grafana | `pkg/services/loginattempt/loginattemptimpl/login_attempt.go` | verified |  |
| grafana | `pkg/services/ngalert/api/promql_compat.go` | verified |  |
| grafana | `pkg/services/ngalert/writer/testing.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/pluginconfig/request.go` | verified |  |
| grafana | `pkg/services/team/teamapi/team_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/nats/connection_test.go` | verified |  |
| grafana | `pkg/tsdb/graphite/utils.go` | verified |  |
| grafana | `public/app/features/dashboard-scene/mutation-api/commands/moveTab.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/serialization/layoutSerializers/DefaultGridLayoutSerializer.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/sharing/ShareButton/utils.ts` | verified |  |
| grafana | `public/app/features/dashboard/components/PanelEditor/OptionsPaneCategoryDescriptor.tsx` | verified |  |
| grafana | `public/app/features/dashboard/utils/timeRange.ts` | verified |  |
| grafana | `public/app/features/explore/Logs/LogsContainer.tsx` | verified |  |
| grafana | `public/app/features/plugins/extensions/registry/setup.ts` | verified |  |
| grafana | `public/app/features/query/state/DashboardQueryRunner/UnifiedAlertStatesWorker.ts` | verified |  |
| grafana | `public/app/features/query/state/DashboardQueryRunner/testHelpers.ts` | verified |  |
| grafana | `public/app/plugins/datasource/loki/makeTableFrames.ts` | verified |  |
| prysm | `beacon-chain/blockchain/kzg/kzg_test.go` | verified |  |
| prysm | `beacon-chain/rpc/prysm/v1alpha1/beacon/assignments_test.go` | verified |  |
| prysm | `beacon-chain/rpc/prysm/v1alpha1/beacon/blocks_test.go` | verified |  |
| prysm | `beacon-chain/state/state-native/state_trie.go` | verified |  |
| prysm | `beacon-chain/sync/validate_beacon_blocks.go` | verified |  |
| prysm | `consensus-types/hdiff/fuzz_test.go` | verified |  |
| prysm | `consensus-types/primitives/sszbytes.go` | verified |  |
| prysm | `testing/spectest/shared/fulu/sanity/slot_processing.go` | verified |  |
| prysm | `validator/slashing-protection-history/round_trip_test.go` | verified |  |
| prysm | `validator/web/handler_test.go` | verified |  |
