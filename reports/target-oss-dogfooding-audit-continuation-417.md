# Target OSS no-LLM dogfooding audit — continuation 417 (batch 418)

Run: 2026-07-23T01:23:56.995355+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `misc/chrome/gophertool/gopher.js` | verified |  |
| go | `src/cmd/compile/internal/noder/codes.go` | verified |  |
| go | `src/cmd/compile/internal/objw/prog.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/shift_test.go` | verified |  |
| go | `src/cmd/internal/obj/x86/list6.go` | verified |  |
| go | `src/crypto/internal/fips140/rsa/rsa.go` | verified |  |
| go | `src/encoding/gob/type_test.go` | verified |  |
| go | `src/io/export_test.go` | verified |  |
| go | `src/net/http/responsecontroller_test.go` | verified |  |
| go | `src/net/netip/uint128.go` | verified |  |
| go | `src/strconv/bytealg_bootstrap.go` | verified |  |
| go | `src/time/zoneinfo_windows_test.go` | verified |  |
| go | `test/chan/fifo.go` | verified |  |
| go | `test/fixedbugs/bug006.go` | verified |  |
| go | `test/fixedbugs/issue22083.go` | verified |  |
| go | `test/fixedbugs/issue28926.go` | verified |  |
| go | `test/fixedbugs/issue4495.go` | verified |  |
| go | `test/fixedbugs/issue47201.dir/a.go` | verified |  |
| go | `test/func4.go` | verified |  |
| go | `test/stackobj3.go` | verified |  |
| go | `test/typeparam/issue50264.go` | verified |  |
| grafana | `apps/alerting/alertenrichment/pkg/apis/alertenrichment/v1beta1/types.go` | verified |  |
| grafana | `apps/collections/pkg/apis/collections/v1alpha1/zz_generated.openapi.go` | verified |  |
| grafana | `packages/grafana-ui/src/components/Layout/Space.tsx` | verified |  |
| grafana | `pkg/login/social/connectors/grafana_com_oauth.go` | verified |  |
| grafana | `pkg/registry/apps/alerting/notifications/config/authorize_test.go` | verified |  |
| grafana | `pkg/registry/apps/alerting/notifications/inhibitionrule/storage.go` | verified |  |
| grafana | `pkg/services/accesscontrol/resourcepermissions/service.go` | verified |  |
| grafana | `pkg/services/apiserver/builder/runner/runner.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/validation_test.go` | verified |  |
| grafana | `pkg/services/ngalert/tests/fakes/kvstore.go` | verified |  |
| grafana | `pkg/services/serviceaccounts/api/token_test.go` | verified |  |
| grafana | `pkg/storage/unified/migrations/status_reader_test.go` | verified |  |
| grafana | `pkg/tests/api/azuremonitor/azuremonitor_test.go` | verified |  |
| grafana | `pkg/tests/apis/iam/team/team_integration_test.go` | verified |  |
| grafana | `public/app/core/constants.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/search/searchParser.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/styles/notifications.ts` | verified |  |
| grafana | `public/app/features/canvas/elements/server/types/database.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/Sidebar/DraggableList/useDropIndicator.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/hooks/usePendingPickerSetters.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/layout-auto-grid/AutoGridItemRenderer.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/variables/components/DefaultGroupByValueEditor.tsx` | verified |  |
| grafana | `public/app/features/inspector/InspectJSONTab.tsx` | verified |  |
| grafana | `public/app/features/panel/components/VizTypePicker/VisualizationSuggestions.tsx` | verified |  |
| grafana | `public/app/features/provisioning/components/Folders/FixFolderMetadataDrawer.tsx` | verified |  |
| grafana | `public/app/features/provisioning/hooks/useGetRepositoryRefs.ts` | verified |  |
| grafana | `public/app/features/query/state/updateQueries.ts` | verified |  |
| grafana | `public/app/plugins/datasource/influxdb/components/editor/config-v2/InfluxFluxDBConnection.tsx` | verified |  |
| grafana | `public/swagger/SwaggerPage.tsx` | verified |  |
