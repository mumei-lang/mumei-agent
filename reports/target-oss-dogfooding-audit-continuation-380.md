# Target OSS no-LLM dogfooding audit — continuation 380 (batch 381)

Run: 2026-07-22T23:32:05.875404+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/internal/par/queue.go` | verified |  |
| go | `src/cmd/link/linkbig_test.go` | verified |  |
| go | `src/crypto/internal/cryptotest/stream.go` | verified |  |
| go | `src/crypto/internal/fips140/rsa/keygen_test.go` | verified |  |
| go | `src/crypto/internal/fips140/sha512/_asm/sha512block_amd64_asm.go` | verified |  |
| go | `src/go/token/export_test.go` | verified |  |
| go | `src/internal/poll/fd_posix_test.go` | verified |  |
| go | `src/log/slog/example_test.go` | verified |  |
| go | `src/net/sock_bsd.go` | verified |  |
| go | `src/net/tcpconn_keepalive_conf_darwin_test.go` | verified |  |
| go | `src/net/tcpconn_keepalive_conf_windows_test.go` | verified |  |
| go | `src/runtime/vgetrandom_unsupported.go` | verified |  |
| go | `src/simd/archsimd/internal/simd_test/unary_helpers_128_test.go` | verified |  |
| go | `src/sync/atomic/doc_32.go` | verified |  |
| go | `test/dwarf/dwarf.dir/z3.go` | verified |  |
| go | `test/fixedbugs/bug017.go` | verified |  |
| go | `test/fixedbugs/bug332.go` | verified |  |
| go | `test/fixedbugs/bug478.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue14520.go` | verified |  |
| go | `test/fixedbugs/issue31777.go` | verified |  |
| go | `test/fixedbugs/issue49665.go` | verified |  |
| go | `test/method1.go` | verified |  |
| go | `test/typeparam/issue47892.dir/a.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/user_codec_gen.go` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/collections/v1alpha1/endpoints.gen.ts` | verified |  |
| grafana | `packages/grafana-data/src/types/app.ts` | verified |  |
| grafana | `packages/grafana-test-utils/src/matchers/toEmitValues.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/DateTimePickers/TimeRangePicker/TimeRangeList.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/test-utils/mockDom.ts` | verified |  |
| grafana | `packages/grafana-ui/src/utils/reactUtils.ts` | verified |  |
| grafana | `pkg/api/accesscontrol.go` | verified |  |
| grafana | `pkg/plugins/config/tracing.go` | verified |  |
| grafana | `pkg/services/authn/authntest/fake.go` | verified |  |
| grafana | `pkg/services/authz/zanzana/common/tuple.go` | verified |  |
| grafana | `pkg/services/ngalert/backtesting/eval_query_test.go` | verified |  |
| grafana | `pkg/services/oauthtoken/oauthtokentest/oauthtokentest.go` | verified |  |
| grafana | `pkg/services/store/kind/dashboard/summary.go` | verified |  |
| grafana | `pkg/tests/api/folders/api_folders_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/foldermetadata/move_creation_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/resourcekinds/jobs_test.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/AlertLabel.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/saving/SaveDashboardForm.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/DashboardReloadBehavior.ts` | verified |  |
| grafana | `public/app/features/datasources/components/SuggestedDashboardsLoader.tsx` | verified |  |
| grafana | `public/app/features/dimensions/context.ts` | verified |  |
| grafana | `public/app/features/provisioning/File/utils.ts` | verified |  |
| grafana | `public/app/features/visualization/data-hover/ComplexDataHoverView.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/memoizedDebounce.ts` | verified |  |
| grafana | `public/app/plugins/datasource/loki/migrations/variableQueryMigrations.ts` | verified |  |
| grafana | `public/app/plugins/panel/geomap/utils/layers.ts` | verified |  |
