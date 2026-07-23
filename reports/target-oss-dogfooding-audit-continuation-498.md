# Target OSS no-LLM dogfooding audit — continuation 498 (batch 499)

Run: 2026-07-23T06:40:11.859352+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/base/hashdebug_test.go` | verified |  |
| go | `src/cmd/go/main.go` | verified |  |
| go | `src/cmd/link/dwarf_test.go` | verified |  |
| go | `src/internal/poll/sendfile_unix.go` | verified |  |
| go | `src/internal/profile/graph.go` | verified |  |
| go | `src/internal/zstd/zstd_test.go` | verified |  |
| go | `src/math/cmplx/rect.go` | verified |  |
| go | `src/net/tcpsockopt_darwin.go` | verified |  |
| go | `src/os/sticky_notbsd.go` | verified |  |
| go | `src/runtime/cpuflags_amd64.go` | verified |  |
| go | `src/syscall/export_wasip1_test.go` | verified |  |
| go | `src/syscall/ztypes_openbsd_riscv64.go` | verified |  |
| go | `test/abi/named_return_stuff.go` | verified |  |
| go | `test/codegen/bool.go` | verified |  |
| go | `test/fixedbugs/issue15550.go` | verified |  |
| go | `test/fixedbugs/issue20923.go` | verified |  |
| go | `test/fixedbugs/issue23311.go` | verified |  |
| go | `test/fixedbugs/issue41440.go` | verified |  |
| go | `test/literal2.go` | verified |  |
| go | `test/parentype.go` | verified |  |
| go | `test/sliceopt.go` | verified |  |
| go | `test/typeparam/issue47713.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v0alpha1/routingtree_ext.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/types.go` | verified |  |
| grafana | `apps/provisioning/pkg/connection/github/connection_test.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/config_repository_mock.go` | verified |  |
| grafana | `packages/grafana-runtime/src/services/CorrelationsService.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/ContextMenu/WithContextMenu.tsx` | verified |  |
| grafana | `pkg/apiserver/rest/dualwriter.go` | verified |  |
| grafana | `pkg/configprovider/configprovider.go` | verified |  |
| grafana | `pkg/registry/apis/iam/datasourcek8s/legacy.go` | verified |  |
| grafana | `pkg/registry/apis/preferences/preferences_merged_test.go` | verified |  |
| grafana | `pkg/services/apiserver/clientgenerator.go` | verified |  |
| grafana | `pkg/services/ldap/settings_test.go` | verified |  |
| grafana | `pkg/services/ngalert/provisioning/persist.go` | verified |  |
| grafana | `pkg/services/ngalert/sender/notifier_ext.go` | verified |  |
| grafana | `pkg/services/preference/prefimpl/pref_test.go` | verified |  |
| grafana | `pkg/services/shorturls/shorturlimpl/shorturl_test.go` | verified |  |
| grafana | `pkg/storage/unified/migrations/resources.go` | verified |  |
| grafana | `pkg/storage/unified/sql/db/dbimpl/db_engine_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/bom_test.go` | verified |  |
| grafana | `pkg/tsdb/grafana-testdata-datasource/sims/utils_test.go` | verified |  |
| grafana | `pkg/util/xorm/sequence.go` | verified |  |
| grafana | `pkg/util/xorm/session_delete.go` | verified |  |
| grafana | `public/app/features/admin/ldap/LdapUserInfo.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/hooks/usePagination.ts` | verified |  |
| grafana | `public/app/features/dashboard/components/ShareModal/ShareModal.tsx` | verified |  |
| grafana | `public/app/features/dashboard/dashgrid/DashboardLibrary/analytics/main.ts` | verified |  |
| grafana | `public/app/features/playlist/PlaylistCard.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/influxdb/components/editor/query/influxql/utils/partListUtils.tsx` | verified |  |
