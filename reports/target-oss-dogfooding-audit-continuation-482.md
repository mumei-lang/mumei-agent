# Target OSS no-LLM dogfooding audit — continuation 482 (batch 483)

Run: 2026-07-23T05:42:24.059330+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/test/issue21897.go` | verified |  |
| go | `src/cmd/cgo/internal/test/issue30527/a.go` | verified |  |
| go | `src/cmd/go/internal/vcweb/git.go` | verified |  |
| go | `src/cmd/internal/obj/sizeof_test.go` | verified |  |
| go | `src/compress/bzip2/move_to_front.go` | verified |  |
| go | `src/crypto/internal/fips140/check/checktest/asm_none.go` | verified |  |
| go | `src/database/sql/example_cli_test.go` | verified |  |
| go | `src/go/types/universe.go` | verified |  |
| go | `src/internal/poll/sock_cloexec.go` | verified |  |
| go | `src/math/pow.go` | verified |  |
| go | `src/regexp/syntax/op_string.go` | verified |  |
| go | `src/runtime/defs_solaris_amd64.go` | verified |  |
| go | `src/runtime/heapdump.go` | verified |  |
| go | `src/runtime/mranges_test.go` | verified |  |
| go | `src/runtime/signal_openbsd_arm64.go` | verified |  |
| go | `src/simd/internal/bridge/import_hook.go` | verified |  |
| go | `src/sync/map.go` | verified |  |
| go | `test/fixedbugs/bug084.go` | verified |  |
| go | `test/fixedbugs/issue23912.go` | verified |  |
| go | `test/fixedbugs/issue68580.go` | verified |  |
| go | `test/range3.go` | verified |  |
| go | `test/typeparam/issue50481b.go` | verified |  |
| go | `test/typeparam/issue51522b.go` | verified |  |
| go | `test/typeparam/mdempsky/1.dir/a.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v32_test.go` | verified |  |
| grafana | `apps/live/pkg/apis/live/v1alpha1/channel_codec_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/factory_test.go` | verified |  |
| grafana | `packages/grafana-data/src/types/dashboard.ts` | verified |  |
| grafana | `packages/grafana-flamegraph/src/FlameGraph/testHelpers.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/DataLinks/DataLinksInlineEditor/DataLinksListItemBase.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/themes/GlobalStyles/code.ts` | verified |  |
| grafana | `pkg/apimachinery/apis/common/v0alpha1/zz_generated.defaults.go` | verified |  |
| grafana | `pkg/apis/datasource/v0alpha1/unstructured.go` | verified |  |
| grafana | `pkg/infra/log/databaseQueryTimer.go` | verified |  |
| grafana | `pkg/registry/apis/folders/continue_test.go` | verified |  |
| grafana | `pkg/registry/apis/iam/user/legacy_search_fake.go` | verified |  |
| grafana | `pkg/registry/apps/annotation/postgres_schema_test.go` | verified |  |
| grafana | `pkg/services/secrets/manager/manager.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/connection/repositories_test.go` | verified |  |
| grafana | `pkg/tsdb/loki/streaming.go` | verified |  |
| grafana | `pkg/tsdb/mysql/mysql_snapshot_test.go` | verified |  |
| grafana | `public/app/features/alerting/unified/hooks/useAlertmanagerConfig.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/insights/mimir/perGroup/RuleGroupEvaluationDurationIntervalRatioScene.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/rule-list/hooks/useAlertsActivityBannerPrefs.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/export/exporters.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/variables/VariableEditorListRow.tsx` | verified |  |
| grafana | `public/app/features/plugins/admin/mocks/localPlugin.mock.ts` | verified |  |
| grafana | `public/app/features/plugins/extensions/utils.tsx` | verified |  |
| grafana | `public/app/features/sandbox/TestStuffPage.tsx` | verified |  |
| grafana | `public/app/plugins/panel/timeseries/InsertNullsEditor.tsx` | verified |  |
