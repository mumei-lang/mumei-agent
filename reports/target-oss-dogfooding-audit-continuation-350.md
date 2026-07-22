# Target OSS no-LLM dogfooding audit — continuation 350 (batch 351)

Run: 2026-07-22T21:04:17.171377+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/dwarfgen/marker.go` | verified |  |
| go | `src/encoding/json/internal/jsonwire/encode.go` | verified |  |
| go | `src/internal/zstd/xxhash.go` | verified |  |
| go | `src/math/big/intconv_test.go` | verified |  |
| go | `src/net/main_test.go` | verified |  |
| go | `src/simd/archsimd/internal/simd_test/simd_test.go` | verified |  |
| go | `test/codegen/issue52635.go` | verified |  |
| go | `test/fixedbugs/bug514.go` | verified |  |
| go | `test/fixedbugs/issue17449.go` | verified |  |
| go | `test/fixedbugs/issue26341.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue58671.go` | verified |  |
| go | `test/typeparam/issue48056.go` | verified |  |
| go | `test/typeparam/pairimp.go` | verified |  |
| grafana | `apps/advisor/pkg/app/metrics/metrics.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v0alpha1/dashboard_codec_gen.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/serviceaccount_deleteserviceaccounttoken_response_body_types_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/applyconfiguration/provisioning/v0alpha1/commitoptions.go` | verified |  |
| grafana | `apps/scope/pkg/apis/scope/v0alpha1/doc.go` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/TableNG/components/MaybeWrapWithLink.tsx` | verified |  |
| grafana | `pkg/cmd/grafana-cli/services/services.go` | verified |  |
| grafana | `pkg/registry/apis/dashboard/snapshot/authorizer.go` | verified |  |
| grafana | `pkg/registry/apis/folders/hooks_test.go` | verified |  |
| grafana | `pkg/registry/apis/iam/legacy/display.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/resources/client_factory_mock.go` | verified |  |
| grafana | `pkg/services/accesscontrol/actest/common.go` | verified |  |
| grafana | `pkg/services/annotations/annotationsimpl/loki/historian_store_test.go` | verified |  |
| grafana | `pkg/services/folder/folderimpl/folder_unifiedstorage.go` | verified |  |
| grafana | `pkg/services/ngalert/sender/sender_test.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/clientmiddleware/tracing_middleware.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/cache_data_mig.go` | verified |  |
| grafana | `pkg/storage/unified/search/options.go` | verified |  |
| grafana | `pkg/tests/api/datasources/datasource_get_by_uid_test.go` | verified |  |
| grafana | `public/app/core/components/AppChrome/FeatureControl/FeatureControlFloating.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rules/CloudRules.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/settings/SettingsContext.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/silences/SilencesEditor.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/Sidebar/SidebarCardGhostStyles.ts` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/TracePageHeader/SpanGraph/render-into-canvas.tsx` | verified |  |
| grafana | `public/app/features/expressions/utils/sqlIdentifier.ts` | verified |  |
| grafana | `public/app/features/logs/components/panel/LogList.tsx` | verified |  |
| prysm | `beacon-chain/rpc/eth/debug/server.go` | verified |  |
| prysm | `beacon-chain/sync/rpc_ping_test.go` | verified |  |
| prysm | `cmd/prysmctl/validator/proposer_settings.go` | verified |  |
| prysm | `testing/benchmark/pregen.go` | verified |  |
| prysm | `testing/spectest/mainnet/fulu__epoch_processing__randao_mixes_reset_test.go` | verified |  |
| prysm | `testing/spectest/mainnet/fulu__operations__bls_to_execution_change_test.go` | verified |  |
| prysm | `testing/spectest/mainnet/phase0__ssz_static__ssz_static_test.go` | verified |  |
| prysm | `testing/spectest/minimal/fulu__epoch_processing__participation_flag_updates_test.go` | verified |  |
| prysm | `testing/spectest/shared/common/operations/test_runner.go` | verified |  |
| prysm | `tools/benchmark-files-gen/main.go` | verified |  |
