# Target OSS no-LLM dogfooding audit — continuation 35 (batch 36)

Run: 2026-07-21T07:46:43.770483+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All 50 sampled files passed no-LLM verification after the tool-side fixes.

## Tool-side fixes (batch 36)

- **go/types container receiver nil-deref false positives**
  - `_go_caller_contract_receiver_types` now recognizes `go/types` `Info` and `ArgumentError` as container types whose methods are called on non-nil receivers.
  - Rep: `go/src/go/types/api.go` (`*Info` and `*ArgumentError` methods).

- **String-typed Go map-key index access**
  - `_index_safety_issue` now skips bounds checks when the index operand has a declared `string` type, because `m[s]` is a map key access, not an array index.
  - Rep: `go/src/internal/goroot/gccgo.go` (`stdpkg[path]`).

- **Go compiler-test files (`// asmcheck`)**
  - `_is_go_compiler_test` now includes `// asmcheck` directives and is honored by `_extract_go_with_tree_sitter`, `_extract_go_regex`, `_infer_go_contracts`, and `_source_has_function_declarations`.
  - Rep: `go/test/codegen/bitfield.go`.

- **Natural-language precondition filtering**
  - `_contract_lines` now detects human-language clauses such as `the Types, Uses and Defs maps are populated` and lowers them to `true` instead of emitting invalid Mumei.
  - `_source_has_function_declarations` ignores Go files whose only function-like declarations are `Test/Benchmark/Example/Fuzz` entry points or compiler-test directives.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| grafana | `public/app/plugins/datasource/cloudwatch/resources/ResourceAPI.test.ts` | verified |  |
| grafana | `public/app/features/admin/AdminListOrgsPage.tsx` | verified |  |
| go | `src/simd/archsimd/internal/simd_test/shift_helpers_128_test.go` | verified |  |
| go | `src/go/types/api.go` | verified |  |
| grafana | `public/app/features/query/state/DashboardQueryRunner/DashboardQueryRunner.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/notifications/NotificationsScene.tsx` | verified |  |
| go | `src/runtime/signal_freebsd_riscv64.go` | verified |  |
| prysm | `config/params/config.go` | verified |  |
| go | `test/codegen/bitfield.go` | verified |  |
| grafana | `public/app/core/components/Page/Page.tsx` | verified |  |
| go | `src/internal/goroot/gccgo.go` | verified |  |
| grafana | `public/app/features/dashboard/components/TransformationsEditor/SqlExpressionCard.tsx` | verified |  |
| grafana | `pkg/storage/unified/resource/kv/sqlkv_test.go` | verified |  |
| go | `test/typeparam/dottype.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rules/central-state-history/CentralHistoryRuntimeDataSource.ts` | verified |  |
| go | `test/fixedbugs/issue62498.dir/main.go` | verified |  |
| prysm | `beacon-chain/core/gloas/pending_payment.go` | verified |  |
| go | `src/runtime/testdata/testsyscall/testsyscallc/testsyscallc.go` | verified |  |
| prysm | `beacon-chain/core/deneb/upgrade.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/import-to-gma/Wizard/NextButton.tsx` | verified |  |
| go | `src/cmd/compile/internal/midway/deepcopy.go` | verified |  |
| grafana | `pkg/registry/apps/annotation/postgres_schema.go` | verified |  |
| grafana | `public/app/features/provisioning/Shared/GitSyncLimitationsAlert.test.tsx` | verified |  |
| grafana | `pkg/tests/api/alerting/api_ruler_test.go` | verified |  |
| go | `src/internal/runtime/maps/map.go` | verified |  |
| go | `test/fixedbugs/issue16037_run.go` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/preferences/user/index.ts` | verified |  |
| grafana | `public/app/plugins/datasource/loki/querybuilder/components/LabelParamEditor.tsx` | verified |  |
| grafana | `packages/grafana-data/src/transformations/matchers/valueMatchers/regexMatchers.ts` | verified |  |
| go | `src/sort/slice.go` | verified |  |
| go | `src/runtime/net_plan9.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v2-core/interfaces/IUniswapV2Pair.sol` | verified |  |
| go | `test/fixedbugs/issue11656.dir/asm.go` | verified |  |
| go | `src/cmd/compile/internal/test/mulconst_test.go` | verified |  |
| go | `test/unsafebuiltins.go` | verified |  |
| grafana | `pkg/tests/apis/iam/team/team_members_search_integration_test.go` | verified |  |
| grafana | `pkg/services/provisioning/plugins/config_reader.go` | verified |  |
| go | `src/net/splice_stub.go` | verified |  |
| grafana | `public/app/plugins/panel/geomap/utils/getLayersExtent.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/hooks/useControlledFieldArray.ts` | verified |  |
| grafana | `public/app/core/history/localStorageConverter.ts` | verified |  |
| grafana | `public/app/plugins/datasource/loki/components/monaco-query-field/monaco-completion-provider/completions.ts` | verified |  |
| grafana | `public/app/core/navigation/GrafanaRouteError.tsx` | verified |  |
| go | `src/cmd/compile/internal/ir/html_test.go` | verified |  |
| go | `src/syscall/ztypes_linux_amd64.go` | verified |  |
| grafana | `packages/grafana-schema/src/raw/composable/logs/panelcfg/x/types.gen.ts` | verified |  |
| prysm | `beacon-chain/sync/validate_proposer_slashing.go` | verified |  |
| go | `src/weak/pointer_test.go` | verified |  |
| go | `src/runtime/os_linux_riscv64.go` | verified |  |
| grafana | `pkg/infra/filestorage/fs_integration_test.go` | verified |  |
