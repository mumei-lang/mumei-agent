# Target OSS no-LLM dogfooding audit — continuation 542 (batch 543)

Run: 2026-07-23T09:54:41.111524+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/test/truncconst_test.go` | verified |  |
| go | `src/cmd/compile/internal/types2/hilbert_test.go` | verified |  |
| go | `src/cmd/internal/test2json/test2json_test.go` | verified |  |
| go | `src/crypto/boring/boring.go` | verified |  |
| go | `src/encoding/csv/reader.go` | verified |  |
| go | `src/internal/syscall/windows/registry/value.go` | verified |  |
| go | `src/math/big/internal/asmgen/cheat.go` | verified |  |
| go | `src/net/http/serve_test.go` | verified |  |
| go | `src/os/dir_darwin.go` | verified |  |
| go | `src/os/file_unix.go` | verified |  |
| go | `src/os/proc.go` | verified |  |
| go | `src/os/zero_copy_stub.go` | verified |  |
| go | `src/runtime/lock_futex.go` | verified |  |
| go | `src/runtime/sema.go` | verified |  |
| go | `src/runtime/signal_aix_ppc64.go` | verified |  |
| go | `src/runtime/stubs_nonlinux.go` | verified |  |
| go | `src/syscall/zsyscall_dragonfly_amd64.go` | verified |  |
| go | `test/escape_level.go` | verified |  |
| go | `test/fixedbugs/bug248.dir/bug0.go` | verified |  |
| go | `test/fixedbugs/bug257.go` | verified |  |
| go | `test/fixedbugs/bug267.go` | verified |  |
| go | `test/fixedbugs/bug415.dir/p.go` | verified |  |
| go | `test/fixedbugs/bug422.go` | verified |  |
| go | `test/initloop.go` | verified |  |
| go | `test/interface/embed3.go` | verified |  |
| go | `test/typeparam/issue49246.dir/a.go` | verified |  |
| go | `test/typeparam/issue49524.go` | verified |  |
| go | `test/typeparam/issue58513.go` | verified |  |
| go | `test/typeparam/structinit.dir/b.go` | verified |  |
| go | `test/used.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v1beta1/receiver_object_gen.go` | verified |  |
| grafana | `apps/plugins/plugin/src/generated/meta/v0alpha1/meta_object_gen.ts` | verified |  |
| grafana | `e2e-playwright/dashboard-new-layouts/page-objects/Controls.ts` | verified |  |
| grafana | `e2e-playwright/panels-suite/barchart-utils.ts` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/createBaseQuery.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Tabs/VerticalTab.tsx` | verified |  |
| grafana | `pkg/api/user_token_test.go` | verified |  |
| grafana | `pkg/plugins/filepath.go` | verified |  |
| grafana | `pkg/services/auth/auth.go` | verified |  |
| grafana | `pkg/services/authz/zanzana/common/translations_test.go` | verified |  |
| grafana | `pkg/services/serviceaccounts/secretscan/service.go` | verified |  |
| grafana | `pkg/services/user/userimpl/time.go` | verified |  |
| grafana | `pkg/tests/api/loki/loki_test.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/metric_data_query_builder_test.go` | verified |  |
| grafana | `pkg/util/xorm/rows.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/settings/AlertmanagerConfig.tsx` | verified |  |
| grafana | `public/app/features/browse-dashboards/BrowseFolderLibraryPanelsPage.tsx` | verified |  |
| grafana | `public/app/features/dashboard/components/DashNav/DashNavButton.tsx` | verified |  |
| grafana | `public/app/features/variables/shared/testing/helpers.ts` | verified |  |
| grafana | `public/app/plugins/datasource/dashboard/DashboardQueryEditor.tsx` | verified |  |
