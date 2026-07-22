# Target OSS no-LLM dogfooding audit — continuation 295 (batch 296)

Run: 2026-07-22T17:40:32.327551+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ssa/zeroextension_test.go` | verified |  |
| go | `src/cmd/go/internal/lockedfile/internal/filelock/filelock_windows.go` | verified |  |
| go | `src/cmd/link/internal/loadpe/seh.go` | verified |  |
| go | `src/crypto/cipher/cbc_aes_test.go` | verified |  |
| go | `src/internal/cpu/cpu_ppc64x_other.go` | verified |  |
| go | `src/net/http/httptest/recorder.go` | verified |  |
| go | `src/runtime/metrics/example_test.go` | verified |  |
| go | `src/simd/internal/bridge/decls_arm64.go` | verified |  |
| go | `src/syscall/sockcmsg_dragonfly.go` | verified |  |
| go | `src/syscall/syscall_linux_test.go` | verified |  |
| go | `test/fixedbugs/issue24651b.go` | verified |  |
| go | `test/fixedbugs/issue6703d.go` | verified |  |
| go | `test/fixedbugs/issue78295.go` | verified |  |
| go | `test/typeparam/issue47775.dir/main.go` | verified |  |
| grafana | `apps/provisioning/pkg/apis/admission/combined_validator.go` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/advisor/v0alpha1/baseAPI.ts` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/dashboard/v2/index.ts` | verified |  |
| grafana | `packages/grafana-data/src/transformations/transformers/filter.ts` | verified |  |
| grafana | `packages/grafana-runtime/src/services/dataSource/expressionDs.ts` | verified |  |
| grafana | `pkg/api/login_test.go` | verified |  |
| grafana | `pkg/apimachinery/identity/context_test.go` | verified |  |
| grafana | `pkg/infra/usagestats/validator/fake.go` | verified |  |
| grafana | `pkg/plugins/repo/client_test.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/resources/resources.go` | verified |  |
| grafana | `pkg/registry/apps/advisor/register.go` | verified |  |
| grafana | `pkg/services/authn/clients/api_key_test.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/angularinspector/angularinspector_test.go` | verified |  |
| grafana | `pkg/services/serviceaccounts/utils.go` | verified |  |
| grafana | `pkg/storage/unified/resource/keys_fuzz_test.go` | verified |  |
| grafana | `pkg/tests/api/alerting/api_backtesting_test.go` | verified |  |
| grafana | `pkg/tests/api/annotations/annotations_test.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/services/data_sources_test.go` | verified |  |
| grafana | `public/app/features/alerting/unified/utils/search.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/Sidebar/Cards/SidebarCard.tsx` | verified |  |
| grafana | `public/app/features/inspector/InspectStatsTable.tsx` | verified |  |
| grafana | `public/app/features/logs/components/fieldSelector/suggestedFields.tsx` | verified |  |
| grafana | `public/app/features/plugins/routes.tsx` | verified |  |
| grafana | `public/app/features/provisioning/components/ProvisionedFormGate.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/components/shared/LogGroups/SelectedLogGroups.tsx` | verified |  |
| grafana | `public/app/plugins/panel/traces/suggestions.ts` | verified |  |
| prysm | `api/client/builder/client_gloas_test.go` | verified |  |
| prysm | `beacon-chain/forkchoice/ro.go` | verified |  |
| prysm | `beacon-chain/rpc/endpoints_removed.go` | verified |  |
| prysm | `beacon-chain/rpc/prysm/v1alpha1/beacon/server.go` | verified |  |
| prysm | `beacon-chain/sync/block_batcher_test.go` | verified |  |
| prysm | `consensus-types/blocks/proofs_test.go` | verified |  |
| prysm | `container/slice/slice_test.go` | verified |  |
| prysm | `testing/spectest/minimal/altair__epoch_processing__effective_balance_updates_test.go` | verified |  |
| prysm | `validator/client/beacon-api/registration.go` | verified |  |
| prysm | `validator/client/propose_test.go` | verified |  |
