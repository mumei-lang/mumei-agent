# Target OSS no-LLM dogfooding audit — continuation 407 (batch 408)

Run: 2026-07-23T01:03:28.704671+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/arm64/ssa.go` | verified |  |
| go | `src/cmd/go/internal/base/env.go` | verified |  |
| go | `src/cmd/go/internal/envcmd/env.go` | verified |  |
| go | `src/cmd/go/internal/modfetch/fetch.go` | verified |  |
| go | `src/cmd/link/internal/ld/go.go` | verified |  |
| go | `src/go/doc/comment/html.go` | verified |  |
| go | `src/go/doc/comment/parse.go` | verified |  |
| go | `src/internal/abi/bounds.go` | verified |  |
| go | `src/internal/runtime/atomic/atomic_386.go` | verified |  |
| go | `src/internal/syscall/unix/nofollow_bsd.go` | verified |  |
| go | `src/math/rand/v2/regress_test.go` | verified |  |
| go | `src/os/stat_plan9.go` | verified |  |
| go | `src/simd/archsimd/_gen/simdgen/arm64/instruction_test.go` | verified |  |
| go | `src/text/template/funcs.go` | verified |  |
| go | `test/fixedbugs/bug13343.go` | verified |  |
| go | `test/fixedbugs/issue18149.go` | verified |  |
| go | `test/fixedbugs/issue29220.go` | verified |  |
| go | `test/fixedbugs/issue42076.go` | verified |  |
| go | `test/fixedbugs/issue52856.go` | verified |  |
| go | `test/import4.go` | verified |  |
| grafana | `apps/alerting/rules/pkg/app/rulesequence/membership_index_test.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/conversion/v2alpha1_to_v1_mappings_test.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/globalrole_spec_gen.go` | verified |  |
| grafana | `apps/logsdrilldown/pkg/apis/app/app.go` | verified |  |
| grafana | `apps/logsdrilldown/plugin/src/generated/logsdrilldowndefaultlabels/v1beta1/types.status.gen.ts` | verified |  |
| grafana | `apps/shorturl/pkg/app/validate.go` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/notifications.alerting/v0alpha1/index.ts` | verified |  |
| grafana | `packages/grafana-runtime/src/services/pluginSettings/hooks.ts` | verified |  |
| grafana | `pkg/api/dtos/dashboard.go` | verified |  |
| grafana | `pkg/expr/sql/frame_db_conv.go` | verified |  |
| grafana | `pkg/infra/log/requestTiming.go` | verified |  |
| grafana | `pkg/registry/apis/iam/authorizer.go` | verified |  |
| grafana | `pkg/registry/apis/query/routes.go` | verified |  |
| grafana | `pkg/services/loginattempt/loginattempttest/mock.go` | verified |  |
| grafana | `pkg/services/ngalert/api/tooling/definitions/testing.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/ualert/tables.go` | verified |  |
| grafana | `pkg/storage/unified/migrations/resources_test.go` | verified |  |
| grafana | `pkg/storage/unified/migrations/validator.go` | verified |  |
| grafana | `public/app/core/components/NestedFolderPicker/Trigger.tsx` | verified |  |
| grafana | `public/app/core/components/Select/ServiceAccountPicker.tsx` | verified |  |
| grafana | `public/app/core/internationalization/loadTranslations.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/mute-timings/MuteTimingTimeInterval.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/query-and-alert-condition/CloudDataSourceSelector.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/Sidebar/Cards/GhostSidebarCard.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/serialization/layoutSerializers/layoutSerializerRegistry.ts` | verified |  |
| grafana | `public/app/features/expressions/components/SqlExpressions/hooks/useSQLSchemas.ts` | verified |  |
| grafana | `public/app/features/logs/components/fieldSelector/getSuggestedFieldsFromTable.ts` | verified |  |
| grafana | `public/app/features/manage-dashboards/SnapshotListPage.tsx` | verified |  |
| grafana | `public/app/features/transformers/smoothing/smoothingEditor.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/language/metric-math/completion/types.ts` | verified |  |
