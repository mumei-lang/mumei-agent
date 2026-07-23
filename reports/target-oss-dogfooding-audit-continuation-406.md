# Target OSS no-LLM dogfooding audit — continuation 406 (batch 407)

Run: 2026-07-23T00:57:37.403352+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/types2/subst.go` | verified |  |
| go | `src/cmd/go/internal/test/testflag.go` | verified |  |
| go | `src/cmd/go/script_test.go` | verified |  |
| go | `src/crypto/internal/fips140/sha256/cast.go` | verified |  |
| go | `src/crypto/tls/conn.go` | verified |  |
| go | `src/go/format/benchmark_test.go` | verified |  |
| go | `src/html/template/content.go` | verified |  |
| go | `src/internal/syscall/windows/registry/export_test.go` | verified |  |
| go | `src/net/dnsclient_unix_test.go` | verified |  |
| go | `src/net/external_test.go` | verified |  |
| go | `src/os/exec_linux.go` | verified |  |
| go | `src/runtime/runtime1.go` | verified |  |
| go | `src/sort/zsortfunc.go` | verified |  |
| go | `src/syscall/ztypes_linux_loong64.go` | verified |  |
| go | `src/time/export_test.go` | verified |  |
| go | `test/fixedbugs/issue13799.go` | verified |  |
| go | `test/fixedbugs/issue15609.dir/call.go` | verified |  |
| go | `test/fixedbugs/issue16016.go` | verified |  |
| go | `test/fixedbugs/issue19261.dir/q.go` | verified |  |
| go | `test/fixedbugs/issue30907.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue48097.go` | verified |  |
| go | `test/fixedbugs/issue4932.dir/foo.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v1beta1/ext.go` | verified |  |
| grafana | `apps/alerting/rules/pkg/apis/alerting/v0alpha1/alertrule_ext.go` | verified |  |
| grafana | `e2e-playwright/dashboard-new-layouts/page-objects/sidebar/DashboardOptions.ts` | verified |  |
| grafana | `packages/grafana-data/src/transformations/transformers/concat.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/TableNG/Cells/SparklineCell.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/TableNG/components/EmptyTablePlaceholder.tsx` | verified |  |
| grafana | `pkg/api/dtos/acl.go` | verified |  |
| grafana | `pkg/api/index.go` | verified |  |
| grafana | `pkg/api/swagger.go` | verified |  |
| grafana | `pkg/plugins/manager/pipeline/initialization/steps_test.go` | verified |  |
| grafana | `pkg/services/authapi/authapi.go` | verified |  |
| grafana | `pkg/services/ldap/api/errors.go` | verified |  |
| grafana | `pkg/services/ngalert/state/historian/dashboard_test.go` | verified |  |
| grafana | `pkg/services/provisioning/stubs_test.go` | verified |  |
| grafana | `pkg/setting/setting_azure.go` | verified |  |
| grafana | `pkg/storage/unified/resource/grpc/authenticator_test.go` | verified |  |
| grafana | `pkg/tests/apis/preferences/anonymous_test.go` | verified |  |
| grafana | `public/app/api/clients/provisioning/v0alpha1/index.ts` | verified |  |
| grafana | `public/app/core/services/echo/EchoSrv.ts` | verified |  |
| grafana | `public/app/core/services/echo/backends/analytics/RudderstackV3Backend.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/receivers/grafanaAppReceivers/ReceiverMetadataBadge.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/silences/SilencesFilter.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/routeGroupsMatcher.worker.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/utils/datasource.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/UnlinkLibraryPanelModal.tsx` | verified |  |
| grafana | `public/app/features/serviceaccounts/components/ServiceAccountProfileRow.tsx` | verified |  |
| grafana | `public/app/features/variables/textbox/actions.ts` | verified |  |
| grafana | `public/app/plugins/panel/canvas/components/SetBackground.tsx` | verified |  |
