# Target OSS no-LLM dogfooding audit — continuation 487 (batch 488)

Run: 2026-07-23T05:52:05.959468+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/amd64/versions_simd_test.go` | verified |  |
| go | `src/cmd/compile/internal/escape/graph.go` | verified |  |
| go | `src/cmd/compile/internal/ir/dump.go` | verified |  |
| go | `src/cmd/compile/internal/ir/sizeof_test.go` | verified |  |
| go | `src/cmd/compile/internal/pkginit/initAsanGlobals.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/_gen/simdgenericOps.go` | verified |  |
| go | `src/cmd/compile/internal/types2/named_test.go` | verified |  |
| go | `src/encoding/json/example_text_marshaling_test.go` | verified |  |
| go | `src/go/constant/kind_string.go` | verified |  |
| go | `src/internal/nettest/conn.go` | verified |  |
| go | `src/internal/runtime/maps/runtime_hash64.go` | verified |  |
| go | `src/math/cmplx/polar.go` | verified |  |
| go | `src/net/parse.go` | verified |  |
| go | `src/reflect/makefunc.go` | verified |  |
| go | `src/runtime/defs_openbsd_amd64.go` | verified |  |
| go | `src/runtime/lock_sema.go` | verified |  |
| go | `src/runtime/race/output_test.go` | verified |  |
| go | `test/bom.go` | verified |  |
| go | `test/codegen/issue54467.go` | verified |  |
| go | `test/fixedbugs/issue24939.go` | verified |  |
| go | `test/fixedbugs/issue45851.go` | verified |  |
| go | `test/ken/ptrvar.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v38.go` | verified |  |
| grafana | `apps/provisioning/pkg/apis/admission/pending_delete_test.go` | verified |  |
| grafana | `packages/grafana-alerting/src/grafana/api/notifications/v0alpha1/mocks/handlers/RoutingTreeHandlers/listRoutingTreeHandler.ts` | verified |  |
| grafana | `packages/grafana-data/src/types/valueMapping.ts` | verified |  |
| grafana | `packages/grafana-sql/src/components/query-editor-raw/QueryEditorRaw.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Combobox/Combobox.tsx` | verified |  |
| grafana | `pkg/apimachinery/apis/common/v0alpha1/secure_values.go` | verified |  |
| grafana | `pkg/registry/apis/iam/team_hooks_test.go` | verified |  |
| grafana | `pkg/services/authz/zanzana/schema/schema.go` | verified |  |
| grafana | `pkg/services/dashboards/service/search/search.go` | verified |  |
| grafana | `pkg/services/ngalert/schedule/rule_sequence_store.go` | verified |  |
| grafana | `pkg/setting/setting_provisioning_test.go` | verified |  |
| grafana | `pkg/storage/unified/search/builders/dashboard.go` | verified |  |
| grafana | `pkg/storage/unified/sql/db/dbimpl/db_engine.go` | verified |  |
| grafana | `public/app/core/utils/navBarItem-translations.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/useAlertRuleSuggestions.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/mocks/server/handlers/k8sReceiverTest.ts` | verified |  |
| grafana | `public/app/features/canvas/registry.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/Sidebar/CollapsableSection.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/SaveLibraryVizPanelModal.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/layout-tabs/TabItemRenderer.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/layouts-shared/findAllGridTypes.ts` | verified |  |
| grafana | `public/app/features/expressions/components/SqlExpressions/functionSignatures.ts` | verified |  |
| grafana | `public/app/features/provisioning/Shared/MessageList.tsx` | verified |  |
| grafana | `public/app/features/search/page/reporting.ts` | verified |  |
| grafana | `public/app/plugins/datasource/influxdb/components/editor/config-v2/helpers.ts` | verified |  |
| grafana | `public/app/plugins/datasource/loki/components/types.ts` | verified |  |
| grafana | `public/app/plugins/panel/heatmap/module.tsx` | verified |  |
