# Target OSS no-LLM dogfooding audit — continuation 414 (batch 415)

Run: 2026-07-23T01:18:36.895385+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/types2/const.go` | verified |  |
| go | `src/cmd/vet/main.go` | verified |  |
| go | `src/crypto/internal/fips140/tls12/tls12.go` | verified |  |
| go | `src/crypto/internal/fips140deps/fipsdeps.go` | verified |  |
| go | `src/crypto/x509/root.go` | verified |  |
| go | `src/go/types/instantiate.go` | verified |  |
| go | `src/os/getwd.go` | verified |  |
| go | `src/os/removeall_noat.go` | verified |  |
| go | `src/reflect/export_test.go` | verified |  |
| go | `src/runtime/metrics_test.go` | verified |  |
| go | `test/abi/spills3.go` | verified |  |
| go | `test/fixedbugs/bug150.go` | verified |  |
| go | `test/fixedbugs/bug319.go` | verified |  |
| go | `test/fixedbugs/issue11656.dir/asm_generic.go` | verified |  |
| go | `test/fixedbugs/issue15838.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue51291.go` | verified |  |
| go | `test/typeparam/devirtualize2.go` | verified |  |
| grafana | `apps/example/plugin/src/generated/example/v0alpha1/example_object_gen.ts` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/plugins/v0alpha1/baseAPI.ts` | verified |  |
| grafana | `packages/grafana-flamegraph/src/FlameGraphPane.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/IconButton/IconButton.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Tooltip/types.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/VizLegend/VizLegend.tsx` | verified |  |
| grafana | `pkg/api/webassets/webassets_test.go` | verified |  |
| grafana | `pkg/cmd/grafana-server/commands/diagnostics_test.go` | verified |  |
| grafana | `pkg/expr/converter_test.go` | verified |  |
| grafana | `pkg/expr/graph_test.go` | verified |  |
| grafana | `pkg/infra/kvstore/kvstore_test.go` | verified |  |
| grafana | `pkg/registry/apis/iam/common/pagination.go` | verified |  |
| grafana | `pkg/registry/apis/secret/testutils/generators.go` | verified |  |
| grafana | `pkg/services/accesscontrol/acimpl/accesscontrol_test.go` | verified |  |
| grafana | `pkg/services/authn/authnimpl/sync/rbac_sync.go` | verified |  |
| grafana | `pkg/services/authn/clients/grafana_test.go` | verified |  |
| grafana | `pkg/services/libraryelements/cache.go` | verified |  |
| grafana | `pkg/services/ngalert/image/service_test.go` | verified |  |
| grafana | `pkg/storage/legacysql/dualwrite/dualwriter.go` | verified |  |
| grafana | `pkg/storage/unified/resource/continue_fuzz_test.go` | verified |  |
| grafana | `public/app/core/components/OptionsUI/NumberInput.tsx` | verified |  |
| grafana | `public/app/core/components/QueryOperationRow/QueryOperationRow.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/receivers/grafanaAppReceivers/useReceiversMetadata.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/triage/rows/OpenDrawerButton.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/conditional-rendering/hooks/ConditionalRenderingOverlay.tsx` | verified |  |
| grafana | `public/app/features/dashboard/api/DashboardAPIVersionResolver.ts` | verified |  |
| grafana | `public/app/features/live/LiveConnectionWarning.tsx` | verified |  |
| grafana | `public/app/features/logs/components/panel/LogListControls.tsx` | verified |  |
| grafana | `public/app/features/plugins/admin/state/selectors.ts` | verified |  |
| grafana | `public/app/features/transformers/fieldToConfigMapping/FieldToConfigMappingEditor.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/mocks/variables.ts` | verified |  |
| grafana | `public/app/plugins/datasource/grafana-postgresql-datasource/sqlUtil.ts` | verified |  |
| grafana | `public/app/plugins/datasource/graphite/jest-setup.js` | verified |  |
