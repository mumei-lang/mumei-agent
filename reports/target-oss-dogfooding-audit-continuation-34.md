# Target OSS no-LLM dogfooding audit — continuation 34 (batch 35)

Run: 2026-07-21T07:26:02.804580Z

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All 50 sampled files passed no-LLM verification after the tool-side fixes.

## Tool-side fixes (batch 35)

- **Go math function float inference**
  - `_go_expression_is_float` now recognizes calls to `math` package functions (e.g. `Exp`, `Log`, `Pow`) as returning `float64`, so local variables assigned from them propagate float-ness.
  - This suppresses false-positive divide-by-zero on `1/ex` where `ex := Exp(x)`.
  - Rep: `go/src/math/sinh.go` `cosh`.

- **Go generic instantiation vs index access**
  - Added `_go_type_names` to collect declared type names.
  - `_index_safety_issue` now skips `container[Type]` when `index` is a type name, because Go uses `[Type]` for generic function/type instantiation, not indexing.
  - Rep: `grafana/pkg/tests/api/alerting/testing.go` `DeleteSilence` (`sendRequestJSON[dynamic](...)`).

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/math/sinh.go` | verified |  |
| go | `src/internal/types/testdata/fixedbugs/issue58612.go` | verified |  |
| grafana | `pkg/tests/api/alerting/testing.go` | verified |  |
| prysm | `beacon-chain/sync/subscriber_data_column_sidecar.go` | verified |  |
| grafana | `pkg/services/login/authinfoimpl/userprotection.go` | verified |  |
| prysm | `beacon-chain/state/state-native/setters_gloas_test.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/testreceivers_test.go` | verified |  |
| go | `src/go/types/named_test.go` | verified |  |
| go | `lib/wasm/wasm_exec_node.js` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/language/cloudwatch-logs-sql/language.ts` | verified |  |
| grafana | `apps/provisioning/pkg/generated/applyconfiguration/provisioning/v0alpha1/syncoptions.go` | verified |  |
| grafana | `packages/grafana-ui/src/components/EmptyState/EmptyState.story.tsx` | verified |  |
| go | `src/internal/types/testdata/fixedbugs/issue43527.go` | verified |  |
| go | `src/simd/sum_test.go` | verified |  |
| go | `test/codegen/typeswitch.go` | verified |  |
| go | `src/crypto/internal/fips140/subtle/xor_asm.go` | verified |  |
| grafana | `pkg/apimachinery/apis/common/v0alpha1/secure_values_test.go` | verified | No Mumei atoms |
| grafana | `pkg/services/sqlstore/migrations/accesscontrol/test/action_set_migration_test.go` | verified |  |
| grafana | `packages/grafana-data/src/themes/createTransitions.ts` | verified |  |
| go | `src/internal/xcoff/file.go` | verified |  |
| go | `src/cmd/compile/internal/loopvar/testdata/for_esc_address.go` | verified |  |
| grafana | `public/app/core/components/RolePicker/ValueContainer.tsx` | verified |  |
| go | `src/debug/macho/fat.go` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/layouts-shared/findAllGridTypes.test.ts` | verified |  |
| grafana | `public/app/features/variables/interval/actions.ts` | verified |  |
| grafana | `packages/grafana-test-utils/src/fixtures/index.ts` | verified |  |
| grafana | `apps/provisioning/pkg/generated/applyconfiguration/provisioning/v0alpha1/bitbucketconnectionconfig.go` | verified |  |
| go | `test/fixedbugs/issue42753.go` | verified |  |
| go | `test/typeparam/issue52124.go` | verified |  |
| prysm | `cmd/beacon-chain/main.go` | verified |  |
| go | `test/linknameasm.dir/x.go` | verified |  |
| prysm | `async/scatter_test.go` | verified | No Mumei atoms |
| prysm | `beacon-chain/sync/checkpoint/api.go` | verified |  |
| grafana | `apps/logsdrilldown/plugin/src/generated/logsdrilldowndefaultcolumns/v1alpha1/types.metadata.gen.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-viewer/tabs/Query/LokiQueryPreview.tsx` | verified |  |
| grafana | `public/app/core/components/AppChrome/TopBar/TopSearchBarCommandPaletteTrigger.tsx` | verified | No Mumei atoms |
| go | `src/math/jn.go` | verified |  |
| go | `test/fixedbugs/issue10219.dir/a.go` | verified |  |
| go | `test/inline_variadic.go` | verified |  |
| grafana | `public/app/plugins/panel/histogram/module.tsx` | verified |  |
| go | `src/runtime/testdata/testgoroutineleakprofile/goker/kubernetes38669.go` | verified |  |
| grafana | `packages/grafana-runtime/src/analyticsFramework/types.ts` | verified |  |
| grafana | `pkg/services/ngalert/api/lotex_prom.go` | verified |  |
| go | `src/runtime/defs_plan9_amd64.go` | verified |  |
| grafana | `pkg/services/live/pushws/ws.go` | verified |  |
| influxdb | `core/table_batch/src/builder/column_writer/dictionary.rs` | verified |  |
| prysm | `beacon-chain/rpc/eth/helpers/error_handling.go` | verified |  |
| grafana | `packages/grafana-ui/src/components/uPlot/plugins/TooltipPlugin2.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/mutation-api/commands/updateDashboardSettings.test.ts` | verified |  |
| go | `src/runtime/vdso_linux.go` | verified |  |
