# Target OSS no-LLM dogfooding audit — continuation 489 (batch 490)

Run: 2026-07-23T06:16:14.323493+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/abt/avlint32_test.go` | verified |  |
| go | `src/cmd/gofmt/long_test.go` | verified |  |
| go | `src/cmd/internal/obj/abi_string.go` | verified |  |
| go | `src/cmd/link/internal/ld/ld_test.go` | verified |  |
| go | `src/crypto/internal/boring/aes.go` | verified |  |
| go | `src/crypto/sha1/sha1.go` | verified |  |
| go | `src/go/parser/interface.go` | verified |  |
| go | `src/internal/poll/fd_writev_libc.go` | verified |  |
| go | `src/io/fs/glob.go` | verified |  |
| go | `src/net/error_windows_test.go` | verified |  |
| go | `src/os/file_plan9.go` | verified |  |
| go | `src/os/stat_wasip1.go` | verified |  |
| go | `src/runtime/malloc_tables_generated.go` | verified |  |
| go | `src/runtime/secret/export.go` | verified |  |
| go | `src/simd/archsimd/export_test.go` | verified |  |
| go | `src/simd/archsimd/internal/simd_test/slicepart_wider_test.go` | verified |  |
| go | `src/syscall/zsyscall_linux_s390x.go` | verified |  |
| go | `test/fixedbugs/bug367.dir/p.go` | verified |  |
| go | `test/fixedbugs/issue22683.go` | verified |  |
| go | `test/fixedbugs/issue6572.go` | verified |  |
| go | `test/typeparam/issue50486.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v1beta1/timeinterval_codec_gen.go` | verified |  |
| grafana | `apps/alerting/rules/pkg/apis/alerting/v0alpha1/alertrule_spec_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/applyconfiguration/provisioning/v0alpha1/githubrepositoryconfig.go` | verified |  |
| grafana | `packages/grafana-data/src/datetime/formats.ts` | verified |  |
| grafana | `packages/grafana-data/src/datetime/parser.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/DateTimePickers/TimeRangePicker/TimePickerContent.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/PanelChrome/types.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/TableRT/HeaderRow.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/VizLegend/VizLegendListItem.tsx` | verified |  |
| grafana | `pkg/generated/clientset/versioned/fake/doc.go` | verified |  |
| grafana | `pkg/infra/filestorage/test_utils.go` | verified |  |
| grafana | `pkg/plugins/config/config.go` | verified |  |
| grafana | `pkg/registry/apis/datasource/plugincontext.go` | verified |  |
| grafana | `pkg/services/accesscontrol/filter_bench_test.go` | verified |  |
| grafana | `pkg/services/quota/model.go` | verified |  |
| grafana | `pkg/services/temp_user/temp_user.go` | verified |  |
| grafana | `pkg/setting/setting_folder.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/service.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/QueryRows.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rules/AlertStateTag.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/mocks/server/handlers/eval.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/triage/instance-details/DrawerTimeRangeInfoBanner.tsx` | verified |  |
| grafana | `public/app/features/expressions/components/SqlExpressions/sqlExpressionContext.ts` | verified |  |
| grafana | `public/app/features/inspector/utils/download.ts` | verified |  |
| grafana | `public/app/features/manage-dashboards/import/utils/floatingGridItems.ts` | verified |  |
| grafana | `public/app/features/provisioning/components/utils/folderName.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/components/QueryEditor/MetricsQueryEditor/SQLBuilderEditor/SQLBuilderSelectRow.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/resources/ResourcesAPI.ts` | verified |  |
| grafana | `public/app/plugins/datasource/influxdb/components/editor/query/influxql/code/RawInfluxQLEditor.tsx` | verified |  |
