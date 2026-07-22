# Target OSS no-LLM dogfooding audit — continuation 336 (batch 337)

Run: 2026-07-22T20:24:16.431425+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/crypto/internal/fips140/mldsa/mldsa_test.go` | verified |  |
| go | `src/debug/elf/elf.go` | verified |  |
| go | `src/math/rand/gen_cooked.go` | verified |  |
| go | `src/net/error_posix_test.go` | verified |  |
| go | `src/os/exec.go` | verified |  |
| go | `src/runtime/list_manual.go` | verified |  |
| go | `src/runtime/lock_wasip1.go` | verified |  |
| go | `src/runtime/secret/crash_test.go` | verified |  |
| go | `src/simd/clmul_test.go` | verified |  |
| go | `src/syscall/zerrors_freebsd_386.go` | verified |  |
| go | `test/fixedbugs/bug110.go` | verified |  |
| go | `test/fixedbugs/issue6789.dir/b.go` | verified |  |
| go | `test/typeparam/issue51245.go` | verified |  |
| grafana | `apps/dashvalidator/pkg/generated/dashboardcompatibilityscore/v1alpha1/dashboardcompatibilityscore_object_gen.go` | verified |  |
| grafana | `apps/plugins/pkg/app/storage_wrapper.go` | verified |  |
| grafana | `packages/grafana-alerting/src/grafana/rules/components/state/StateText.tsx` | verified |  |
| grafana | `packages/grafana-data/src/context/plugins/guards.ts` | verified |  |
| grafana | `packages/grafana-flamegraph/src/utils/storybook/withTheme.tsx` | verified |  |
| grafana | `packages/grafana-runtime/src/services/pluginMeta/types/plugin/types.metadata.gen.ts` | verified |  |
| grafana | `packages/grafana-runtime/src/services/pluginSettings/mappers/mappers.ts` | verified |  |
| grafana | `packages/grafana-ui/src/utils/measureText.ts` | verified |  |
| grafana | `pkg/infra/serverlock/serverlock.go` | verified |  |
| grafana | `pkg/services/folder/cleaner/contents_cleaner_test.go` | verified |  |
| grafana | `pkg/services/grpcserver/health_test.go` | verified |  |
| grafana | `pkg/services/ngalert/models/receivers.go` | verified |  |
| grafana | `pkg/services/ngalert/store/json.go` | verified |  |
| grafana | `pkg/services/publicdashboards/internal/commands/generate_datasources/main_test.go` | verified |  |
| grafana | `pkg/storage/legacysql/dualwrite/dualwriter_dryrun_test.go` | verified |  |
| grafana | `pkg/storage/unified/sql/db/migrations/resource_rv_fix_mig_test.go` | verified |  |
| grafana | `public/app/core/navigation/urlRewrite.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rules/MultipleDataSourcePicker.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/utils/template-constants.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/hooks/usePendingExpression.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/layouts-shared/paste.ts` | verified |  |
| grafana | `public/app/features/dashboard/components/ShareModal/SharePublicDashboard/ModalAlerts/PublicDashboardAlert.tsx` | verified |  |
| grafana | `public/app/features/dashboard/dashgrid/DashboardLibrary/utils/communityDashboardHelpers.ts` | verified |  |
| grafana | `public/app/features/datasources/components/picker/AddNewDataSourceButton.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/utils/sort.ts` | verified |  |
| grafana | `public/app/features/provisioning/hooks/useFolderReadme.ts` | verified |  |
| grafana | `public/app/plugins/datasource/loki/components/monaco-query-field/MonacoQueryFieldLazy.tsx` | verified |  |
| prysm | `beacon-chain/execution/testing/mock_engine_client.go` | verified |  |
| prysm | `beacon-chain/sync/block_batcher.go` | verified |  |
| prysm | `beacon-chain/sync/pending_blocks_queue_test.go` | verified |  |
| prysm | `encoding/ssz/merkleize_test.go` | verified |  |
| prysm | `testing/spectest/mainnet/capella__operations__attester_slashing_test.go` | verified |  |
| prysm | `testing/spectest/mainnet/deneb__epoch_processing__eth1_data_reset_test.go` | verified |  |
| prysm | `testing/spectest/mainnet/electra__epoch_processing__eth1_data_reset_test.go` | verified |  |
| prysm | `testing/spectest/minimal/deneb__epoch_processing__eth1_data_reset_test.go` | verified |  |
| prysm | `testing/util/bazel.go` | verified |  |
| prysm | `validator/helpers/metadata_test.go` | verified |  |
