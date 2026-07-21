# Target OSS no-LLM dogfooding audit — continuation 33 (batch 34)

Run: 2026-07-21T07:15:55.176816Z

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All 50 sampled files passed no-LLM verification after the tool-side fix.

## Tool-side fix (batch 34)

- **Go alignment/roundup overflow**
  - The idiomatic alignment expression ``(x + y - 1) &^ (y - 1)`` is recognized and the intermediate ``+`` overflow warning is suppressed.
  - Added `_is_roundup_expression` and used it in `_i64_overflow_safety_issue`.
  - Rep: `go/src/internal/routebsd/sys.go` `roundup`.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| grafana | `apps/provisioning/pkg/connection/delete_validator.go` | verified |  |
| grafana | `public/app/features/plugins/admin/pages/Browse.tsx` | verified |  |
| influxdb | `core/data_types/src/snapshot/partition.rs` | verified |  |
| grafana | `public/app/features/dashboard-scene/solo/SoloPanelPageLogo.test.tsx` | verified |  |
| grafana | `apps/provisioning/pkg/generated/informers/externalversions/provisioning/v0alpha1/connection.go` | verified |  |
| grafana | `public/app/features/dashboard/components/GenAI/GenAIHistory.tsx` | verified |  |
| go | `test/dwarf/dwarf.dir/z7.go` | verified |  |
| grafana | `pkg/services/diagnostics/diagnostics_test.go` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/utils/structs/EnumerableSet.sol` | verified |  |
| grafana | `e2e-playwright/panels-suite/gauge.spec.ts` | verified |  |
| go | `src/encoding/json/v2/arshal_default.go` | verified |  |
| prysm | `beacon-chain/sync/backfill/status_test.go` | verified |  |
| go | `src/cmd/cgo/internal/test/seh_windows_test.go` | verified | No Mumei atoms |
| grafana | `pkg/storage/unified/sql/notifier.go` | verified |  |
| go | `test/fixedbugs/issue4964.go` | verified |  |
| grafana | `public/app/features/alerting/unified/rule-list/DataSourceGroupLoader.tsx` | verified |  |
| grafana | `pkg/registry/apis/iam/globalrole/inmemory/models.go` | verified |  |
| grafana | `pkg/registry/apis/iam/team/validate.go` | verified |  |
| grafana | `packages/grafana-ui/src/components/FileDropzone/FileDropzone.tsx` | verified |  |
| grafana | `pkg/services/pluginsintegration/managedplugins/managed.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/folderscope/folder_annotation_guard_test.go` | verified | No Mumei atoms |
| grafana | `public/app/features/alerting/unified/components/rule-viewer/RuleViewerVisualization.tsx` | verified |  |
| go | `src/net/fd_wasip1.go` | verified |  |
| go | `src/internal/routebsd/sys.go` | verified |  |
| go | `test/fixedbugs/bug288.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/git/git.go` | verified |  |
| grafana | `public/app/core/components/AppChrome/MegaMenu/MegaMenuExtensionPoint.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/mute-timings/EditMuteTiming.tsx` | verified |  |
| grafana | `pkg/plugins/manager/pipeline/validation/doc.go` | verified |  |
| go | `src/internal/types/testdata/fixedbugs/issue48008.go` | verified | No Mumei atoms |
| go | `src/crypto/internal/fips140/nistec/fiat/benchmark_test.go` | verified | No Mumei atoms |
| prysm | `third_party/go-bip39/wordlists/french.go` | verified |  |
| grafana | `pkg/services/apiserver/options/options.go` | verified |  |
| prysm | `beacon-chain/p2p/peers/assigner_test.go` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/TransformationFilterDisplay.tsx` | verified |  |
| grafana | `public/app/features/dashboard/services/ScenePerformanceLogger.ts` | verified |  |
| grafana | `public/app/plugins/datasource/grafana-testdata-datasource/components/ErrorEditor.tsx` | verified |  |
| grafana | `public/app/features/dashboard/dashgrid/DashboardLibrary/utils/templatePermissions.ts` | verified |  |
| go | `src/net/http/internal/http2/server_internal_test.go` | verified | No Mumei atoms |
| grafana | `public/app/features/alerting/unified/components/notification-policies/PoliciesTree.tsx` | verified |  |
| grafana | `pkg/services/secrets/types.go` | verified |  |
| prysm | `beacon-chain/core/electra/error.go` | verified |  |
| prysm | `testing/spectest/shared/deneb/epoch_processing/helpers.go` | verified |  |
| grafana | `pkg/storage/unified/sql/backend.go` | verified |  |
| grafana | `public/app/features/canvas/elements/windTurbine.tsx` | verified |  |
| grafana | `pkg/services/pluginsintegration/plugininstaller/service.go` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/types/TNil.tsx` | verified |  |
| go | `test/fixedbugs/issue23732.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v2-periphery/interfaces/IWETH.sol` | verified |  |
| grafana | `public/app/features/variables/query/adapter.ts` | verified |  |
