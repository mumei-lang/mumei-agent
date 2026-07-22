# Target OSS no-LLM dogfooding audit — continuation 272 (batch 273)

Run: 2026-07-22T16:11:42.624696+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/inline/inl.go` | verified |  |
| go | `src/cmd/go/internal/work/exec_test.go` | verified |  |
| go | `src/cmd/internal/goobj/builtinlist.go` | verified |  |
| go | `src/cmd/internal/obj/x86/obj6_test.go` | verified |  |
| go | `src/go/token/example_test.go` | verified |  |
| go | `src/go/types/predicates.go` | verified |  |
| go | `src/image/image_test.go` | verified |  |
| go | `src/internal/runtime/gc/internal/gen/val.go` | verified |  |
| go | `src/mime/example_test.go` | verified |  |
| go | `src/runtime/secret_nosecret.go` | verified |  |
| go | `src/runtime/sys_darwin_arm64.go` | verified |  |
| go | `src/testing/allocs_test.go` | verified |  |
| go | `src/text/template/parse/parse.go` | verified |  |
| go | `test/arenas/smoke.go` | verified |  |
| go | `test/fixedbugs/bug142.go` | verified |  |
| go | `test/fixedbugs/bug157.go` | verified |  |
| go | `test/fixedbugs/issue4215.go` | verified |  |
| go | `test/fixedbugs/issue59367.go` | verified |  |
| grafana | `apps/alerting/rules/pkg/app/recordingrule/mutator.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v2/register.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/rolebinding_spec_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/factory_mock.go` | verified |  |
| grafana | `e2e-playwright/plugin-e2e/plugin-e2e-api-tests/mocks/resources.ts` | verified |  |
| grafana | `packages/grafana-schema/src/raw/composable/logsnew/panelcfg/x/types.gen.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Alert/Alert.tsx` | verified |  |
| grafana | `pkg/infra/usagestats/statscollector/service_test.go` | verified |  |
| grafana | `pkg/plugins/codegen/jenny_plugingotypes.go` | verified |  |
| grafana | `pkg/services/annotations/annotationsimpl/composite_store.go` | verified |  |
| grafana | `pkg/services/authn/clients/utils.go` | verified |  |
| grafana | `pkg/services/ldap/ldap_helpers_test.go` | verified |  |
| grafana | `pkg/services/ngalert/remote/forked_alertmanager_test.go` | verified |  |
| grafana | `pkg/services/ngalert/state/historian/backend.go` | verified |  |
| grafana | `pkg/storage/unified/sql/sqltemplate/mocks/SQLTemplate.go` | verified |  |
| grafana | `public/app/core/services/PreferencesService.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/rule-list/GrafanaGroupLoader.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/edit-pane/SectionFiltersList.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/saving/SaveDashboardDrawer.tsx` | verified |  |
| grafana | `public/app/features/explore/QueryLibrary/types.ts` | verified |  |
| grafana | `public/app/plugins/panel/xychart/SeriesEditor.tsx` | verified |  |
| prysm | `beacon-chain/blockchain/init_sync_process_block.go` | verified |  |
| prysm | `beacon-chain/blockchain/metrics_test.go` | verified |  |
| prysm | `beacon-chain/core/altair/epoch_precompute_test.go` | verified |  |
| prysm | `beacon-chain/rpc/prysm/v1alpha1/validator/proposer_altair_test.go` | verified |  |
| prysm | `beacon-chain/sync/fuzz_exports.go` | verified |  |
| prysm | `beacon-chain/sync/validate_light_client_test.go` | verified |  |
| prysm | `consensus-types/blocks/execution_test.go` | verified |  |
| prysm | `crypto/hash/htr/hashtree.go` | verified |  |
| prysm | `io/logs/stream_test.go` | verified |  |
| prysm | `testing/spectest/minimal/deneb__operations__deposit_test.go` | verified |  |
| prysm | `testing/spectest/shared/electra/operations/sync_committee.go` | verified |  |
