# Target OSS no-LLM dogfooding audit — continuation 366 (batch 367)

Run: 2026-07-22T22:03:58.239978+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/dwarfgen/dwarf.go` | verified |  |
| go | `src/cmd/compile/internal/syntax/branches.go` | verified |  |
| go | `src/cmd/compile/internal/types/kind_string.go` | verified |  |
| go | `src/cmd/internal/script/scripttest/scripttest.go` | verified |  |
| go | `src/go/types/basic.go` | verified |  |
| go | `src/internal/pkgbits/sync.go` | verified |  |
| go | `src/internal/poll/hook_windows.go` | verified |  |
| go | `src/internal/syscall/windows/nonblocking_windows.go` | verified |  |
| go | `src/runtime/mgclimit.go` | verified |  |
| go | `src/simd/archsimd/_gen/simdgen/main.go` | verified |  |
| go | `src/text/template/parse/parse_test.go` | verified |  |
| go | `test/codegen/issue42610.go` | verified |  |
| go | `test/codegen/select.go` | verified |  |
| go | `test/fixedbugs/issue31412b.go` | verified |  |
| go | `test/fixedbugs/issue34503.go` | verified |  |
| go | `test/fixedbugs/issue37513.go` | verified |  |
| go | `test/fixedbugs/issue5957.dir/b.go` | verified |  |
| go | `test/typeparam/issue48185b.dir/main.go` | verified |  |
| go | `test/typeparam/issue49536.dir/a.go` | verified |  |
| go | `test/typeparam/smallest.go` | verified |  |
| go | `test/unsafe_string.go` | verified |  |
| grafana | `e2e-playwright/test-plugins/grafana-extensionstest-app/plugins/grafana-extensionexample1-app/components/App/App.tsx` | verified |  |
| grafana | `packages/grafana-o11y-ds-frontend/src/TraceToLogs/TagMappingInput.tsx` | verified |  |
| grafana | `packages/grafana-schema/src/schema/dashboard/v2alpha1/types.metadata.gen.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/TableRT/FilterList.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Tabs/Counter.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/uPlot/utils.ts` | verified |  |
| grafana | `pkg/apimachinery/validation/validation.go` | verified |  |
| grafana | `pkg/apis/service/v0alpha1/zz_generated.deepcopy.go` | verified |  |
| grafana | `pkg/registry/apis/iam/legacy/scope_resolver_test.go` | verified |  |
| grafana | `pkg/registry/apis/iam/team/rest_members_test.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/controller/token_metrics_test.go` | verified |  |
| grafana | `pkg/registry/backgroundsvcs/adapter/doc.go` | verified |  |
| grafana | `pkg/services/cloudmigration/gmsclient/dtos.go` | verified |  |
| grafana | `pkg/services/ngalert/api/api_ruler_history_test.go` | verified |  |
| grafana | `pkg/setting/setting_nats_test.go` | verified |  |
| grafana | `pkg/util/testutil/user.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/notificaton-preview/JourneyPolicyCard.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/mocks/templatesApi.ts` | verified |  |
| grafana | `public/app/features/browse-dashboards/api/mostUsed.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/variables/components/QueryVariableForm.tsx` | verified |  |
| grafana | `public/app/features/dashboard/components/ShareModal/ViewJsonModal.tsx` | verified |  |
| grafana | `public/app/features/logs/components/LogLabelStats.tsx` | verified |  |
| grafana | `public/app/features/org/OrgDetailsPage.tsx` | verified |  |
| grafana | `public/app/features/panel/components/VizTypePicker/PanelTypeCard.tsx` | verified |  |
| grafana | `public/app/features/provisioning/components/utils/path.ts` | verified |  |
| grafana | `public/app/features/scopes/dashboards/ScopesNavigationTreeLink.tsx` | verified |  |
| grafana | `public/app/features/scopes/selector/useScopeNode.ts` | verified |  |
| grafana | `public/app/features/search/state/SearchStateManager.ts` | verified |  |
| grafana | `public/app/plugins/datasource/influxdb/components/editor/config/constants.ts` | verified |  |
