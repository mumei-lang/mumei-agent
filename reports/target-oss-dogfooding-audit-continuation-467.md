# Target OSS no-LLM dogfooding audit — continuation 467 (batch 468)

Run: 2026-07-23T04:37:22.707456+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/rangefunc/rewrite.go` | verified |  |
| go | `src/cmd/compile/internal/walk/builtin.go` | verified |  |
| go | `src/go/ast/ast.go` | verified |  |
| go | `src/go/types/example_test.go` | verified |  |
| go | `src/internal/cpu/cpu_windows.go` | verified |  |
| go | `src/internal/goarch/goarch_arm64.go` | verified |  |
| go | `src/math/big/internal/asmgen/arm.go` | verified |  |
| go | `src/net/mail/message_test.go` | verified |  |
| go | `src/os/env_test.go` | verified |  |
| go | `src/runtime/export_vdso_linux_test.go` | verified |  |
| go | `src/runtime/mklockrank.go` | verified |  |
| go | `src/simd/internal/bridge/decls_amd64.go` | verified |  |
| go | `src/syscall/exec_windows_test.go` | verified |  |
| go | `src/testing/panic_test.go` | verified |  |
| go | `test/codegen/switch.go` | verified |  |
| go | `test/fixedbugs/bug113.go` | verified |  |
| go | `test/fixedbugs/bug116.go` | verified |  |
| go | `test/fixedbugs/bug506.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue24187.go` | verified |  |
| go | `test/fixedbugs/issue27518b.go` | verified |  |
| go | `test/fixedbugs/issue59709.go` | verified |  |
| go | `test/typeparam/issue47710.go` | verified |  |
| go | `test/typeparam/issue50109b.go` | verified |  |
| grafana | `apps/provisioning/pkg/apis/provisioning/v0alpha1/types.go` | verified |  |
| grafana | `apps/shorturl/pkg/app/validate_test.go` | verified |  |
| grafana | `packages/grafana-runtime/src/services/pluginMeta/mappers/v0alpha1PanelMapper.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/EmptySearchResult/EmptySearchResult.tsx` | verified |  |
| grafana | `pkg/plugins/log/infra_wrapper.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/sync/full_test.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/resources/errors_test.go` | verified |  |
| grafana | `pkg/services/gcom/gcom.go` | verified |  |
| grafana | `pkg/services/live/pipeline/tree/tree_test.go` | verified |  |
| grafana | `pkg/services/ngalert/provisioning/contactpoints.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/serverlock_migrations.go` | verified |  |
| grafana | `pkg/tests/api/alerting/high_availability_test.go` | verified |  |
| grafana | `pkg/tests/apis/alerting/rules/rulesequence/rulesequence_test.go` | verified |  |
| grafana | `public/app/core/services/echo/backends/analytics/BrowseConsoleBackend.ts` | verified |  |
| grafana | `public/app/features/admin/OrgRolePicker.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/hooks/useCombinedRuleNamespaces.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/VersionsEditView.tsx` | verified |  |
| grafana | `public/app/features/dashboard/components/PanelEditor/OptionsPaneItemOverrides.tsx` | verified |  |
| grafana | `public/app/features/explore/RawPrometheus/RawPrometheusContainerPure.tsx` | verified |  |
| grafana | `public/app/features/plugins/admin/components/Badges/PluginEnterpriseBadge.tsx` | verified |  |
| grafana | `public/app/features/plugins/admin/components/InstallControls/InstallControlsWarning.tsx` | verified |  |
| grafana | `public/app/features/provisioning/GettingStarted/GettingStartedPage.tsx` | verified |  |
| grafana | `public/app/features/provisioning/Job/FinishedJobStatus.tsx` | verified |  |
| grafana | `public/app/features/provisioning/hooks/useSelectionRepoValidation.ts` | verified |  |
| grafana | `public/app/features/transformers/editors/SeriesToRowsTransformerEditor.tsx` | verified |  |
| grafana | `public/app/features/variables/adhoc/reducer.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/language/cloudwatch-logs-sql/completion/CompletionItemProvider.ts` | verified |  |
