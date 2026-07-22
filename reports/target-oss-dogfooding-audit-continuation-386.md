# Target OSS no-LLM dogfooding audit — continuation 386 (batch 387)

Run: 2026-07-22T23:54:25.511389+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/go/internal/mmap/mmap_unix.go` | verified |  |
| go | `src/cmd/go/internal/vcweb/vcweb_test.go` | verified |  |
| go | `src/cmd/go/internal/web/url_other.go` | verified |  |
| go | `src/cmd/internal/goobj/builtin.go` | verified |  |
| go | `src/go/types/scope.go` | verified |  |
| go | `src/image/gif/reader.go` | verified |  |
| go | `src/internal/goexperiment/exp_fieldtrack_on.go` | verified |  |
| go | `src/log/syslog/syslog.go` | verified |  |
| go | `src/net/http/internal/http2/config.go` | verified |  |
| go | `src/syscall/getdirentries_test.go` | verified |  |
| go | `test/ddd2.dir/ddd3.go` | verified |  |
| go | `test/fixedbugs/bug003.go` | verified |  |
| go | `test/fixedbugs/bug198.go` | verified |  |
| go | `test/fixedbugs/issue20014.dir/a/a.go` | verified |  |
| go | `test/fixedbugs/issue46957.go` | verified |  |
| go | `test/interface/private.go` | verified |  |
| go | `test/stress/parsego.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v17.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v19_test.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v41_test.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/applyconfiguration/provisioning/v0alpha1/resourcecount.go` | verified |  |
| grafana | `devenv/docker/blocks/loki/data/data.js` | verified |  |
| grafana | `packages/grafana-ui/src/components/DataLinks/DataLinkInput.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Layout/utils/responsiveness.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Select/IndicatorsContainer.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/TableNG/components/HeaderCell.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/VizTooltip/VizTooltipRow.tsx` | verified |  |
| grafana | `pkg/api/dtos/short_url.go` | verified |  |
| grafana | `pkg/api/pluginproxy/ds_proxy.go` | verified |  |
| grafana | `pkg/registry/apis/preferences/utils/authorizer.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/sync/folder_metadata_incremental_diff.go` | verified |  |
| grafana | `pkg/services/libraryelements/fake/libraryelements_service_test.go` | verified |  |
| grafana | `pkg/services/plugindashboards/plugindashboards.go` | verified |  |
| grafana | `pkg/services/signingkeys/signingkeysimpl/service.go` | verified |  |
| grafana | `pkg/setting/setting_anonymous.go` | verified |  |
| grafana | `pkg/storage/unified/resource/search_vector_test.go` | verified |  |
| grafana | `pkg/storage/unified/sql/backend_bulk_test.go` | verified |  |
| grafana | `public/app/core/components/NestedFolderPicker/utils.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/plugins/useAlertingHomePageExtensions.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/triage/scene/expressionBuilder.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/edit-pane/add-new/AddNewEditPane.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/QueryEditorContextWrapper.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/new-toolbar/actions/SaveLibraryPanelButton.tsx` | verified |  |
| grafana | `public/app/features/dashboard/utils/panel.ts` | verified |  |
| grafana | `public/app/features/dimensions/editors/ValueMappingsEditor/ValueMappingEditRow.tsx` | verified |  |
| grafana | `public/app/features/geo/gazetteer/gazetteer.ts` | verified |  |
| grafana | `public/app/features/query/state/processing/canceler.ts` | verified |  |
| grafana | `public/app/features/templating/fieldAccessorCache.ts` | verified |  |
| grafana | `public/app/plugins/panel/dashlist/module.tsx` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| grafana | `public/app/types/settings.ts` | verified |  |
