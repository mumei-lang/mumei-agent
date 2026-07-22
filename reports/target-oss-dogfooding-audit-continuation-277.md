# Target OSS no-LLM dogfooding audit — continuation 277 (batch 278)

Run: 2026-07-22T16:36:52.533730+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification after fixing gob idToType guards and local map alias detection.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/inline/inlheur/dumpscores_test.go` | verified |  |
| go | `src/cmd/go/scriptconds_test.go` | verified |  |
| go | `src/encoding/gob/type.go` | verified |  |
| go | `src/encoding/json/internal/jsonopts/options_test.go` | verified |  |
| go | `src/internal/cpu/datacache_unsupported.go` | verified |  |
| go | `src/internal/runtime/atomic/atomic_andor_test.go` | verified |  |
| go | `src/internal/syscall/unix/faccessat_openbsd.go` | verified |  |
| go | `src/os/root_windows_test.go` | verified |  |
| go | `test/codegen/writebarrier.go` | verified |  |
| go | `test/dwarf/dwarf.dir/z4.go` | verified |  |
| go | `test/env.go` | verified |  |
| go | `test/fixedbugs/bug167.go` | verified |  |
| go | `test/fixedbugs/bug175.go` | verified |  |
| go | `test/fixedbugs/issue18906.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/mutator.go` | verified |  |
| grafana | `devenv/docker/blocks/elastic/data/data.js` | verified |  |
| grafana | `devenv/scopes/scopes.go` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/collections/v1alpha1/baseAPI.ts` | verified |  |
| grafana | `packages/grafana-sql/rollup.config.ts` | verified |  |
| grafana | `pkg/infra/features/doc.go` | verified |  |
| grafana | `pkg/registry/apis/iam/authorizer/parent_provider_test.go` | verified |  |
| grafana | `pkg/server/wire_gen.go` | verified |  |
| grafana | `pkg/services/dashboards/models.go` | verified |  |
| grafana | `pkg/services/ngalert/api/tooling/definitions/ruler_state_history.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/clientmiddleware/tracing_middleware_test.go` | verified |  |
| grafana | `pkg/services/serviceaccounts/database/store.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/short_url_mig.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/foldermetadata/helper_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/git/incrementaldiffthreshold/incremental_diff_threshold_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/git/sourcepath_guard/sourcepath_guard_test.go` | verified |  |
| grafana | `pkg/util/svg_test.go` | verified |  |
| grafana | `public/app/features/alerting/unified/hooks/ruleGroup/useDeleteRuleFromGroup.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/hooks/useSilenceViewData.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/mocks/server/handlers/k8s/receivers.k8s.ts` | verified |  |
| grafana | `public/app/features/dashboard/components/GenAI/GenAIDashTitleButton.tsx` | verified |  |
| grafana | `public/app/features/expressions/ExpressionDatasource.ts` | verified |  |
| grafana | `public/app/features/migrate-to-cloud/fixtures/migrationItems.ts` | verified |  |
| grafana | `public/app/features/provisioning/Wizard/utils/getSteps.ts` | verified |  |
| prysm | `beacon-chain/operations/synccommittee/error.go` | verified |  |
| prysm | `beacon-chain/p2p/utils.go` | verified |  |
| prysm | `beacon-chain/rpc/service_test.go` | verified |  |
| prysm | `beacon-chain/state/state-native/getters_exit_test.go` | verified |  |
| prysm | `cmd/prysmctl/weaksubjectivity/log.go` | verified |  |
| prysm | `proto/engine/v1/electra.go` | verified |  |
| prysm | `testing/spectest/mainnet/fulu__operations__execution_payload_test.go` | verified |  |
| prysm | `testing/spectest/minimal/fulu__operations__deposit_requests_test.go` | verified |  |
| prysm | `testing/spectest/minimal/gloas__finality__finality_test.go` | verified |  |
| prysm | `testing/util/slot.go` | verified |  |
| prysm | `tools/analyzers/modernize/slicescontains/analyzer.go` | verified |  |
| prysm | `tools/replay-http/main.go` | verified |  |
