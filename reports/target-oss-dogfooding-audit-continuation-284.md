# Target OSS no-LLM dogfooding audit — continuation 284 (batch 285)

Run: 2026-07-22T17:03:39.979330+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/test/issue9400/stubs.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/pair.go` | verified |  |
| go | `src/cmd/compile/internal/types2/errors.go` | verified |  |
| go | `src/crypto/cipher/fuzz_test.go` | verified |  |
| go | `src/crypto/internal/fips140/aes/gcm/ghash.go` | verified |  |
| go | `src/database/sql/closemu.go` | verified |  |
| go | `src/go/types/gccgosizes.go` | verified |  |
| go | `src/internal/goexperiment/exp_fieldtrack_off.go` | verified |  |
| go | `src/internal/poll/export_windows_test.go` | verified |  |
| go | `src/math/nextafter.go` | verified |  |
| go | `src/reflect/internal/example2/example.go` | verified |  |
| go | `test/codegen/comparisons.go` | verified |  |
| go | `test/codegen/ifaces.go` | verified |  |
| go | `test/syntax/else.go` | verified |  |
| grafana | `apps/live/pkg/apis/live/v1alpha1/client_gen.go` | verified |  |
| grafana | `apps/plugins/pkg/app/app.go` | verified |  |
| grafana | `packages/grafana-data/src/transformations/transformers/seriesToRows.ts` | verified |  |
| grafana | `packages/grafana-flamegraph/.storybook/copyAssets.ts` | verified |  |
| grafana | `packages/grafana-i18n/src/constants.ts` | verified |  |
| grafana | `packages/grafana-test-utils/src/handlers/api/user/handlers.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/ScrollContainer/ScrollContainer.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/TableRT/styles.ts` | verified |  |
| grafana | `pkg/api/frontendlogging/grafana_javascript_agent_payload.go` | verified |  |
| grafana | `pkg/api/static/static.go` | verified |  |
| grafana | `pkg/cmd/grafana-cli/commands/log_last_migration_test.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/extras/register.go` | verified |  |
| grafana | `pkg/services/apiserver/auth/authorizer/service.go` | verified |  |
| grafana | `pkg/services/store/storage_sql_test.go` | verified |  |
| grafana | `pkg/tests/apis/alerting/notifications/common/testing.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/services/regions_test.go` | verified |  |
| grafana | `public/app/features/dashboard/state/analyticsProcessor.ts` | verified |  |
| grafana | `public/app/features/explore/QueryLibrary/mocks.tsx` | verified |  |
| grafana | `public/app/features/inspector/DetailText.tsx` | verified |  |
| grafana | `public/app/features/library-panels/components/LibraryPanelsView/reducer.ts` | verified |  |
| grafana | `public/app/features/logs/components/panel/panelState/getLogsPanelState.ts` | verified |  |
| grafana | `public/app/features/plugins/built_in_plugins.ts` | verified |  |
| grafana | `public/app/features/variables/adhoc/picker/AdHocPicker.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/graphite/components/SeriesSection.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/loki/querybuilder/components/LokiQueryBuilderContainer.tsx` | verified |  |
| grafana | `public/app/plugins/panel/timeseries/migrations.ts` | verified |  |
| prysm | `beacon-chain/blockchain/gloas_test.go` | verified |  |
| prysm | `beacon-chain/blockchain/service.go` | verified |  |
| prysm | `beacon-chain/rpc/eth/blob/server.go` | verified |  |
| prysm | `beacon-chain/rpc/eth/config/handlers.go` | verified |  |
| prysm | `container/slice/ranges_test.go` | verified |  |
| prysm | `monitoring/prometheus/service_test.go` | verified |  |
| prysm | `testing/spectest/shared/altair/epoch_processing/slashings_reset.go` | verified |  |
| prysm | `testing/spectest/shared/bellatrix/epoch_processing/inactivity_updates.go` | verified |  |
| prysm | `testing/spectest/shared/electra/operations/deposit_request.go` | verified |  |
| prysm | `testing/util/attestation_test.go` | verified |  |
