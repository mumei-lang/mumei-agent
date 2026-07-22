# Target OSS no-LLM dogfooding audit — continuation 289 (batch 290)

Run: 2026-07-22T17:24:21.899488+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ssa/rewriteLOONG64.go` | verified |  |
| go | `src/crypto/internal/fips140/bigmod/nat_test.go` | verified |  |
| go | `src/go/types/literals.go` | verified |  |
| go | `src/internal/abi/type.go` | verified |  |
| go | `src/runtime/stubs_linux.go` | verified |  |
| go | `src/time/format_rfc3339.go` | verified |  |
| go | `test/fixedbugs/bug045.go` | verified |  |
| go | `test/fixedbugs/bug415.go` | verified |  |
| go | `test/fixedbugs/issue14636.go` | verified |  |
| go | `test/fixedbugs/issue20298.go` | verified |  |
| go | `test/fixedbugs/issue24761.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue27836.dir/Þmain.go` | verified |  |
| go | `test/fixedbugs/issue49512.go` | verified |  |
| go | `test/typeparam/issue49893.dir/a.go` | verified |  |
| grafana | `.github/actions/changelog/semver.js` | verified |  |
| grafana | `apps/advisor/pkg/app/checks/authchecks/list_format_validation_test.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/conversion/v2alpha1_to_v1.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/applyconfiguration/provisioning/v0alpha1/gitrepositoryconfig.go` | verified |  |
| grafana | `packages/grafana-ui/src/components/ToolbarButton/ToolbarButtonRow.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/uPlot/config/gradientFills.ts` | verified |  |
| grafana | `pkg/expr/threshold_test.go` | verified |  |
| grafana | `pkg/mocks/mock_gcsifaces/mocks.go` | verified |  |
| grafana | `pkg/plugins/manager/registry/in_memory.go` | verified |  |
| grafana | `pkg/services/login/authinfotest/auth_info_service_mock.go` | verified |  |
| grafana | `pkg/services/ngalert/api/api_ruler_test.go` | verified |  |
| grafana | `pkg/services/ngalert/state/persister_async_rule_test.go` | verified |  |
| grafana | `pkg/services/secrets/manager/cache.go` | verified |  |
| grafana | `pkg/services/store/types_test.go` | verified |  |
| grafana | `pkg/util/ip_address.go` | verified |  |
| grafana | `pkg/util/xorm/engine_cond.go` | verified |  |
| grafana | `pkg/web/tree.go` | verified |  |
| grafana | `public/app/core/components/GraphNG/types.ts` | verified |  |
| grafana | `public/app/core/components/NavLandingPage/NavLandingPage.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/ExpressionsEditor.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/settings/useAutoSyncConfiguration.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/home/PluginIntegrations.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/rule-list/components/RuleActionsButtons.V2.tsx` | verified |  |
| grafana | `public/app/features/explore/SupplementaryResultError.tsx` | verified |  |
| grafana | `public/app/features/home/HomeRoute.tsx` | verified |  |
| grafana | `public/app/features/search/page/components/ActionRow.tsx` | verified |  |
| prysm | `beacon-chain/core/transition/bellatrix_transition_no_verify_sig_test.go` | verified |  |
| prysm | `beacon-chain/forkchoice/error.go` | verified |  |
| prysm | `beacon-chain/rpc/prysm/v1alpha1/validator/proposer_capella.go` | verified |  |
| prysm | `crypto/keystore/utils.go` | verified |  |
| prysm | `testing/spectest/minimal/bellatrix__fork__upgrade_to_altair_test.go` | verified |  |
| prysm | `testing/spectest/shared/common/forkchoice/service.go` | verified |  |
| prysm | `validator/client/beacon-api/prepare_beacon_proposer.go` | verified |  |
| prysm | `validator/db/filesystem/db.go` | verified |  |
| prysm | `validator/db/kv/deprecated_attester_protection_test.go` | verified |  |
| prysm | `validator/keymanager/remote-web3signer/internal/client.go` | verified |  |
