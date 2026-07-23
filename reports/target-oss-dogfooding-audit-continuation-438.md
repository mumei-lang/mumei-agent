# Target OSS no-LLM dogfooding audit — continuation 438 (batch 439)

Run: 2026-07-23T02:22:54.775352+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/archive/tar/writer.go` | verified |  |
| go | `src/cmd/cgo/internal/test/gcc68255.go` | verified |  |
| go | `src/cmd/cgo/internal/test/issue9400/gccgo.go` | verified |  |
| go | `src/cmd/compile/internal/syntax/printer_test.go` | verified |  |
| go | `src/crypto/sha1/sha1block_s390x.go` | verified |  |
| go | `src/debug/dwarf/entry_test.go` | verified |  |
| go | `src/encoding/gob/encode.go` | verified |  |
| go | `src/internal/runtime/syscall/linux/defs_linux_amd64.go` | verified |  |
| go | `src/math/tanh.go` | verified |  |
| go | `src/net/http/export_test.go` | verified |  |
| go | `src/net/internal/socktest/sys_windows.go` | verified |  |
| go | `src/os/root.go` | verified |  |
| go | `src/os/user/getgrouplist_unix.go` | verified |  |
| go | `src/reflect/benchmark_test.go` | verified |  |
| go | `src/runtime/defs_linux_arm.go` | verified |  |
| go | `src/simd/simd_types.go` | verified |  |
| go | `src/syscall/zsyscall_openbsd_amd64.go` | verified |  |
| go | `test/const5.go` | verified |  |
| go | `test/fixedbugs/bug077.go` | verified |  |
| go | `test/fixedbugs/bug176.go` | verified |  |
| go | `test/fixedbugs/issue16741.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/app/app.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/getsearchusers_response_types_gen.go` | verified |  |
| grafana | `packages/grafana-data/src/themes/palette_new.ts` | verified |  |
| grafana | `packages/grafana-data/src/transformations/matchers/mocks.ts` | verified |  |
| grafana | `packages/grafana-data/src/transformations/transformers/utils.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Combobox/ValuePill.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/DataLinksActionsTooltip.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/VizTooltip/VizTooltipContainer.tsx` | verified |  |
| grafana | `pkg/infra/remotecache/remotecache.go` | verified |  |
| grafana | `pkg/middleware/recovery.go` | verified |  |
| grafana | `pkg/registry/apps/annotation/legacy.go` | verified |  |
| grafana | `pkg/services/annotations/annotationsimpl/annotations.go` | verified |  |
| grafana | `pkg/services/datasources/service/datasource_test.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/compat_test.go` | verified |  |
| grafana | `pkg/services/ngalert/store/instance_database_bench_test.go` | verified |  |
| grafana | `pkg/services/secrets/kvstore/sql_test.go` | verified |  |
| grafana | `pkg/services/secrets/migrator/rollback.go` | verified |  |
| grafana | `pkg/util/ring/ring.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/export/GrafanaExportDrawer.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/import-to-gma/ImportToGMABanner.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/GrafanaFolderAndLabelsStep.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/settings/AlertmanagerCard.tsx` | verified |  |
| grafana | `public/app/features/scopes/dashboards/ScopesDashboardsTree.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/LogsQueryEditor/RawQuery.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/LogsQueryEditor/useMigrations.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/language/cloudwatch-logs-sql/completion/types.ts` | verified |  |
| grafana | `public/app/plugins/datasource/influxdb/components/editor/config-v2/constants.ts` | verified |  |
| grafana | `public/app/plugins/panel/geomap/layers/data/lastPointTracker.ts` | verified |  |
| grafana | `public/app/plugins/panel/timeseries/plugins/mocks/mockAnnotationFrames.ts` | verified |  |
