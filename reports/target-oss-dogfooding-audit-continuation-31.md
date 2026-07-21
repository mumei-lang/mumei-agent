# Target OSS no-LLM dogfooding audit — continuation 31 (batch 32)

Run: 2026-07-21T05:31:58.160095Z

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All 50 sampled files passed no-LLM verification after the tool-side fix.

## Tool-side fix (batch 32)

- **Go global lookup-table indexing**
  - `_go_global_array_keys` parses package-level `var X = [...]T{{ Key: ... }}` literals so that indexing by those same keyed names is recognized as valid by construction.
  - As a fallback for cross-file package constants (e.g. `types2.Typ[Invalid]`), index bounds are also suppressed when both the container and index are exported Go identifiers and the index is not a function parameter.
- Rep: `go/src/cmd/compile/internal/types2/named.go` `expandRHS`.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/runtime/os_js.go` | verified |  |
| grafana | `packages/grafana-ui/src/components/Toggletip/Toggletip.tsx` | verified |  |
| go | `src/net/netip/netip_test.go` | verified |  |
| grafana | `public/app/features/logs/components/panel/export.test.ts` | verified |  |
| grafana | `public/app/features/datasources/components/DataSourceReadOnlyMessage.tsx` | verified |  |
| go | `test/fixedbugs/bug178.go` | verified |  |
| influxdb | `influxdb3_processing_engine/src/plugins.rs` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/metrics_test.go` | verified | No Mumei atoms |
| prysm | `validator/db/kv/proposer_protection_test.go` | verified | No Mumei atoms |
| influxdb | `influxdb3_system_tables/src/parquet_files.rs` | verified |  |
| grafana | `pkg/services/live/managedstream/cache_redis.go` | verified |  |
| grafana | `apps/folder/pkg/apis/folder/v1/folder_spec_gen.go` | verified |  |
| go | `src/cmd/compile/internal/syntax/nodes_test.go` | verified |  |
| grafana | `apps/advisor/pkg/app/checks/plugincheck/check.go` | verified |  |
| grafana | `public/app/features/playlist/PlaylistPageList.tsx` | verified |  |
| go | `src/cmd/cgo/internal/test/issue26213/test26213.go` | verified | No Mumei atoms |
| grafana | `packages/grafana-ui/src/components/DateTimePickers/TimeRangePicker.tsx` | verified |  |
| go | `test/fixedbugs/issue52128.dir/p.go` | verified |  |
| grafana | `pkg/registry/apis/folders/delete_options.go` | verified |  |
| grafana | `e2e-playwright/plugin-e2e/plugin-e2e-api-tests/as-admin-user/variablePage.spec.ts` | verified |  |
| go | `src/internal/types/testdata/fixedbugs/issue50729.go` | verified |  |
| grafana | `public/app/features/serviceaccounts/ServiceAccountCreatePage.tsx` | verified |  |
| grafana | `pkg/util/sqlite/sqlite_nocgo.go` | verified |  |
| grafana | `public/app/features/alerting/unified/enterprise-components/AI/AIGenImproveLabelsButton/addAIImproveLabelsButton.ts` | verified |  |
| grafana | `pkg/services/publicdashboards/internal/api/common_test.go` | verified |  |
| grafana | `pkg/services/ngalert/schedule/ticker/ticker_test.go` | verified | No Mumei atoms |
| grafana | `apps/provisioning/pkg/repository/local/watch_test.go` | verified | No Mumei atoms |
| grafana | `public/app/plugins/datasource/azuremonitor/utils/common.test.ts` | verified |  |
| grafana | `public/app/features/provisioning/hooks/usePullRequestParam.test.ts` | verified |  |
| go | `test/typeparam/listimp.dir/a.go` | verified |  |
| go | `src/cmd/compile/internal/types2/named.go` | verified |  |
| influxdb | `influxdb3_catalog/src/enterprise/format/records/token/tests.rs` | verified |  |
| go | `test/typeparam/issue51232.go` | verified |  |
| prysm | `testing/bls/batch_verify_test.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v2/zz_generated.deepcopy.go` | verified |  |
| go | `test/fixedbugs/bug473.go` | verified |  |
| grafana | `packages/grafana-runtime/src/services/pluginSettings/settings.ts` | verified |  |
| go | `src/cmd/internal/sys/arch_test.go` | verified | No Mumei atoms |
| go | `test/fixedbugs/issue29612.dir/main.go` | verified |  |
| grafana | `public/app/features/dashboard/components/Inspector/hooks.test.ts` | verified |  |
| grafana | `pkg/plugins/codegen/pfs/pfs.go` | verified |  |
| grafana | `public/app/features/datasources/state/actions.test.ts` | verified |  |
| prysm | `config/params/testnet_config_test.go` | verified |  |
| go | `src/syscall/zsyscall_openbsd_arm.go` | verified |  |
| go | `src/go/types/selection.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rules/Filter/useRuleFilterAutocomplete.ts` | verified |  |
| grafana | `public/app/core/components/Select/UserPicker.test.tsx` | verified |  |
| grafana | `pkg/tests/apis/provisioning/quota/quota_test.go` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/mocks/queries.ts` | verified |  |
| go | `src/cmd/api/testdata/src/pkg/p4/p4.go` | verified |  |
