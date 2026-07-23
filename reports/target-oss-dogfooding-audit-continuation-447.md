# Target OSS no-LLM dogfooding audit — continuation 447 (batch 448)

Run: 2026-07-23T02:55:06.307354+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/go/internal/doc/signal_notunix.go` | verified |  |
| go | `src/cmd/internal/obj/arm64/asm7.go` | verified |  |
| go | `src/crypto/elliptic/elliptic.go` | verified |  |
| go | `src/internal/syscall/unix/copy_file_range_unix.go` | verified |  |
| go | `src/runtime/iface.go` | verified |  |
| go | `src/runtime/signal_openbsd_386.go` | verified |  |
| go | `src/simd/archsimd/internal/simd_test/unary_helpers_wider_test.go` | verified |  |
| go | `src/sort/search.go` | verified |  |
| go | `src/syscall/syscall_freebsd_test.go` | verified |  |
| go | `src/text/template/option.go` | verified |  |
| go | `test/fixedbugs/bug322.dir/main.go` | verified |  |
| go | `test/fixedbugs/issue24491b.go` | verified |  |
| go | `test/fixedbugs/issue30908.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue36259.go` | verified |  |
| go | `test/fixedbugs/issue3705.go` | verified |  |
| go | `test/fixedbugs/issue43570.go` | verified |  |
| go | `test/fixedbugs/issue52127.go` | verified |  |
| go | `test/fixedbugs/issue5493.go` | verified |  |
| go | `test/fixedbugs/issue75569.go` | verified |  |
| go | `test/shift1.go` | verified |  |
| go | `test/typeparam/listimp2.dir/main.go` | verified |  |
| go | `test/wasmmemsize.dir/main.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/git/repository.go` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/dashboard/v2/endpoints.gen.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/CodeMirror/sqlFolding.ts` | verified |  |
| grafana | `pkg/api/admin_users_test.go` | verified |  |
| grafana | `pkg/cmd/grafana/main_test.go` | verified |  |
| grafana | `pkg/expr/classic/reduce_test.go` | verified |  |
| grafana | `pkg/expr/testing.go` | verified |  |
| grafana | `pkg/services/apiserver/aggregatorrunner/runner.go` | verified |  |
| grafana | `pkg/services/authn/error.go` | verified |  |
| grafana | `pkg/services/ngalert/remote/client/alertmanager_limits.go` | verified |  |
| grafana | `pkg/services/scimutil/scim_util.go` | verified |  |
| grafana | `pkg/services/secrets/kvstore/cache.go` | verified |  |
| grafana | `pkg/services/sqlstore/logger.go` | verified |  |
| grafana | `pkg/storage/unified/informer/informer.go` | verified |  |
| grafana | `public/app/features/alerting/unified/api/prometheus.ts` | verified |  |
| grafana | `public/app/features/browse-dashboards/types.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/assistant/DashboardAssistantViewMode.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/edit-pane/dashboard/DashboardLinksList.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/edit-pane/dashboard/DroppableCategory.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/variables/components/VariableLegend.tsx` | verified |  |
| grafana | `public/app/features/explore/ExploreDrawer.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/utils/config/get-config.tsx` | verified |  |
| grafana | `public/app/features/playlist/PlaylistSrv.ts` | verified |  |
| grafana | `public/app/features/provisioning/Wizard/hooks/useWizardSubmission.ts` | verified |  |
| grafana | `public/app/features/templating/types.ts` | verified |  |
| grafana | `public/app/features/variables/pickers/shared/VariableOptions.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/components/shared/LogGroups/LogGroupClassSelector.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/graphite/state/helpers.ts` | verified |  |
