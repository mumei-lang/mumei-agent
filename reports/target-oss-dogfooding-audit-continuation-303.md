# Target OSS no-LLM dogfooding audit — continuation 303 (batch 304)

Run: 2026-07-22T18:23:29.475491+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/test/intrinsics_test.go` | verified |  |
| go | `src/crypto/x509/root_darwin.go` | verified |  |
| go | `src/net/http/example_test.go` | verified |  |
| go | `src/runtime/asan.go` | verified |  |
| go | `src/runtime/defs_darwin_arm64.go` | verified |  |
| go | `src/runtime/pprof/protomem_test.go` | verified |  |
| go | `src/slices/zsortanyfunc.go` | verified |  |
| go | `src/sync/cond.go` | verified |  |
| go | `test/fixedbugs/issue11674.go` | verified |  |
| go | `test/fixedbugs/issue16095.go` | verified |  |
| go | `test/fixedbugs/issue52788.go` | verified |  |
| go | `test/nil.go` | verified |  |
| go | `test/typeparam/issue48617.go` | verified |  |
| grafana | `apps/provisioning/pkg/apis/provisioning/v0alpha1/zz_generated.openapi.go` | verified |  |
| grafana | `packages/grafana-alerting/src/grafana/notificationPolicies/hooks/useMatchPolicies.ts` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/preferences/team/baseAPI.ts` | verified |  |
| grafana | `packages/grafana-data/src/transformations/transformers/ensureColumns.ts` | verified |  |
| grafana | `packages/grafana-flamegraph/src/FlameGraph/rendering.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Cascader/styles.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/List/InlineList.tsx` | verified |  |
| grafana | `pkg/api/webassets/webassets.go` | verified |  |
| grafana | `pkg/registry/apis/dashboard/search.go` | verified |  |
| grafana | `pkg/services/authn/clients/identity.go` | verified |  |
| grafana | `pkg/services/authz/zanzana/server/reconciler/anonymous_test.go` | verified |  |
| grafana | `pkg/services/libraryelements/guard.go` | verified |  |
| grafana | `pkg/services/store/http.go` | verified |  |
| grafana | `pkg/storage/secret/encryption/query_test.go` | verified |  |
| grafana | `pkg/storage/unified/sql/sqltemplate/args.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/orgs/usagestats_test.go` | verified |  |
| grafana | `public/app/core/hooks/useCleanup.ts` | verified |  |
| grafana | `public/app/core/services/echo/backends/grafana-javascript-agent/GrafanaJavascriptAgentBackend.ts` | verified |  |
| grafana | `public/app/core/services/impression_srv.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/api/alertmanagerApi.ts` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| grafana | `public/app/features/alerting/unified/components/export/GrafanaModifyExport.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rules/RuleDetails.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rules/central-state-history/useRuleHistoryRecords.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/silences/AmAlertStateTag.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/triage/Workbench.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/mutation-api/DashboardMutationClient.ts` | verified |  |
| grafana | `public/app/features/dashboard/components/TransformationsEditor/TransformationsEditor.tsx` | verified |  |
| prysm | `beacon-chain/core/altair/reward_test.go` | verified |  |
| prysm | `beacon-chain/db/kv/wss_test.go` | verified |  |
| prysm | `beacon-chain/operations/slashings/log.go` | verified |  |
| prysm | `consensus-types/wrapper/metadata.go` | verified |  |
| prysm | `genesis/embedded.go` | verified |  |
| prysm | `testing/spectest/mainnet/deneb__operations__block_header_test.go` | verified |  |
| prysm | `testing/spectest/minimal/phase0__random__random_test.go` | verified |  |
| prysm | `testing/spectest/shared/common/operations/sync_aggregate.go` | verified |  |
| prysm | `tools/unencrypted-keys-gen/main.go` | verified |  |
| prysm | `validator/db/kv/prune_attester_protection.go` | verified |  |
