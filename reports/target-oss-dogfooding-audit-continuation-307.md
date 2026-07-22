# Target OSS no-LLM dogfooding audit — continuation 307 (batch 308)

Run: 2026-07-22T18:37:53.743464+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ssa/biasedsparsemap.go` | verified |  |
| go | `src/context/context_test.go` | verified |  |
| go | `src/crypto/internal/fips140/sha3/sha3_arm64.go` | verified |  |
| go | `src/image/png/paeth.go` | verified |  |
| go | `src/net/main_posix_test.go` | verified |  |
| go | `src/net/netgo_on.go` | verified |  |
| go | `src/runtime/slice_test.go` | verified |  |
| go | `src/runtime/trace/trace.go` | verified |  |
| go | `src/simd/archsimd/internal/simd_test/compare_128_test.go` | verified |  |
| go | `src/simd/midway_amd64.go` | verified |  |
| go | `test/fixedbugs/bug229.go` | verified |  |
| go | `test/fixedbugs/bug407.dir/two.go` | verified |  |
| go | `test/fixedbugs/bug434.go` | verified |  |
| go | `test/fixedbugs/bug487.go` | verified |  |
| go | `test/fixedbugs/issue22063.go` | verified |  |
| go | `test/fixedbugs/issue7867.go` | verified |  |
| grafana | `apps/shorturl/plugin/src/generated/shorturl/v1beta1/shorturl_object_gen.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/MatchersUI/FieldsByFrameRefIdMatcher.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/utils/storybook/themeStorybookControls.tsx` | verified |  |
| grafana | `pkg/api/datasources_k8s_test.go` | verified |  |
| grafana | `pkg/plugins/tracing/tracing.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/controller/webhook_integration_test.go` | verified |  |
| grafana | `pkg/services/authz/zanzana/server/server_batch_check.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/legacy_storage/receivers.go` | verified |  |
| grafana | `pkg/services/ngalert/schedule/rule_sequence_store_k8s.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrator/sqlite_dialect.go` | verified |  |
| grafana | `pkg/tsdb/azuremonitor/metrics/azuremonitor-datasource_test.go` | verified |  |
| grafana | `pkg/util/retryer/retryer.go` | verified |  |
| grafana | `pkg/util/xorm/dialect_mysql.go` | verified |  |
| grafana | `public/app/features/correlations/useCorrelationsK8s.ts` | verified |  |
| grafana | `public/app/features/explore/NoDataSourceCallToAction.tsx` | verified |  |
| grafana | `public/app/features/inspector/utils/transformToZipkin.ts` | verified |  |
| grafana | `public/app/features/plugins/admin/hooks/usePluginPageExtensions.tsx` | verified |  |
| grafana | `public/app/features/plugins/components/restrictedGrafanaApis/RestrictedGrafanaApisProvider.tsx` | verified |  |
| grafana | `public/app/features/provisioning/hooks/useSelectionProvisioningStatus.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/components/shared/SelectionSearchInput.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/grafana-testdata-datasource/dataquery.ts` | verified |  |
| grafana | `public/app/plugins/panel/logstable/LogsTable.tsx` | verified |  |
| grafana | `public/app/plugins/panel/timeseries/config.ts` | verified |  |
| grafana | `tools/setup_grafana_alertmanager_integration_test_images.go` | verified |  |
| prysm | `beacon-chain/rpc/eth/validator/server.go` | verified |  |
| prysm | `beacon-chain/rpc/prysm/node/handlers_test.go` | verified |  |
| prysm | `beacon-chain/state/state-native/setters_eth1.go` | verified |  |
| prysm | `encoding/ssz/query/path_test.go` | verified |  |
| prysm | `proto/prysm/v1alpha1/gloas.minimal.ssz.go` | verified |  |
| prysm | `testing/spectest/mainnet/altair__fork_helper__upgrade_to_altair_test.go` | verified |  |
| prysm | `testing/spectest/mainnet/phase0__epoch_processing__historical_roots_update_test.go` | verified |  |
| prysm | `testing/spectest/minimal/bellatrix__forkchoice__forkchoice_test.go` | verified |  |
| prysm | `testing/spectest/minimal/fulu__epoch_processing__inactivity_updates_test.go` | verified |  |
| prysm | `testing/spectest/shared/common/operations/voluntary_exit.go` | verified |  |
