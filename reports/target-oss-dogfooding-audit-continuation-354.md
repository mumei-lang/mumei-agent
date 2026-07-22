# Target OSS no-LLM dogfooding audit — continuation 354 (batch 355)

Run: 2026-07-22T21:17:08.751513+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ssa/fuse_test.go` | verified |  |
| go | `src/cmd/compile/internal/typecheck/dcl.go` | verified |  |
| go | `src/cmd/compile/internal/types2/util.go` | verified |  |
| go | `src/os/os_unix_test.go` | verified |  |
| go | `src/runtime/export_debug_test.go` | verified |  |
| go | `src/simd/archsimd/_gen/unify/trace.go` | verified |  |
| go | `src/simd/archsimd/internal/simd_test/binary_helpers_128_test.go` | verified |  |
| go | `src/syscall/export_rlimit_test.go` | verified |  |
| go | `src/syscall/zsysnum_linux_mipsle.go` | verified |  |
| go | `test/fixedbugs/gcc61265.go` | verified |  |
| go | `test/fixedbugs/issue20162.go` | verified |  |
| go | `test/fixedbugs/issue20780b.go` | verified |  |
| go | `test/fixedbugs/issue20811.go` | verified |  |
| grafana | `apps/advisor/pkg/apis/advisor/v0alpha1/createregister_response_body_types_gen.go` | verified |  |
| grafana | `packages/grafana-data/src/types/ScopedVars.ts` | verified |  |
| grafana | `packages/grafana-data/src/types/templateVars.ts` | verified |  |
| grafana | `packages/grafana-test-utils/src/fixtures/folders.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/DateTimePickers/options.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Segment/SegmentInput.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/types/interactiveTable.ts` | verified |  |
| grafana | `pkg/api/plugin_checks.go` | verified |  |
| grafana | `pkg/registry/usagestatssvcs/usage_stats_providers_registry.go` | verified |  |
| grafana | `pkg/services/live/pipeline/tree/tree.go` | verified |  |
| grafana | `pkg/services/live/pushhttp/push.go` | verified |  |
| grafana | `pkg/services/org/orgimpl/store.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/accesscontrol/managed_permission_migrator.go` | verified |  |
| grafana | `pkg/storage/unified/resource/continue_test.go` | verified |  |
| grafana | `pkg/tests/apis/alerting/notifications/receivers/integration_testing_test.go` | verified |  |
| grafana | `pkg/tsdb/jaeger/utils/client_utils_test.go` | verified |  |
| grafana | `pkg/tsdb/mysql/mysql.go` | verified |  |
| grafana | `pkg/util/xorm/sequence_test.go` | verified |  |
| grafana | `public/app/core/components/Page/PageTabs.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/mocks/server/handlers/k8s/utils.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/types/silence-form.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/saving/SaveDashboardAsForm.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/serialization/layoutSerializers/TabsLayoutSerializer.ts` | verified |  |
| grafana | `public/app/features/dashboard/components/ShareModal/ThemePicker.tsx` | verified |  |
| grafana | `public/app/features/scopes/selector/ScopesSelector.tsx` | verified |  |
| grafana | `public/app/plugins/panel/timeseries/plugins/OutsideRangePlugin.tsx` | verified |  |
| grafana | `scripts/ci/generate-enterprise-imports/main.go` | verified |  |
| prysm | `beacon-chain/blockchain/process_block_test.go` | verified |  |
| prysm | `beacon-chain/rpc/prysm/v1alpha1/beacon/blocks.go` | verified |  |
| prysm | `beacon-chain/rpc/prysm/v1alpha1/validator/unblinder_test.go` | verified |  |
| prysm | `beacon-chain/sync/pending_payload_envelope.go` | verified |  |
| prysm | `proto/engine/v1/electra.pb.go` | verified |  |
| prysm | `testing/endtoend/minimal_scenario_e2e_test.go` | verified |  |
| prysm | `testing/spectest/shared/deneb/fork/transition.go` | verified |  |
| prysm | `testing/spectest/shared/fulu/epoch_processing/eth1_data_reset.go` | verified |  |
| prysm | `tools/keystores/main_test.go` | verified |  |
| prysm | `validator/rpc/handlers_health_test.go` | verified |  |
