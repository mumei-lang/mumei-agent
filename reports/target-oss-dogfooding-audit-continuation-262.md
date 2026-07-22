# Target OSS no-LLM dogfooding audit — continuation 262 (batch 263)

Run: 2026-07-22T15:24:33.179306+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/types2/instantiate.go` | verified |  |
| go | `src/cmd/go/internal/auth/gitauth_test.go` | verified |  |
| go | `src/encoding/json/v2_example_text_marshaling_test.go` | verified |  |
| go | `src/internal/bytealg/index_native.go` | verified |  |
| go | `src/internal/syscall/unix/at_js.go` | verified |  |
| go | `src/syscall/ztypes_aix_ppc64.go` | verified |  |
| go | `test/deferfin.go` | verified |  |
| go | `test/fixedbugs/arm64bitfieldoverlap.go` | verified |  |
| go | `test/fixedbugs/issue13777.dir/main.go` | verified |  |
| go | `test/fixedbugs/issue31637.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue74836.go` | verified |  |
| go | `test/fixedbugs/issue79762.go` | verified |  |
| go | `test/index.go` | verified |  |
| go | `test/ken/mfunc.go` | verified |  |
| grafana | `packages/grafana-sql/src/components/configuration/MaxLifetimeField.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/DateTimePickers/TimeRangePicker/TimeRangeLabel.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Forms/Legend.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Segment/SegmentAsync.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Select/types.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/filterExpression.ts` | verified |  |
| grafana | `pkg/api/plugin_checks_test.go` | verified |  |
| grafana | `pkg/apiserver/auditing/event_test.go` | verified |  |
| grafana | `pkg/registry/apis/datasource/sub_health_test.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/export/folders_test.go` | verified |  |
| grafana | `pkg/services/librarypanels/librarypanels_test.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/ualert/org_upgrade_state_mig.go` | verified |  |
| grafana | `pkg/storage/unified/sql/db/mocks/Row.go` | verified |  |
| grafana | `pkg/tsdb/jaeger/types/types.go` | verified |  |
| grafana | `pkg/tsdb/jaeger/utils/grpc_utils_test.go` | verified |  |
| grafana | `pkg/util/shortid_generator_test.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/AlertManagerPicker.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/receivers/editor/register.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/previewToggles.ts` | verified |  |
| grafana | `public/app/features/correlations/CorrelationsPageWrapper.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/DashboardLayoutOrchestrator.tsx` | verified |  |
| grafana | `public/app/features/dashboard/components/GenAI/QuickFeedback.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/utils/color-generator.tsx` | verified |  |
| prysm | `api/grpc/grpc_connection_provider_test.go` | verified |  |
| prysm | `beacon-chain/core/transition/transition_no_verify_sig.go` | verified |  |
| prysm | `beacon-chain/db/kv/custody_test.go` | verified |  |
| prysm | `beacon-chain/db/slasherkv/kv.go` | verified |  |
| prysm | `beacon-chain/p2p/testing/fuzz_p2p.go` | verified |  |
| prysm | `beacon-chain/rpc/eth/shared/request_test.go` | verified |  |
| prysm | `consensus-types/primitives/sszuint64_test.go` | verified |  |
| prysm | `monitoring/journald/journalhook_linux.go` | verified |  |
| prysm | `proto/prysm/v1alpha1/gloas.minimal.pb.go` | verified |  |
| prysm | `testing/spectest/minimal/deneb__sanity__slots_test.go` | verified |  |
| prysm | `validator/client/beacon-api/sync_committee_test.go` | verified |  |
| prysm | `validator/client/health_monitor_test.go` | verified |  |
| prysm | `validator/keymanager/local/keymanager.go` | verified |  |
