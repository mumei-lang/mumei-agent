# Target OSS no-LLM dogfooding audit — continuation 520 (batch 521)

Run: 2026-07-23T07:53:17.903362+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/archive/tar/stat_actime2.go` | verified |  |
| go | `src/bufio/net_test.go` | verified |  |
| go | `src/cmd/cgo/internal/test/issue8828.go` | verified |  |
| go | `src/cmd/cgo/internal/testtls/tls_test.go` | verified |  |
| go | `src/cmd/compile/internal/noder/unified.go` | verified |  |
| go | `src/cmd/compile/internal/staticdata/embed.go` | verified |  |
| go | `src/cmd/go/internal/test/genflags.go` | verified |  |
| go | `src/internal/routebsd/route.go` | verified |  |
| go | `src/math/exp2_asm.go` | verified |  |
| go | `src/net/internal/socktest/main_unix_test.go` | verified |  |
| go | `src/runtime/mfinal.go` | verified |  |
| go | `src/runtime/os_android.go` | verified |  |
| go | `src/runtime/syscall_windows_test.go` | verified |  |
| go | `src/simd/archsimd/_gen/simdgen/xed.go` | verified |  |
| go | `src/syscall/wtf8_windows_test.go` | verified |  |
| go | `src/syscall/zerrors_darwin_arm64.go` | verified |  |
| go | `test/fixedbugs/bug024.go` | verified |  |
| go | `test/fixedbugs/issue24159.go` | verified |  |
| go | `test/fixedbugs/issue38746.go` | verified |  |
| go | `test/inline_literal.go` | verified |  |
| go | `test/typeparam/pairimp.dir/a.go` | verified |  |
| go | `test/typeparam/typeswitch2.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v0alpha1/routingtree_client_gen.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v0alpha1/routingtree_object_gen.go` | verified |  |
| grafana | `e2e-playwright/test-plugins/grafana-test-datasource/webpack.config.ts` | verified |  |
| grafana | `packages/grafana-data/src/transformations/matchers/valueMatchers/types.ts` | verified |  |
| grafana | `packages/grafana-data/src/utils/LocalStorageValueProvider.tsx` | verified |  |
| grafana | `pkg/apis/appplugin/v0alpha1/zz_generated.defaults.go` | verified |  |
| grafana | `pkg/registry/apis/dashboard/search_test.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/migrate/unifiedstorage.go` | verified |  |
| grafana | `pkg/services/authz/zanzana/server/server_mutate_org_role_test.go` | verified |  |
| grafana | `pkg/services/authz/zanzana/server/server_store_test.go` | verified |  |
| grafana | `pkg/services/ngalert/accesscontrol/accesscontrol.go` | verified |  |
| grafana | `pkg/services/ngalert/sender/testing.go` | verified |  |
| grafana | `pkg/services/quota/quotaimpl/store.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/accesscontrol/seed_assignment.go` | verified |  |
| grafana | `pkg/services/store/file_guardian.go` | verified |  |
| grafana | `pkg/storage/unified/resourcepb/resource_grpc.pb.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/client_test.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/sort_frame.go` | verified |  |
| grafana | `pkg/tsdb/jaeger/callresource.go` | verified |  |
| grafana | `public/app/features/apiserver/types.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/edit-pane/dashboard/DraggableListItem.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/variables/editors/CustomVariableEditor/getCustomVariableOptions.tsx` | verified |  |
| grafana | `public/app/features/dashboard/containers/PublicDashboardPageProxy.tsx` | verified |  |
| grafana | `public/app/features/migrate-to-cloud/onprem/EmptyState/InfoPaneLeft.tsx` | verified |  |
| grafana | `public/app/features/panel/components/VizTypePicker/VizTypePickerPlugin.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/VariableEditor/GrafanaTemplateVariableFn.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/components/shared/LogGroups/LogGroupsSelector.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/loki/components/monaco-query-field/monaco-completion-provider/completionUtils.ts` | verified |  |
