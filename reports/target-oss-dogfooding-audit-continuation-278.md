# Target OSS no-LLM dogfooding audit — continuation 278 (batch 279)

Run: 2026-07-22T16:43:45.623486+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/riscv64/ssa.go` | verified |  |
| go | `src/cmd/internal/dwarf/dwarf.go` | verified |  |
| go | `src/go/types/slice.go` | verified |  |
| go | `src/internal/goarch/zgoarch_wasm.go` | verified |  |
| go | `src/internal/syscall/unix/getrandom_dragonfly.go` | verified |  |
| go | `src/runtime/os_illumos.go` | verified |  |
| go | `src/runtime/signal_darwin_amd64.go` | verified |  |
| go | `src/syscall/types_aix.go` | verified |  |
| go | `test/fixedbugs/bug099.go` | verified |  |
| go | `test/fixedbugs/bug344.go` | verified |  |
| go | `test/fixedbugs/issue29389.go` | verified |  |
| go | `test/typeparam/issue54537.go` | verified |  |
| grafana | `apps/alerting/rules/pkg/app/rulesequence/membership_index.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/getsearchusers_request_params_object_gen.go` | verified |  |
| grafana | `packages/grafana-data/src/valueFormats/baseFormatters.ts` | verified |  |
| grafana | `packages/grafana-sql/src/components/visual-query-builder/SelectCustomFunctionParameters.tsx` | verified |  |
| grafana | `pkg/components/apikeygen/apikeygen_test.go` | verified |  |
| grafana | `pkg/infra/usagestats/service/api_test.go` | verified |  |
| grafana | `pkg/registry/apis/iam/resource_permission_hooks_test.go` | verified |  |
| grafana | `pkg/services/authn/authnserver/service_test.go` | verified |  |
| grafana | `pkg/services/live/pipeline/models.go` | verified |  |
| grafana | `pkg/services/live/pipeline/registry.go` | verified |  |
| grafana | `pkg/services/ngalert/models/alert_rule_test.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/sandbox/sandbox.go` | verified |  |
| grafana | `pkg/services/provisioning/alerting/contact_point_provisioner.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/dashboard_mig.go` | verified |  |
| grafana | `pkg/services/store/kind/dashboard/fuzz_test.go` | verified |  |
| grafana | `pkg/services/store/system_users_test.go` | verified |  |
| grafana | `public/app/core/components/OptionsUI/slider.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/EvaluationGroupQuickPick.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/extensions/CreateAlertFromPanelExposedComponent.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/edit-pane/useUserActivity.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/utils/test-utils.ts` | verified |  |
| grafana | `public/app/features/dimensions/text.ts` | verified |  |
| grafana | `public/app/features/explore/ExploreActions.tsx` | verified |  |
| grafana | `public/app/features/playlist/PlaylistPage.tsx` | verified |  |
| grafana | `public/app/features/plugins/components/pluginNavFallbacks.ts` | verified |  |
| grafana | `public/app/plugins/datasource/influxdb/fsql/sqlCompletionProvider.ts` | verified |  |
| grafana | `public/app/plugins/panel/geomap/view.ts` | verified |  |
| prysm | `beacon-chain/core/execution/upgrade.go` | verified |  |
| prysm | `beacon-chain/rpc/eth/beacon/handlers_gloas_test.go` | verified |  |
| prysm | `beacon-chain/rpc/prysm/validator/server.go` | verified |  |
| prysm | `cmd/beacon-chain/flags/base.go` | verified |  |
| prysm | `config/log.go` | verified |  |
| prysm | `container/trie/sparse_merkle_trie_fuzz_test.go` | verified |  |
| prysm | `encoding/ssz/query/bitvector.go` | verified |  |
| prysm | `testing/spectest/mainnet/capella__operations__attestation_test.go` | verified |  |
| prysm | `testing/spectest/shared/common/merkle_proof/single_merkle_proof.go` | verified |  |
| prysm | `tools/analyzers/comparesame/analyzer.go` | verified |  |
| prysm | `validator/rpc/handlers_accounts_test.go` | verified |  |
