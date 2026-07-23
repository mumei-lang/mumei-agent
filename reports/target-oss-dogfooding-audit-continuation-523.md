# Target OSS no-LLM dogfooding audit — continuation 523 (batch 524)

Run: 2026-07-23T08:07:07.747829+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/types/type.go` | verified |  |
| go | `src/cmd/link/internal/ld/data_test.go` | verified |  |
| go | `src/internal/dag/parse.go` | verified |  |
| go | `src/internal/goarch/zgoarch_mips64p32.go` | verified |  |
| go | `src/internal/goarch/zgoarch_ppc64le.go` | verified |  |
| go | `src/internal/poll/fd_poll_js.go` | verified |  |
| go | `src/internal/trace/mud_test.go` | verified |  |
| go | `src/os/exec/env_test.go` | verified |  |
| go | `src/runtime/cgo/windows.go` | verified |  |
| go | `src/slices/slices_test.go` | verified |  |
| go | `src/sync/runtime2.go` | verified |  |
| go | `src/syscall/sockcmsg_linux.go` | verified |  |
| go | `src/syscall/zsyscall_linux_amd64.go` | verified |  |
| go | `test/assign1.go` | verified |  |
| go | `test/fixedbugs/bug452.go` | verified |  |
| go | `test/fixedbugs/issue29612.dir/p2/ssa/ssa.go` | verified |  |
| go | `test/fixedbugs/issue32477.go` | verified |  |
| go | `test/fixedbugs/issue34520.go` | verified |  |
| go | `test/fixedbugs/issue43112.go` | verified |  |
| go | `test/init1.go` | verified |  |
| go | `test/interface/embed2.go` | verified |  |
| go | `test/typeparam/gencrawler.dir/main.go` | verified |  |
| go | `test/typeparam/issue47684b.go` | verified |  |
| go | `test/typeparam/issue48454.dir/a.go` | verified |  |
| go | `test/typeparam/issue50690c.go` | verified |  |
| grafana | `e2e-playwright/dashboard-cujs/cuj-selectors.ts` | verified |  |
| grafana | `packages/grafana-data/src/themes/zIndex.ts` | verified |  |
| grafana | `packages/grafana-data/src/types/layout.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Combobox/useComboboxFloat.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Select/SelectOptionGroupHeader.tsx` | verified |  |
| grafana | `pkg/codegen/jenny_go_spec.go` | verified |  |
| grafana | `pkg/infra/nats/config.go` | verified |  |
| grafana | `pkg/plugins/manager/pipeline/bootstrap/steps_test.go` | verified |  |
| grafana | `pkg/registry/apps/alerting/notifications/timeinterval/authorize.go` | verified |  |
| grafana | `pkg/services/apiserver/appinstaller/storage.go` | verified |  |
| grafana | `pkg/services/datasources/service/store_test.go` | verified |  |
| grafana | `pkg/services/ngalert/provisioning/testing.go` | verified |  |
| grafana | `pkg/storage/unified/sql/sqltemplate/dialect_test.go` | verified |  |
| grafana | `pkg/tsdb/azuremonitor/azmoncredentials/default.go` | verified |  |
| grafana | `public/app/core/hooks/useNavModel.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rules/RuleDetailsMatchingInstances.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/hooks/abilities/abilityUtils.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/rule-list/components/AlertRuleListItemLoader.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/pages/DashboardScenePageStateManager.ts` | verified |  |
| grafana | `public/app/features/dashboard/components/DashNav/DashNav.tsx` | verified |  |
| grafana | `public/app/features/datasources/components/picker/VirtualizedList.tsx` | verified |  |
| grafana | `public/app/features/provisioning/GettingStarted/features.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/mocks/dashboardOnLoadedEvent.ts` | verified |  |
| grafana | `public/app/plugins/panel/candlestick/fields.ts` | verified |  |
| grafana | `public/app/plugins/panel/nodeGraph/useFocusPositionOnLayout.ts` | verified |  |
