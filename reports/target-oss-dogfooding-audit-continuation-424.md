# Target OSS no-LLM dogfooding audit — continuation 424 (batch 425)

Run: 2026-07-23T01:41:24.871325+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/reflectdata/reflect.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/rewritePPC64.go` | verified |  |
| go | `src/cmd/compile/internal/syntax/syntax.go` | verified |  |
| go | `src/cmd/internal/obj/s390x/anamesz.go` | verified |  |
| go | `src/cmd/internal/objabi/flag_test.go` | verified |  |
| go | `src/cmd/link/internal/riscv64/obj.go` | verified |  |
| go | `src/net/cgo_darwin.go` | verified |  |
| go | `src/net/http/requestwrite_test.go` | verified |  |
| go | `src/net/netgo_netcgo.go` | verified |  |
| go | `src/runtime/cpuflags_amd64_test.go` | verified |  |
| go | `src/runtime/mgc.go` | verified |  |
| go | `src/sync/atomic/type.go` | verified |  |
| go | `src/syscall/syscall_bsd.go` | verified |  |
| go | `test/codegen/retpoline.go` | verified |  |
| go | `test/fixedbugs/issue13171.go` | verified |  |
| go | `test/fixedbugs/issue30862.dir/b/b.go` | verified |  |
| go | `test/fixedbugs/issue6772.go` | verified |  |
| go | `test/fixedbugs/issue7995b.go` | verified |  |
| go | `test/typeparam/nested.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v1beta1/routingtree_client_gen.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/conversion/conversion_test.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v31_test.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/informers/externalversions/internalinterfaces/factory_interfaces.go` | verified |  |
| grafana | `packages/grafana-alerting/src/grafana/rules/components/labels/AlertLabel.tsx` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/dashboard/v1beta1/endpoints.gen.ts` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/historian.alerting/v0alpha1/index.ts` | verified |  |
| grafana | `packages/grafana-data/src/types/annotations.ts` | verified |  |
| grafana | `packages/grafana-ui/src/options/builder/stacking.tsx` | verified |  |
| grafana | `pkg/api/live_test.go` | verified |  |
| grafana | `pkg/expr/mathexp/parse/node.go` | verified |  |
| grafana | `pkg/infra/features/cache_test.go` | verified |  |
| grafana | `pkg/infra/log/term/terminal_logger.go` | verified |  |
| grafana | `pkg/kinds/dashboard/dashboard_gen.go` | verified |  |
| grafana | `pkg/registry/apis/iam/teambinding/legacy_search_test.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/sync/compare_fn_mock.go` | verified |  |
| grafana | `pkg/services/apiserver/auth/authorizer/storewrapper/wrapper.go` | verified |  |
| grafana | `pkg/services/apiserver/auth/authorizer/storewrapper/wrapper_test.go` | verified |  |
| grafana | `pkg/services/licensing/accesscontrol.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/ualert/test/receiver_scope_mig_test.go` | verified |  |
| grafana | `pkg/services/ssosettings/validation/oauth_validators_test.go` | verified |  |
| grafana | `pkg/services/supportbundles/supportbundlesimpl/api.go` | verified |  |
| grafana | `pkg/storage/secret/encryption/query.go` | verified |  |
| grafana | `pkg/tsdb/grafana-testdata-datasource/stream_handler.go` | verified |  |
| grafana | `public/app/features/actions/analytics.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/settings/ExternalAlertmanagers.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/insights/mimir/rules/Firing.tsx` | verified |  |
| grafana | `public/app/features/commandPalette/actions/staticActions.ts` | verified |  |
| grafana | `public/app/features/dashboard/components/GenAI/GenAIPanelTitleButton.tsx` | verified |  |
| grafana | `public/app/features/migrate-to-cloud/onprem/NameCell.tsx` | verified |  |
| grafana | `public/app/types/plugins.ts` | verified |  |
