# Target OSS no-LLM dogfooding audit — continuation 485 (batch 486)

Run: 2026-07-23T05:48:24.583362+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/bytes/bytes.go` | verified |  |
| go | `src/cmd/compile/internal/arm/ssa.go` | verified |  |
| go | `src/cmd/compile/internal/s390x/galign.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/shortcircuit.go` | verified |  |
| go | `src/cmd/compile/internal/types/universe.go` | verified |  |
| go | `src/cmd/link/internal/ld/link.go` | verified |  |
| go | `src/internal/syscall/unix/at_libc2.go` | verified |  |
| go | `src/math/cbrt.go` | verified |  |
| go | `src/net/http/internal/http2/databuffer.go` | verified |  |
| go | `src/path/path.go` | verified |  |
| go | `src/runtime/test_stubs.go` | verified |  |
| go | `src/runtime/trace/encoding.go` | verified |  |
| go | `src/simd/archsimd/ops_amd64.go` | verified |  |
| go | `src/syscall/syscall_plan9.go` | verified |  |
| go | `test/fixedbugs/bug264.go` | verified |  |
| go | `test/fixedbugs/bug276.go` | verified |  |
| go | `test/fixedbugs/bug439.go` | verified |  |
| go | `test/fixedbugs/issue22941.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue3552.dir/two.go` | verified |  |
| go | `test/fixedbugs/issue42876.go` | verified |  |
| go | `test/typeparam/listimp.dir/main.go` | verified |  |
| grafana | `apps/provisioning/pkg/connection/factory.go` | verified |  |
| grafana | `packages/grafana-api-clients/src/generator/variants.ts` | verified |  |
| grafana | `packages/grafana-data/src/transformations/fieldReducer.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/CodeMirror/CodeEditorLazy.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Layout/types.ts` | verified |  |
| grafana | `pkg/api/short_url_test.go` | verified |  |
| grafana | `pkg/apis/iam/v0alpha1/types_sso.go` | verified |  |
| grafana | `pkg/expr/sql/parser_allow_test.go` | verified |  |
| grafana | `pkg/registry/apis/iam/team/legacy_search_test.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/resources/errors.go` | verified |  |
| grafana | `pkg/registry/apis/query/register.go` | verified |  |
| grafana | `pkg/services/folder/tree_test.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/ualert/rule_group_index_migration.go` | verified |  |
| grafana | `pkg/storage/unified/resource/notifier.go` | verified |  |
| grafana | `pkg/storage/unified/resource/usagestats/ingester.go` | verified |  |
| grafana | `pkg/storage/unified/sql/notifier_sql.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/connection/connection_test.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/log_groups_test.go` | verified |  |
| grafana | `public/app/core/components/FormPrompt/FormPrompt.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/HoverCard.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/hooks/useSelectedCard.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/layout-default/row-actions/RowOptionsForm.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/utils/PanelModelCompatibilityWrapper.ts` | verified |  |
| grafana | `public/app/features/explore/NodeGraph/NodeGraphContainer.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/utils/filter-spans.tsx` | verified |  |
| grafana | `public/app/features/plugins/admin/types.ts` | verified |  |
| grafana | `public/app/features/users/TokenRevokedModal.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/language/logs/completion/types.ts` | verified |  |
| grafana | `public/app/plugins/datasource/jaeger/configuration/ConfigEditor.tsx` | verified |  |
