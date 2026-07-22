# Target OSS no-LLM dogfooding audit — continuation 356 (batch 357)

Run: 2026-07-22T21:25:12.615439+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/escape/call.go` | verified |  |
| go | `src/cmd/compile/internal/typecheck/_builtin/runtime.go` | verified |  |
| go | `src/crypto/hkdf/hkdf_wycheproof_test.go` | verified |  |
| go | `src/database/sql/fakedb_test.go` | verified |  |
| go | `src/internal/filepathlite/path_unix.go` | verified |  |
| go | `src/internal/msan/msan.go` | verified |  |
| go | `src/internal/syscall/unix/at_solaris.go` | verified |  |
| go | `src/runtime/os_netbsd.go` | verified |  |
| go | `src/simd/archsimd/maskmerge_gen_arm64.go` | verified |  |
| go | `src/syscall/zsyscall_linux_riscv64.go` | verified |  |
| go | `test/fixedbugs/bug306.dir/p2.go` | verified |  |
| go | `test/fixedbugs/issue31747.go` | verified |  |
| go | `test/fixedbugs/issue73309.go` | verified |  |
| go | `test/typeparam/issue47925c.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v0alpha1/zz_generated.defaults.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/getsearchteams_response_body_types_gen.go` | verified |  |
| grafana | `apps/playlist/pkg/app/app.go` | verified |  |
| grafana | `apps/provisioning/pkg/apis/provisioning/v0alpha1/zz_generated.defaults.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/informers/externalversions/provisioning/v0alpha1/repository.go` | verified |  |
| grafana | `packages/grafana-data/src/types/variables.ts` | verified |  |
| grafana | `packages/grafana-flamegraph/src/utils.ts` | verified |  |
| grafana | `packages/grafana-sql/src/components/visual-query-builder/SelectColumn.tsx` | verified |  |
| grafana | `pkg/apimachinery/identity/role_type.go` | verified |  |
| grafana | `pkg/apimachinery/identity/static.go` | verified |  |
| grafana | `pkg/expr/sql_command_alert_test.go` | verified |  |
| grafana | `pkg/registry/apps/apps.go` | verified |  |
| grafana | `pkg/services/auth/idtest/fake.go` | verified |  |
| grafana | `pkg/services/ngalert/writer/datasourcewriter.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/libraryelements.go` | verified |  |
| grafana | `pkg/storage/unified/search/vector/schema.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/mocks/list_metrics_service.go` | verified |  |
| grafana | `public/app/features/correlations/Forms/correlationsFormContext.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/StackedEditor/useActiveStackedItemObserver.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/saving/useSaveDashboard.ts` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/TraceTimelineViewer/SpanDetail/SpanFlameGraph.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/TraceTimelineViewer/TimelineHeaderRow/TimelineColumnResizer.tsx` | verified |  |
| grafana | `public/app/features/home/Recommendations/RecommendationPill.tsx` | verified |  |
| grafana | `public/app/features/scopes/ScopesService.ts` | verified |  |
| grafana | `public/app/plugins/datasource/grafana-testdata-datasource/runStreams.ts` | verified |  |
| grafana | `public/app/plugins/datasource/graphite/components/GraphiteQueryEditor.tsx` | verified |  |
| prysm | `beacon-chain/core/time/slot_epoch_test.go` | verified |  |
| prysm | `beacon-chain/db/kv/execution_chain_test.go` | verified |  |
| prysm | `beacon-chain/rpc/prysm/v1alpha1/node/server.go` | verified |  |
| prysm | `beacon-chain/sync/initial-sync/blocks_queue.go` | verified |  |
| prysm | `beacon-chain/sync/validate_attester_slashing.go` | verified |  |
| prysm | `cmd/validator/wallet/create_test.go` | verified |  |
| prysm | `consensus-types/payload-attestation/readonly_message.go` | verified |  |
| prysm | `testing/spectest/minimal/electra__operations__voluntary_exit_test.go` | verified |  |
| prysm | `testing/spectest/minimal/gloas__operations__sync_committee_test.go` | verified |  |
| prysm | `testing/spectest/minimal/phase0__operations__attester_slashing_test.go` | verified |  |
