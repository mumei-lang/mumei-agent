# Target OSS no-LLM dogfooding audit — continuation 514 (batch 515)

Run: 2026-07-23T07:40:30.660455+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ssa/_gen/simdWasmops.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/memcombine.go` | verified |  |
| go | `src/cmd/go/internal/base/signal.go` | verified |  |
| go | `src/crypto/cipher/cfb.go` | verified |  |
| go | `src/crypto/internal/rand/rand_fips140v1.0.go` | verified |  |
| go | `src/internal/trace/generation.go` | verified |  |
| go | `src/log/slog/example_custom_levels_test.go` | verified |  |
| go | `src/math/log.go` | verified |  |
| go | `src/simd/archsimd/_gen/sgutil/insert_ordered_map.go` | verified |  |
| go | `src/strings/builder.go` | verified |  |
| go | `src/testing/slogtest/example_test.go` | verified |  |
| go | `test/chan/nonblock.go` | verified |  |
| go | `test/devirtualization_nil_panics.go` | verified |  |
| go | `test/fixedbugs/bug068.go` | verified |  |
| go | `test/fixedbugs/bug088.go` | verified |  |
| go | `test/fixedbugs/issue10700.go` | verified |  |
| go | `test/fixedbugs/issue16439.go` | verified |  |
| go | `test/fixedbugs/issue19671.go` | verified |  |
| go | `test/fixedbugs/issue5515.go` | verified |  |
| go | `test/indirect.go` | verified |  |
| go | `test/torture.go` | verified |  |
| go | `test/typeparam/slices.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v0alpha1/snapshot_codec_gen.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v11_test.go` | verified |  |
| grafana | `packages/grafana-data/src/types/panel.ts` | verified |  |
| grafana | `packages/grafana-test-utils/src/handlers/api/search/handlers.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Forms/Legacy/Select/SelectOption.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/TableRT/ExpandedRow.tsx` | verified |  |
| grafana | `pkg/components/loki/lokihttp/client.go` | verified |  |
| grafana | `pkg/infra/nats/tls_test.go` | verified |  |
| grafana | `pkg/plugins/codegen/pfs/plugindef_types.go` | verified |  |
| grafana | `pkg/registry/apps/shorturl/conversions_test.go` | verified |  |
| grafana | `pkg/services/ngalert/backtesting/eval_query.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/accesscontrol/permission_migrator.go` | verified |  |
| grafana | `pkg/storage/unified/resource/notifier_shadow_test.go` | verified |  |
| grafana | `pkg/storage/unified/sql/sqltemplate/dialect_sqlite.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/models/resources/types.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/notificaton-preview/ContactPointGroup.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-viewer/AlertRuleMenu.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/state/AlertmanagerContext.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/triage/scene/dataTransform.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/mutation-api/commands/applySpec.ts` | verified |  |
| grafana | `public/app/features/dashboard/components/PanelEditor/utils.ts` | verified |  |
| grafana | `public/app/features/explore/Logs/utils/mocks.ts` | verified |  |
| grafana | `public/app/features/migrate-to-cloud/onprem/useNotifyOnSuccess.tsx` | verified |  |
| grafana | `public/app/features/transformers/editors/CalculateFieldTransformerEditor/ReduceRowOptionsEditor.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/ConfigEditor/DefaultSubscription.tsx` | verified |  |
| grafana | `public/app/plugins/panel/geomap/layers/basemaps/osm.ts` | verified |  |
| grafana | `public/app/plugins/panel/piechart/migrations.ts` | verified |  |
| grafana | `public/app/plugins/panel/timeseries/ThresholdsStyleEditor.tsx` | verified |  |
