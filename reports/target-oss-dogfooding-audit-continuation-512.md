# Target OSS no-LLM dogfooding audit — continuation 512 (batch 513)

Run: 2026-07-23T07:27:19.740491+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ssa/cache.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/sizeof_test.go` | verified |  |
| go | `src/cmd/go/internal/str/path.go` | verified |  |
| go | `src/cmd/internal/script/engine_test.go` | verified |  |
| go | `src/compress/flate/example_test.go` | verified |  |
| go | `src/compress/flate/level6.go` | verified |  |
| go | `src/crypto/internal/fips140/aes/gcm/gcm.go` | verified |  |
| go | `src/crypto/internal/fips140/sha256/sha256block_ppc64x.go` | verified |  |
| go | `src/internal/nettest/nettest_test.go` | verified |  |
| go | `src/io/multi.go` | verified |  |
| go | `src/math/big/intmarsh.go` | verified |  |
| go | `src/net/cgo_solaris.go` | verified |  |
| go | `src/net/http/httptrace/trace_test.go` | verified |  |
| go | `src/simd/archsimd/internal/simd_test/reduce_helpers_arm64_test.go` | verified |  |
| go | `src/sync/once.go` | verified |  |
| go | `src/time/zoneinfo.go` | verified |  |
| go | `test/chancap.go` | verified |  |
| go | `test/dwarf/dwarf.dir/z15.go` | verified |  |
| go | `test/fixedbugs/bug389.go` | verified |  |
| go | `test/fixedbugs/issue11053.dir/p_test.go` | verified |  |
| go | `test/fixedbugs/issue16985.go` | verified |  |
| go | `test/fixedbugs/issue22794.go` | verified |  |
| go | `test/fixedbugs/issue33555.go` | verified |  |
| go | `test/fixedbugs/issue4085b.go` | verified |  |
| go | `test/fixedbugs/issue49016.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v1/zz_generated.conversion.go` | verified |  |
| grafana | `apps/example/plugin/src/generated/example/v0alpha1/types.metadata.gen.ts` | verified |  |
| grafana | `packages/grafana-data/src/types/options.ts` | verified |  |
| grafana | `packages/grafana-sql/src/components/configuration/MaxOpenConnectionsField.tsx` | verified |  |
| grafana | `packages/grafana-sql/src/loadResources.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Select/getSelectStyles.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/TagsInput/TagItem.tsx` | verified |  |
| grafana | `pkg/expr/hysteresis_test.go` | verified |  |
| grafana | `pkg/expr/mathexp/parse/lex.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/sync/incremental_sync_fn_mock.go` | verified |  |
| grafana | `pkg/registry/apps/apps_test.go` | verified |  |
| grafana | `pkg/services/accesscontrol/metadata_bench_test.go` | verified |  |
| grafana | `pkg/setting/setting_smtp.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/repository/webhook_connection_validation_test.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rules/RuleState.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/hooks/useAsync.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/rule-list/components/ListGroup.tsx` | verified |  |
| grafana | `public/app/features/canvas/elements/droneTop.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/Header/DatasourceHelpPanel.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/variables/editors/QueryVariableEditor/VariableOptionsSpreadsheet/SortSelector.tsx` | verified |  |
| grafana | `public/app/features/scopes/selector/ScopesInput.tsx` | verified |  |
| grafana | `public/app/features/transformers/editors/EnumMappingEditor.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/loki/shardQuerySplitting.ts` | verified |  |
| grafana | `public/test/fixtures/panelModel.fixture.ts` | verified |  |
| grafana | `scripts/cli/generateSassVariableFiles.ts` | verified |  |
