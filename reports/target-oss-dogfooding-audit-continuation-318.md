# Target OSS no-LLM dogfooding audit — continuation 318 (batch 319)

Run: 2026-07-22T19:12:45.547609+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/inline/inlheur/names.go` | verified |  |
| go | `src/cmd/compile/internal/typecheck/syms.go` | verified |  |
| go | `src/cmd/compile/internal/walk/stmt.go` | verified |  |
| go | `src/cmd/go/internal/modfetch/repo.go` | verified |  |
| go | `src/crypto/internal/cryptotest/block.go` | verified |  |
| go | `src/image/jpeg/fuzz_test.go` | verified |  |
| go | `src/internal/syscall/unix/getrandom_linux_test.go` | verified |  |
| go | `src/math/big/natmul.go` | verified |  |
| go | `src/os/executable_netbsd.go` | verified |  |
| go | `src/sync/once_test.go` | verified |  |
| go | `src/syscall/linkname_darwin.go` | verified |  |
| go | `src/syscall/linkname_libc.go` | verified |  |
| go | `test/fixedbugs/bug404.dir/one.go` | verified |  |
| go | `test/fixedbugs/issue22662b.go` | verified |  |
| go | `test/fixedbugs/issue36085.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v1/doc.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/conversion/v2alpha1_to_v2beta1_test.go` | verified |  |
| grafana | `packages/grafana-data/src/types/queryRunner.ts` | verified |  |
| grafana | `packages/grafana-sql/src/components/visual-query-builder/SelectFunctionParameters.tsx` | verified |  |
| grafana | `packages/grafana-test-utils/src/handlers/api/plugins/handlers.ts` | verified |  |
| grafana | `packages/grafana-ui/src/themes/ThemeContext.tsx` | verified |  |
| grafana | `pkg/registry/apis/iam/externalgroupmapping/models.go` | verified |  |
| grafana | `pkg/services/dashboardsnapshots/helper.go` | verified |  |
| grafana | `pkg/services/datasources/service/store.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/pluginconfig/envvars.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/dashboard_public_mig.go` | verified |  |
| grafana | `pkg/setting/setting_time_picker.go` | verified |  |
| grafana | `pkg/setting/setting_unified_alerting_test.go` | verified |  |
| grafana | `pkg/storage/unified/search/remote_index_cleanup_test.go` | verified |  |
| grafana | `pkg/storage/unified/sql/rvmanager/templates.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/git/managed_dashboard_commit_message_test.go` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/layouts-shared/CanvasGridAddActions.tsx` | verified |  |
| grafana | `public/app/features/dashboard/services/DashboardProfiler.ts` | verified |  |
| grafana | `public/app/features/dashboard/services/DashboardSrv.ts` | verified |  |
| grafana | `public/app/features/dashboard/state/TimeModel.ts` | verified |  |
| grafana | `public/app/features/datasources/components/DataSourcesListHeader.tsx` | verified |  |
| grafana | `public/app/features/dimensions/editors/ResourcePicker.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/loki/components/LokiLabelBrowser.tsx` | verified |  |
| grafana | `public/app/plugins/panel/geomap/utils/tooltip.ts` | verified |  |
| prysm | `beacon-chain/p2p/pubsub_filter_test.go` | verified |  |
| prysm | `beacon-chain/state/stateutil/trie_helpers.go` | verified |  |
| prysm | `cmd/prysmctl/testnet/generate_genesis.go` | verified |  |
| prysm | `config/params/testnet_hoodi_config_test.go` | verified |  |
| prysm | `proto/prysm/v1alpha1/slashings/surround_votes_test.go` | verified |  |
| prysm | `runtime/prereqs/log.go` | verified |  |
| prysm | `testing/endtoend/components/builder.go` | verified |  |
| prysm | `testing/endtoend/components/validator.go` | verified |  |
| prysm | `testing/spectest/mainnet/capella__operations__withdrawals_test.go` | verified |  |
| prysm | `testing/spectest/mainnet/fulu__ssz_static__ssz_static_test.go` | verified |  |
| prysm | `testing/spectest/shared/phase0/epoch_processing/effective_balance_updates.go` | verified |  |
