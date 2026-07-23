# Target OSS no-LLM dogfooding audit — continuation 471 (batch 472)

Run: 2026-07-23T04:45:12.439430+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/test/issue8517_windows.go` | verified |  |
| go | `src/context/context.go` | verified |  |
| go | `src/crypto/internal/fips140/ecdh/order_test.go` | verified |  |
| go | `src/internal/dag/alg_test.go` | verified |  |
| go | `src/internal/runtime/atomic/atomic_test.go` | verified |  |
| go | `src/internal/syscall/unix/at_darwin.go` | verified |  |
| go | `src/internal/syscall/unix/constants.go` | verified |  |
| go | `src/net/http/httptest/httptest.go` | verified |  |
| go | `src/os/dirent_dragonfly.go` | verified |  |
| go | `src/os/exec/exec_linux_test.go` | verified |  |
| go | `src/os/exec/lp_plan9.go` | verified |  |
| go | `src/os/readfrom_freebsd_test.go` | verified |  |
| go | `src/runtime/cgo_mmap.go` | verified |  |
| go | `src/sync/atomic/atomic_test.go` | verified |  |
| go | `src/syscall/syscall_openbsd_amd64.go` | verified |  |
| go | `src/syscall/syscall_openbsd_arm.go` | verified |  |
| go | `src/syscall/zsysnum_netbsd_arm.go` | verified |  |
| go | `test/dwarf/dwarf.dir/z14.go` | verified |  |
| go | `test/escape_param.go` | verified |  |
| go | `test/fixedbugs/bug086.go` | verified |  |
| go | `test/fixedbugs/issue30659.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue32595.dir/main.go` | verified |  |
| grafana | `e2e-playwright/test-plugins/grafana-extensionstest-app/pages/Config.tsx` | verified |  |
| grafana | `packages/grafana-data/src/datetime/common.ts` | verified |  |
| grafana | `packages/grafana-schema/src/schema/variable/v2beta1/variable_object_gen.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/Cells/JSONViewCell.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/utils/useAsyncDependency.ts` | verified |  |
| grafana | `pkg/infra/usagestats/validator/impl.go` | verified |  |
| grafana | `pkg/plugins/manager/signature/authorizer.go` | verified |  |
| grafana | `pkg/registry/apis/iam/serviceaccount/store.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/response.go` | verified |  |
| grafana | `pkg/registry/apis/query/client/plugin.go` | verified |  |
| grafana | `pkg/registry/apis/secret/service/dev_tools/seed_values.go` | verified |  |
| grafana | `pkg/services/apiserver/client/discovery.go` | verified |  |
| grafana | `pkg/services/authn/clients/jwt.go` | verified |  |
| grafana | `pkg/services/ngalert/metrics/remote_alertmanager.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/alert_broadcast_test.go` | verified |  |
| grafana | `pkg/services/ngalert/store/alert_rule_backfill_test.go` | verified |  |
| grafana | `pkg/services/team/teamk8s/team.go` | verified |  |
| grafana | `pkg/tsdb/mysql/proxy.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/AnnotationsStep.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/DashboardPicker.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/silences/SilencedInstancesPreview.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/insights/grafana/RulesByEvaluationPercentage.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/addToDashboard/addToDashboard.ts` | verified |  |
| grafana | `public/app/features/panel/components/VizTypePicker/interactions.ts` | verified |  |
| grafana | `public/app/features/provisioning/Repository/RepositoryOverview.tsx` | verified |  |
| grafana | `public/app/features/provisioning/components/Shared/OrphanedResourceActionConfirmModal.tsx` | verified |  |
| grafana | `public/app/features/variables/state/selectors.ts` | verified |  |
| grafana | `public/app/plugins/panel/histogram/panelcfg.gen.ts` | verified |  |
