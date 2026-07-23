# Target OSS no-LLM dogfooding audit — continuation 543 (batch 544)

Run: 2026-07-23T09:56:31.131433+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ssa/magic_test.go` | verified |  |
| go | `src/cmd/go/internal/auth/httputils.go` | verified |  |
| go | `src/cmd/link/internal/sym/symbol.go` | verified |  |
| go | `src/cmd/trace/goroutinegen.go` | verified |  |
| go | `src/crypto/internal/fips140/aes/cbc_s390x.go` | verified |  |
| go | `src/crypto/internal/fips140/purego.go` | verified |  |
| go | `src/crypto/tls/handshake_messages_test.go` | verified |  |
| go | `src/encoding/hex/hex_test.go` | verified |  |
| go | `src/internal/goarch/zgoarch_arm64.go` | verified |  |
| go | `src/internal/goos/zgoos_dragonfly.go` | verified |  |
| go | `src/internal/syscall/windows/registry/mksyscall.go` | verified |  |
| go | `src/net/http/internal/http2/netconn_test.go` | verified |  |
| go | `src/net/textproto/writer.go` | verified |  |
| go | `src/os/exec/exec_unix_test.go` | verified |  |
| go | `src/os/exec/read3.go` | verified |  |
| go | `src/runtime/stubs_nonwasm.go` | verified |  |
| go | `test/fixedbugs/bug314.go` | verified |  |
| go | `test/fixedbugs/bug352.go` | verified |  |
| go | `test/fixedbugs/bug365.go` | verified |  |
| go | `test/fixedbugs/gcc61253.go` | verified |  |
| go | `test/fixedbugs/issue17111.go` | verified |  |
| go | `test/fixedbugs/issue29610.dir/main.go` | verified |  |
| go | `test/fixedbugs/issue30116u.go` | verified |  |
| go | `test/fixedbugs/issue32901.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue43479.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue4470.go` | verified |  |
| go | `test/fixedbugs/issue48230.go` | verified |  |
| go | `test/fixedbugs/issue74935.go` | verified |  |
| go | `test/fixedbugs/issue75764.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/testutil/mocks.go` | verified |  |
| grafana | `apps/folder/pkg/apis/folder/v1/types.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/github/client.go` | verified |  |
| grafana | `packages/grafana-ui/src/components/Badge/Badge.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/ColorPicker/ColorPicker.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/TableNG/Cells/ImageCell.tsx` | verified |  |
| grafana | `pkg/operators/register.go` | verified |  |
| grafana | `pkg/registry/apis/iam/team/store.go` | verified |  |
| grafana | `pkg/services/annotations/annotationsimpl/loki/historian_store.go` | verified |  |
| grafana | `pkg/services/authz/rbac/service_test.go` | verified |  |
| grafana | `pkg/services/ngalert/api/api_alertmanager_silences_test.go` | verified |  |
| grafana | `pkg/services/ngalert/store/provisioning_store.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/pluginslog/pluginslog.go` | verified |  |
| grafana | `pkg/tests/api/plugins/backendplugin/backendplugin_test.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/models/api.go` | verified |  |
| grafana | `public/app/features/alerting/unified/hooks/useUpsertUngroupedGrafanaRule.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/rule-list/components/DataSourceErrorBoundary.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/edit-pane/VizPanelEditableElement.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/panel-actions/PanelGroupByAction/PanelGroupByAction.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/sharing/public-dashboards/utils.ts` | verified |  |
| grafana | `public/app/plugins/panel/dashlist/DashListItem.tsx` | verified |  |
