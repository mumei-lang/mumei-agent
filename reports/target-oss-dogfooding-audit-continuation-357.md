# Target OSS no-LLM dogfooding audit — continuation 357 (batch 358)

Run: 2026-07-22T21:27:05.699474+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/go/internal/tool/signal.go` | verified |  |
| go | `src/cmd/pprof/readlineui.go` | verified |  |
| go | `src/crypto/cipher/cipher.go` | verified |  |
| go | `src/crypto/internal/boring/bbig/big.go` | verified |  |
| go | `src/go/printer/performance_test.go` | verified |  |
| go | `src/internal/race/norace.go` | verified |  |
| go | `src/log/slog/json_handler.go` | verified |  |
| go | `src/math/exp_amd64.go` | verified |  |
| go | `src/net/rawconn_stub_test.go` | verified |  |
| go | `src/runtime/pprof/pprof_rusage.go` | verified |  |
| go | `src/simd/archsimd/_gen/sgutil/compare_natural.go` | verified |  |
| go | `test/defer.go` | verified |  |
| go | `test/fixedbugs/bug271.go` | verified |  |
| go | `test/fixedbugs/issue20789.go` | verified |  |
| go | `test/typeparam/issue50259.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v0alpha1/templategroup_schema_gen.go` | verified |  |
| grafana | `apps/live/pkg/apis/live/v1alpha1/channel_object_gen.go` | verified |  |
| grafana | `apps/plugins/pkg/app/app_test.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/extra_mock.go` | verified |  |
| grafana | `packages/grafana-e2e-selectors/src/types/selectors.ts` | verified |  |
| grafana | `packages/grafana-ui/src/utils/logger.ts` | verified |  |
| grafana | `pkg/registry/apis/provisioning/controller/token_metrics.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/migrate/mock_migrator.go` | verified |  |
| grafana | `pkg/services/authn/clients/basic_test.go` | verified |  |
| grafana | `pkg/services/authz/zanzana/server/reconciler/namespace_test.go` | verified |  |
| grafana | `pkg/services/caching/metrics.go` | verified |  |
| grafana | `pkg/services/ngalert/models/history.go` | verified |  |
| grafana | `pkg/services/preference/model.go` | verified |  |
| grafana | `public/app/core/components/ValidationLabels/ValidationLabels.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/api/sloApi.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/import-to-gma/steps/StepReviewEnableAutoSync.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/hooks/abilities/alertmanager/useAlertGroupAbility.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/search/search.js` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/StackedEditor/StackedEditorRenderer.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/ProvisionedControlsSection.tsx` | verified |  |
| grafana | `public/app/features/logs/legacyLogsFrame.ts` | verified |  |
| grafana | `public/app/features/provisioning/Config/BranchOptionsSection.tsx` | verified |  |
| grafana | `public/app/features/provisioning/Shared/ProvisioningAlert.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/loki/configuration/DerivedField.tsx` | verified |  |
| grafana | `public/app/types/supportBundles.ts` | verified |  |
| prysm | `beacon-chain/blockchain/testing/mock.go` | verified |  |
| prysm | `beacon-chain/core/blocks/payload_test.go` | verified |  |
| prysm | `beacon-chain/core/gloas/builder_exit.go` | verified |  |
| prysm | `cmd/beacon-chain/execution/log.go` | verified |  |
| prysm | `monitoring/prometheus/logrus_collector.go` | verified |  |
| prysm | `proto/prysm/v1alpha1/sync_committee.minimal.pb.go` | verified |  |
| prysm | `runtime/fdlimits/log.go` | verified |  |
| prysm | `testing/spectest/mainnet/deneb__epoch_processing__slashings_reset_test.go` | verified |  |
| prysm | `testing/spectest/shared/electra/epoch_processing/historical_summaries_update.go` | verified |  |
| prysm | `validator/client/beacon-api/payload_attestation_test.go` | verified |  |
