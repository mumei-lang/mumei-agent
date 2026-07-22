# Target OSS no-LLM dogfooding audit — continuation 364 (batch 365)

Run: 2026-07-22T22:00:02.851506+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ssa/rewrite.go` | verified |  |
| go | `src/cmd/go/internal/modfetch/codehost/git_test.go` | verified |  |
| go | `src/cmd/go/internal/modfetch/sumdb.go` | verified |  |
| go | `src/database/sql/driver/driver.go` | verified |  |
| go | `src/debug/pe/string.go` | verified |  |
| go | `src/go/ast/issues_test.go` | verified |  |
| go | `src/hash/crc32/crc32_amd64.go` | verified |  |
| go | `src/internal/runtime/gc/scan/expand_amd64.go` | verified |  |
| go | `src/internal/trace/tracev1.go` | verified |  |
| go | `src/internal/zstd/huff.go` | verified |  |
| go | `src/math/rand/v2/chacha8_test.go` | verified |  |
| go | `src/os/path_unix.go` | verified |  |
| go | `src/runtime/mpagealloc_32bit.go` | verified |  |
| go | `src/simd/archsimd/_gen/midway/intersect_simd_ops.go` | verified |  |
| go | `src/simd/doc.go` | verified |  |
| go | `test/asmhdr.go` | verified |  |
| go | `test/codegen/multiply.go` | verified |  |
| go | `test/fixedbugs/bug382.dir/pkg.go` | verified |  |
| go | `test/fixedbugs/issue42058b.go` | verified |  |
| go | `test/fixedbugs/issue6703j.go` | verified |  |
| go | `test/typeparam/issue50121.dir/main.go` | verified |  |
| grafana | `apps/logsdrilldown/plugin/src/generated/logsdrilldowndefaultcolumns/v1beta1/types.status.gen.ts` | verified |  |
| grafana | `packages/grafana-alerting/src/grafana/mocks/util.ts` | verified |  |
| grafana | `packages/grafana-runtime/src/services/JourneyTracker.ts` | verified |  |
| grafana | `packages/grafana-sql/src/datasource/SqlDatasource.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Select/InputControl.tsx` | verified |  |
| grafana | `pkg/apimachinery/identity/context.go` | verified |  |
| grafana | `pkg/registry/apis/iam/authorizer/resource_permissions.go` | verified |  |
| grafana | `pkg/registry/apis/secret/testutils/fake_aws_secrets_manager.go` | verified |  |
| grafana | `pkg/registry/apis/secret/testutils/model_gsm.go` | verified |  |
| grafana | `pkg/services/ngalert/store/alert_rule_test.go` | verified |  |
| grafana | `pkg/services/provisioning/alerting/text_templates_types.go` | verified |  |
| grafana | `pkg/storage/unified/sql/sqltemplate/dialect_mysql.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/get_metric_query_batches.go` | verified |  |
| grafana | `pkg/util/xorm/session_insert.go` | verified |  |
| grafana | `pkg/util/xorm/statement_exprparam.go` | verified |  |
| grafana | `public/app/app.ts` | verified |  |
| grafana | `public/app/features/admin/utils.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/QueryEditor.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/insights/SectionFooter.tsx` | verified |  |
| grafana | `public/app/features/correlations/Forms/CorrelationFormNavigation.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/conditional-rendering/conditions/ConditionalRenderingConditionWrapper.tsx` | verified |  |
| grafana | `public/app/features/datasources/components/ButtonRow.tsx` | verified |  |
| grafana | `public/app/features/explore/Logs/LogsVolumePanel.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/TraceTimelineViewer/SpanDetail/AccordionReferences.tsx` | verified |  |
| grafana | `public/app/features/panel/table/addTableCustomConfig.ts` | verified |  |
| grafana | `public/app/features/provisioning/Job/RecentJobs.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/language/cloudwatch-ppl/tokenTypes.ts` | verified |  |
| grafana | `public/app/plugins/datasource/loki/components/LokiQueryEditor.tsx` | verified |  |
| grafana | `public/app/plugins/panel/alertlist/unified-alerting/GroupedView.tsx` | verified |  |
