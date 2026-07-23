# Target OSS no-LLM dogfooding audit — continuation 536 (batch 537)

Run: 2026-07-23T09:15:00.627327+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/test/linux_ppc64x_test.go` | verified |  |
| go | `src/crypto/md5/md5block.go` | verified |  |
| go | `src/crypto/tls/conn_test.go` | verified |  |
| go | `src/go/doc/reader.go` | verified |  |
| go | `src/go/parser/parser_test.go` | verified |  |
| go | `src/internal/syscall/windows/version_windows_test.go` | verified |  |
| go | `src/internal/syscall/windows/zsyscall_windows.go` | verified |  |
| go | `src/math/big/int.go` | verified |  |
| go | `src/runtime/signal_arm.go` | verified |  |
| go | `src/runtime/sigtab_linux_mipsx.go` | verified |  |
| go | `src/syscall/syscall_unix.go` | verified |  |
| go | `test/alias3.dir/c.go` | verified |  |
| go | `test/codegen/arithmetic.go` | verified |  |
| go | `test/codegen/unsafe.go` | verified |  |
| go | `test/fixedbugs/bug109.go` | verified |  |
| go | `test/fixedbugs/bug396.dir/one.go` | verified |  |
| go | `test/fixedbugs/bug479.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue14006.go` | verified |  |
| go | `test/fixedbugs/issue17039.go` | verified |  |
| go | `test/fixedbugs/issue43551.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue4396a.go` | verified |  |
| go | `test/fixedbugs/issue51291.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue56990.go` | verified |  |
| go | `test/fixedbugs/issue58439.go` | verified |  |
| go | `test/fixedbugs/issue7525b.go` | verified |  |
| go | `test/fixedbugs/issue77815.go` | verified |  |
| go | `test/fixedbugs/issue8139.go` | verified |  |
| grafana | `apps/example/pkg/app/conversion.go` | verified |  |
| grafana | `apps/folder/pkg/apis/folder/v1/folder_codec_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/git/staged_test.go` | verified |  |
| grafana | `devenv/docker/blocks/prometheus_utf8/main.go` | verified |  |
| grafana | `packages/grafana-plugin-configs/types/custom.d.ts` | verified |  |
| grafana | `pkg/plugins/repo/errors.go` | verified |  |
| grafana | `pkg/registry/apps/alerting/rules/common/selectors_test.go` | verified |  |
| grafana | `pkg/registry/apps/annotation/instrumented_store.go` | verified |  |
| grafana | `pkg/services/accesscontrol/scope.go` | verified |  |
| grafana | `pkg/services/ngalert/backtesting/engine_test.go` | verified |  |
| grafana | `pkg/services/preference/timezone_test.go` | verified |  |
| grafana | `pkg/services/provisioning/plugins/plugin_provisioner_test.go` | verified |  |
| grafana | `pkg/tests/alertmanager/webhook.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/resourcekinds/files_test.go` | verified |  |
| grafana | `pkg/tsdb/grafana-testdata-datasource/standalone/datasource.go` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/layouts-shared/styles.ts` | verified |  |
| grafana | `public/app/features/dashboard/components/ShareModal/SharePublicDashboard/ModalAlerts/NoUpsertPermissionsAlert.tsx` | verified |  |
| grafana | `public/app/features/dashboard/components/SubMenu/DashboardLinksDashboard.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/TracePageHeader/SpanGraph/index.tsx` | verified |  |
| grafana | `public/app/features/explore/utils/queries.ts` | verified |  |
| grafana | `public/app/features/plugins/admin/components/SearchField.tsx` | verified |  |
| grafana | `public/app/features/variables/shared/testing/adHocVariableBuilder.ts` | verified |  |
| grafana | `public/app/plugins/panel/geomap/utils/actions.ts` | verified |  |
