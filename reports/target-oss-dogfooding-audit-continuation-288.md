# Target OSS no-LLM dogfooding audit — continuation 288 (batch 289)

Run: 2026-07-22T17:14:22.887402+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ssa/poset_test.go` | verified |  |
| go | `src/encoding/gob/codec_test.go` | verified |  |
| go | `src/net/cgo_unix.go` | verified |  |
| go | `src/syscall/syscall_linux_ppc64x.go` | verified |  |
| go | `src/syscall/ztypes_netbsd_arm64.go` | verified |  |
| go | `src/testing/fstest/mapfs.go` | verified |  |
| go | `test/fixedbugs/issue12588.go` | verified |  |
| go | `test/fixedbugs/issue19217.go` | verified |  |
| go | `test/fixedbugs/issue23017.go` | verified |  |
| go | `test/fixedbugs/issue45359.go` | verified |  |
| go | `test/fixedbugs/issue50788.dir/b.go` | verified |  |
| go | `test/typeparam/mapsimp.dir/a.go` | verified |  |
| go | `test/typeparam/orderedmapsimp.go` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/shorturl/v1beta1/index.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/Cells/ImageCell.tsx` | verified |  |
| grafana | `pkg/plugins/manager/pipeline/discovery/doc.go` | verified |  |
| grafana | `pkg/registry/apps/alerting/notifications/register_test.go` | verified |  |
| grafana | `pkg/services/apiserver/appinstaller/installer.go` | verified |  |
| grafana | `pkg/services/authz/zanzana/server/reconciler/noop.go` | verified |  |
| grafana | `pkg/services/libraryelements/accesscontrol.go` | verified |  |
| grafana | `pkg/services/rendering/auth.go` | verified |  |
| grafana | `pkg/setting/setting_quota.go` | verified |  |
| grafana | `pkg/storage/unified/search/builders/user.go` | verified |  |
| grafana | `pkg/storage/unified/sql/server.go` | verified |  |
| grafana | `public/app/core/components/AppChrome/MegaMenu/MegaMenuCustomiseControls.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/alert-rule-form/formValuesToAppPlatform.ts` | verified |  |
| grafana | `public/app/features/auth-config/components/ConfigureAuthCTA.tsx` | verified |  |
| grafana | `public/app/features/connections/hooks/useIsAlertingSupported.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/Header/ExperimentalFeedbackButton.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/layout-rows/RowItem.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/new-toolbar/actions/ShareExportDashboardButton.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/serialization/groupByMigration.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/utils/predefinedVariables.ts` | verified |  |
| grafana | `public/app/features/logs/components/panel/HighlightedLogRenderer.tsx` | verified |  |
| grafana | `public/app/features/migrate-to-cloud/cloud/MigrationTokenPane/TokenStatus.tsx` | verified |  |
| grafana | `public/app/features/plugins/importer/addTranslationsToI18n.ts` | verified |  |
| grafana | `public/app/features/provisioning/GettingStarted/EnhancedFeatures.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/influxdb/components/editor/query/influxql/visual/FromSection.tsx` | verified |  |
| grafana | `public/app/plugins/panel/gauge/module.tsx` | verified |  |
| grafana | `public/app/plugins/panel/gettingstarted/components/sharedStyles.ts` | verified |  |
| prysm | `beacon-chain/forkchoice/ro_test.go` | verified |  |
| prysm | `beacon-chain/p2p/encoder/ssz.go` | verified |  |
| prysm | `beacon-chain/state/state-native/readonly_validator.go` | verified |  |
| prysm | `cmd/prysmctl/p2p/handler.go` | verified |  |
| prysm | `config/params/init.go` | verified |  |
| prysm | `proto/prysm/v1alpha1/payload_attestation_minimal.go` | verified |  |
| prysm | `testing/spectest/minimal/fulu__operations__bls_to_execution_change_test.go` | verified |  |
| prysm | `testing/spectest/shared/electra/sanity/block_processing.go` | verified |  |
| prysm | `testing/validator-mock/validator_client_mock.go` | verified |  |
| prysm | `validator/client/beacon-api/test-helpers/gloas_beacon_block_test_helpers.go` | verified |  |
