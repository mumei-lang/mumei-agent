# Target OSS no-LLM dogfooding audit — continuation 32 (batch 33)

Run: 2026-07-21T05:43:29.841529Z

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All 50 sampled files passed no-LLM verification.

## Tool-side fix

No new mumei-agent fixes were required for this batch.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| grafana | `public/app/core/components/OptionsUI/DashboardPicker.test.tsx` | verified |  |
| grafana | `public/app/features/explore/Logs/LogsMetaRow.test.tsx` | verified |  |
| go | `src/syscall/syscall_plan9_test.go` | verified |  |
| prysm | `beacon-chain/core/helpers/validators_test.go` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/variables/SectionFiltersSet.tsx` | verified |  |
| go | `src/database/sql/convert.go` | verified |  |
| go | `src/net/addrselect_test.go` | verified | No Mumei atoms |
| grafana | `packages/grafana-eslint-rules/jest.config.js` | verified |  |
| grafana | `public/app/plugins/panel/canvas/editor/element/QuickPositioning.tsx` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/ERC3156FlashBorrowerMock.sol` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/language/logs/completion/statementPosition.ts` | verified |  |
| grafana | `packages/grafana-data/src/vector/FunctionalVector.ts` | verified |  |
| go | `src/cmd/cgo/internal/test/issue18146.go` | verified |  |
| grafana | `public/app/core/components/AppChrome/MegaMenu/MegaMenuPinnedItem.test.tsx` | verified |  |
| grafana | `pkg/infra/httpclient/httpclientprovider/grafana_request_id_header_middleware_test.go` | verified | No Mumei atoms |
| go | `src/runtime/mbarrier.go` | verified |  |
| prysm | `testing/spectest/mainnet/phase0__operations__voluntary_exit_test.go` | verified | No Mumei atoms |
| grafana | `public/app/features/alerting/unified/AlertGroups.tsx` | verified |  |
| grafana | `public/app/features/provisioning/components/Dashboards/OrphanedProvisionedDrawerNotice.tsx` | verified |  |
| grafana | `public/app/features/home/AlertsIncidents/IncidentsCard.tsx` | verified |  |
| go | `src/image/color/palette/generate.go` | verified |  |
| grafana | `packages/grafana-data/src/transformations/matchers/compareValues.test.ts` | verified |  |
| go | `src/cmd/cgo/internal/testout/out_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/git/files_test.go` | verified | No Mumei atoms |
| grafana | `pkg/services/provisioning/dashboards/validator.go` | verified |  |
| go | `src/simd/archsimd/generate.go` | verified |  |
| grafana | `public/app/features/search/utils.ts` | verified |  |
| go | `src/internal/syscall/unix/kernel_version_freebsd_test.go` | verified | No Mumei atoms |
| go | `src/archive/zip/fuzz_test.go` | verified | No Mumei atoms |
| grafana | `public/app/features/variables-management/utils.ts` | verified |  |
| go | `src/cmd/covdata/subtractintersect.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/pluginconfig/envvars_test.go` | verified |  |
| prysm | `io/prompt/validate.go` | verified |  |
| grafana | `public/app/plugins/panel/timeseries/utils.test.ts` | verified | No Mumei atoms |
| go | `src/net/http/fcgi/fcgi_test.go` | verified |  |
| grafana | `e2e-playwright/dashboard-new-layouts/dashboards-edit-query-variables.spec.ts` | verified |  |
| grafana | `packages/grafana-data/src/dataframe/DataFrameJSON.test.ts` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/utils/introspection/ERC165Storage.sol` | verified |  |
| grafana | `pkg/services/pluginsintegration/pluginassets/pluginassets.go` | verified |  |
| prysm | `beacon-chain/blockchain/merge_ascii_art.go` | verified |  |
| grafana | `public/app/plugins/panel/timeseries/ThresholdsStyleEditor.test.tsx` | verified |  |
| go | `src/syscall/zsyscall_darwin_amd64.go` | verified |  |
| prysm | `async/event/interface.go` | verified |  |
| prysm | `runtime/messagehandler/messagehandler.go` | verified |  |
| prysm | `testing/spectest/minimal/fulu__operations__voluntary_exit_test.go` | verified | No Mumei atoms |
| grafana | `pkg/services/preference/generate_themes.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/generate.go` | verified |  |
| grafana | `pkg/util/proxyutil/proxyutil_test.go` | verified | No Mumei atoms |
| grafana | `public/app/features/alerting/unified/components/MoreButton.tsx` | verified |  |
| grafana | `public/app/features/connections/tabs/ConnectData/CategoryHeader/CategoryHeader.tsx` | verified |  |
