# Target OSS no-LLM dogfooding audit — continuation 533 (batch 534)

Run: 2026-07-23T09:09:18.135329+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ir/dump_test.go` | verified |  |
| go | `src/cmd/internal/script/conds.go` | verified |  |
| go | `src/crypto/mlkem/mlkem_wycheproof_test.go` | verified |  |
| go | `src/internal/abi/abi_test.go` | verified |  |
| go | `src/internal/copyright/copyright_test.go` | verified |  |
| go | `src/internal/goexperiment/exp_mapsplitgroup_off.go` | verified |  |
| go | `src/os/exec/exec_windows.go` | verified |  |
| go | `src/runtime/mem_bsd.go` | verified |  |
| go | `src/runtime/numcpu_freebsd_test.go` | verified |  |
| go | `src/syscall/exec_libc.go` | verified |  |
| go | `src/syscall/sockcmsg_unix_other.go` | verified |  |
| go | `src/syscall/syscall_linux_arm64.go` | verified |  |
| go | `test/fixedbugs/issue16249.go` | verified |  |
| go | `test/fixedbugs/issue21879.go` | verified |  |
| go | `test/fixedbugs/issue30085.go` | verified |  |
| go | `test/fixedbugs/issue42703.go` | verified |  |
| go | `test/fixedbugs/issue4359.go` | verified |  |
| go | `test/fixedbugs/issue51401.go` | verified |  |
| go | `test/fixedbugs/issue7550.go` | verified |  |
| go | `test/fixedbugs/issue8017.go` | verified |  |
| go | `test/fixedbugs/issue8042.go` | verified |  |
| go | `test/fixedbugs/issue9006.go` | verified |  |
| go | `test/import2.go` | verified |  |
| go | `test/ken/shift.go` | verified |  |
| go | `test/stack.go` | verified |  |
| grafana | `apps/advisor/pkg/app/checks/plugincheck/check_test.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v0alpha1/ext.go` | verified |  |
| grafana | `packages/grafana-data/src/themes/createSpacing.ts` | verified |  |
| grafana | `pkg/expr/converter.go` | verified |  |
| grafana | `pkg/expr/dataplane.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/webhooks/pullrequest/changes.go` | verified |  |
| grafana | `pkg/registry/apps/alerting/notifications/templategroup/legacy_storage.go` | verified |  |
| grafana | `pkg/services/accesscontrol/authorizer_test.go` | verified |  |
| grafana | `pkg/services/authz/rbac/cache.go` | verified |  |
| grafana | `pkg/services/ngalert/accesscontrol/silences_test.go` | verified |  |
| grafana | `pkg/services/ngalert/api/tooling/definitions/provisioning_contactpoints.go` | verified |  |
| grafana | `pkg/services/provisioning/alerting/mute_times_provisioner.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/ualert/state_firedat_mig.go` | verified |  |
| grafana | `pkg/storage/unified/resource/kv/last_import_time.go` | verified |  |
| grafana | `pkg/tsdb/azuremonitor/metrics/migrations_test.go` | verified |  |
| grafana | `pkg/tsdb/influxdb/influxql/util/util.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/backtesting/BacktestDropdownButton.tsx` | verified |  |
| grafana | `public/app/features/connections/mocks/store.navIndex.mock.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/layout-auto-grid/AutoGridLayoutManager.tsx` | verified |  |
| grafana | `public/app/features/datasources/components/DataSourceFailureBadge.tsx` | verified |  |
| grafana | `public/app/features/explore/RichHistory/RichHistorySettingsTab.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/utils/tags.ts` | verified |  |
| grafana | `public/app/features/expressions/utils/interpolateSourceQueries.ts` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/mocks/instanceSettings.ts` | verified |  |
| grafana | `public/app/plugins/datasource/influxdb/components/editor/query/influxql/utils/getTemplateVariableOptions.ts` | verified |  |
