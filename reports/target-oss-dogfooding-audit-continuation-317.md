# Target OSS no-LLM dogfooding audit — continuation 317 (batch 318)

Run: 2026-07-22T19:10:06.347690+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/test/callback.go` | verified |  |
| go | `src/encoding/gob/encoder.go` | verified |  |
| go | `src/internal/goarch/zgoarch_sparc64.go` | verified |  |
| go | `src/internal/trace/tracev2/spec.go` | verified |  |
| go | `src/net/http/internal/http2/writesched_benchmarks_test.go` | verified |  |
| go | `src/net/http/proxy_test.go` | verified |  |
| go | `src/os/exec/bench_test.go` | verified |  |
| go | `src/plugin/plugin_stubs.go` | verified |  |
| go | `src/simd/archsimd/_gen/simdgen/gen_simdGenericOps.go` | verified |  |
| go | `src/syscall/exec_pdeathsig_test.go` | verified |  |
| go | `test/fixedbugs/dse_move_auxint.go` | verified |  |
| go | `test/fixedbugs/issue8154.go` | verified |  |
| go | `test/linknameasm.go` | verified |  |
| go | `test/typeparam/issue50417b.go` | verified |  |
| go | `test/typeparam/mdempsky/3.go` | verified |  |
| grafana | `apps/alerting/rules/pkg/apis/alerting/v0alpha1/recordingrule_status_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/informers/externalversions/provisioning/v0alpha1/interface.go` | verified |  |
| grafana | `devenv/jsonnet/gen.go` | verified |  |
| grafana | `hack/externalTools.go` | verified |  |
| grafana | `packages/grafana-runtime/src/services/pluginMeta/types.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Combobox/useMeasureMulti.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Input/AutoSizeInput.tsx` | verified |  |
| grafana | `pkg/apis/datasource/v0alpha1/register.go` | verified |  |
| grafana | `pkg/infra/kvstore/model.go` | verified |  |
| grafana | `pkg/registry/apis/dashboard/snapshot/conversions.go` | verified |  |
| grafana | `pkg/registry/apis/iam/teambinding/validate_test.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/controller/finalizers.go` | verified |  |
| grafana | `pkg/services/contexthandler/contexthandler_test.go` | verified |  |
| grafana | `pkg/services/loginattempt/loginattemptimpl/models.go` | verified |  |
| grafana | `pkg/services/user/user.go` | verified |  |
| grafana | `pkg/storage/unified/search/lock_local_backend.go` | verified |  |
| grafana | `pkg/tsdb/grafana-postgresql-datasource/sqleng/handler_checkhealth.go` | verified |  |
| grafana | `public/app/features/alerting/unified/notifications/NotificationDetailSidebar.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/rule-list/hooks/filterPredicates.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/triage/rows/FolderGroupRow.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/PanelDataPaneNext.tsx` | verified |  |
| grafana | `public/app/features/datasources/components/DataSourceLoadError.tsx` | verified |  |
| grafana | `public/app/features/plugins/admin/components/PluginDetailsDisabledError.tsx` | verified |  |
| grafana | `public/app/features/provisioning/components/Folders/analytics/main.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/components/VariableQueryEditor/MultiFilterItem.tsx` | verified |  |
| prysm | `beacon-chain/core/altair/log.go` | verified |  |
| prysm | `beacon-chain/operations/payloadattestation/pool.go` | verified |  |
| prysm | `beacon-chain/sync/data_column_assignment_test.go` | verified |  |
| prysm | `consensus-types/blocks/partialdatacolumn_mutation_test.go` | verified |  |
| prysm | `consensus-types/primitives/epoch_test.go` | verified |  |
| prysm | `crypto/bls/interface.go` | verified |  |
| prysm | `testing/spectest/minimal/fulu__epoch_processing__rewards_and_penalties_test.go` | verified |  |
| prysm | `testing/spectest/shared/electra/operations/withdrawal_request.go` | verified |  |
| prysm | `tools/analyzers/modernize/rangeint/analyzer.go` | verified |  |
| prysm | `validator/client/propose_gloas.go` | verified |  |
