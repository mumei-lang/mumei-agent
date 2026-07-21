# Target OSS no-LLM dogfooding audit — continuation 29 (batch 30)

Run: 2026-07-21T04:57:48.311208Z

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All 50 sampled files passed no-LLM verification after the tool-side fix.

## Tool-side fix (batch 30)

- **Go non-nil framework/container receivers and parameters**
  - `_go_nonnil_param_names` recognizes pointer receivers/parameters whose unqualified type name ends with `Service`, `Node`, `Handler`, `Manager`, `Store`, `Client`, `Provider`, `Server`, `Resolver`, `Registry`, or `Factory`.
  - These values are removed from the nil-dereference `dereference_values` set, because their methods are caller-contract non-nil (e.g. dependency-injected `*Service`, pipeline `*Node`).
  - Rep: `grafana/pkg/expr/nodes.go` (`baseNode.String`, `CMDNode.NeedsVars`/`Execute`, `*Service` parameter).

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/crypto/rsa/notboring.go` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/LogsQueryBuilder/LimitSection.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/utils/registerDynamicDashNavAction.ts` | verified |  |
| go | `src/cmd/cgo/internal/testplugin/testdata/method3/main.go` | verified |  |
| go | `test/fixedbugs/issue15733.go` | verified |  |
| go | `test/fixedbugs/issue17381.go` | verified |  |
| go | `src/syscall/ztypes_freebsd_riscv64.go` | verified |  |
| go | `test/fixedbugs/issue26340.go` | verified |  |
| prysm | `beacon-chain/state/state-native/getters_attestation.go` | verified |  |
| uniswap-contracts | `src/briefcase/deployers/v2-periphery/UniswapV2Router02Deployer.sol` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/AlertStatesDataLayer.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/TableNG/Cells/ActionsCell.tsx` | verified |  |
| grafana | `public/app/core/components/Signup/VerifyEmailPage.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/assistant/ViewModePanelPromptCard.tsx` | verified |  |
| grafana | `pkg/api/datasource/validation/validation.go` | verified |  |
| grafana | `public/app/features/inspector/styles.ts` | verified |  |
| go | `src/syscall/syscall_linux_arm.go` | verified |  |
| grafana | `pkg/services/authz/zanzana/client/shadow_rbac_client.go` | verified |  |
| grafana | `public/app/features/dashboard/state/PanelModel.ts` | verified |  |
| grafana | `public/app/plugins/panel/geomap/view.test.ts` | verified |  |
| grafana | `pkg/services/live/pipeline/frame_output_redirect.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/role_spec_gen.go` | verified |  |
| prysm | `testing/bls/aggregate_test.yaml.go` | verified |  |
| go | `src/runtime/tracetype.go` | verified |  |
| grafana | `packages/grafana-ui/src/components/Forms/InlineLabel.story.tsx` | verified |  |
| grafana | `apps/correlations/plugin/src/generated/correlation/v0alpha1/correlation_object_gen.ts` | verified |  |
| go | `test/fixedbugs/issue24760.go` | verified |  |
| go | `src/cmd/cgo/internal/test/issue42018.go` | verified |  |
| go | `src/archive/zip/reader_test.go` | verified |  |
| grafana | `public/app/features/dashboard-scene/serialization/transformSceneToSaveModelSchemaV2.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Sidebar/SidebarPaneHeader.tsx` | verified |  |
| go | `src/internal/types/testdata/spec/comparable1.19.go` | verified |  |
| go | `src/cmd/internal/par/work.go` | verified |  |
| grafana | `packages/grafana-sql/src/components/configuration/useMigrateDatabaseFields.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/insights/mimir/AlertsByState.tsx` | verified |  |
| grafana | `pkg/expr/mathexp/resample.go` | verified |  |
| grafana | `packages/grafana-data/src/dataframe/processDataFrame.ts` | verified |  |
| grafana | `public/app/features/explore/extensions/toolbar/types.ts` | verified |  |
| go | `src/cmd/cgo/internal/test/test.go` | verified |  |
| grafana | `pkg/expr/nodes.go` | verified |  |
| grafana | `pkg/services/publicdashboards/internal/service/service.go` | verified |  |
| go | `test/fixedbugs/bug366.go` | verified |  |
| grafana | `public/app/features/dashboard-scene/edit-pane/events.ts` | verified |  |
| prysm | `cmd/prysmctl/validator/proposer_settings_test.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v5_test.go` | verified | No Mumei atoms |
| grafana | `public/app/features/alerting/unified/insights/mimir/perGroup/RuleGroupIntervalScene.tsx` | verified |  |
| go | `src/internal/types/testdata/fixedbugs/issue51048.go` | verified |  |
| go | `src/crypto/internal/fips140/nistec/p224.go` | verified |  |
| prysm | `third_party/go-bip39/wordlists/chinese_traditional.go` | verified |  |
| grafana | `pkg/services/ldap/api/dtos.go` | verified |  |
