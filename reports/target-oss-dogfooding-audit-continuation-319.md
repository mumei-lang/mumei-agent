# Target OSS no-LLM dogfooding audit — continuation 319 (batch 320)

Run: 2026-07-22T19:21:58.103530+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ssa/sparseset.go` | verified |  |
| go | `src/cmd/compile/internal/typecheck/universe.go` | verified |  |
| go | `src/cmd/go/internal/load/search.go` | verified |  |
| go | `src/internal/routebsd/sys_dragonfly.go` | verified |  |
| go | `src/internal/routebsd/sys_netbsd.go` | verified |  |
| go | `src/internal/syscall/unix/arandom_netbsd.go` | verified |  |
| go | `src/internal/syscall/unix/user_darwin.go` | verified |  |
| go | `src/internal/testenv/testenv_unix.go` | verified |  |
| go | `src/net/http/h2_error_test.go` | verified |  |
| go | `src/reflect/internal/example1/example.go` | verified |  |
| go | `src/unicode/letter.go` | verified |  |
| go | `test/fixedbugs/gcc67968.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue21979.go` | verified |  |
| go | `test/fixedbugs/issue49249.go` | verified |  |
| go | `test/fixedbugs/issue53439.go` | verified |  |
| go | `test/fixedbugs/issue7044.go` | verified |  |
| grafana | `packages/grafana-data/src/panel/getPanelOptionsWithDefaults.ts` | verified |  |
| grafana | `pkg/registry/apis/preferences/store_test.go` | verified |  |
| grafana | `pkg/registry/apis/secret/decrypt/authorizer_test.go` | verified |  |
| grafana | `pkg/services/frontend/frontend_settings.go` | verified |  |
| grafana | `pkg/services/org/orgimpl/org_test.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/clientmiddleware/usealertingheaders_middleware.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/coreplugin/coreplugins_test.go` | verified |  |
| grafana | `pkg/services/provisioning/alerting/rules_types_test.go` | verified |  |
| grafana | `pkg/services/secrets/kvstore/migrations/datasource_mig_test.go` | verified |  |
| grafana | `pkg/storage/unified/search/bleve_postrank_authz.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/metric_data_input_builder_test.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/import-to-gma/Wizard/WizardLayout.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/notificaton-preview/MatchDetails.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-viewer/tabs/QueryAndCondition.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rules/useCombinedGroupNamespace.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/mutation-api/commands/addPanel.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/types/DashboardLayoutManager.ts` | verified |  |
| grafana | `public/app/features/dashboard/components/ShareModal/SharePublicDashboard/ConfigPublicDashboard/SettingsBarHeader.tsx` | verified |  |
| grafana | `public/app/features/dashboard/components/TransformationsEditor/types.ts` | verified |  |
| grafana | `public/app/features/expressions/components/SqlExpressions/SqlExpr.tsx` | verified |  |
| grafana | `public/app/features/panel/state/reducers.ts` | verified |  |
| grafana | `public/app/features/search/service/unified.ts` | verified |  |
| grafana | `public/app/features/stars/StarToolbarButton.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/mysql/fields.ts` | verified |  |
| prysm | `beacon-chain/blockchain/log_test.go` | verified |  |
| prysm | `beacon-chain/blockchain/process_block_helpers.go` | verified |  |
| prysm | `beacon-chain/db/slasherkv/pruning_test.go` | verified |  |
| prysm | `beacon-chain/rpc/eth/node/log.go` | verified |  |
| prysm | `testing/endtoend/components/eth1/miner.go` | verified |  |
| prysm | `testing/spectest/mainnet/gloas__epoch_processing__pending_deposits_churn_test.go` | verified |  |
| prysm | `testing/spectest/minimal/capella__epoch_processing__eth1_data_reset_test.go` | verified |  |
| prysm | `testing/spectest/shared/phase0/epoch_processing/justification_and_finalization.go` | verified |  |
| prysm | `testing/validator-mock/validator_mock.go` | verified |  |
| prysm | `validator/client/beacon-api/propose_exit_test.go` | verified |  |
