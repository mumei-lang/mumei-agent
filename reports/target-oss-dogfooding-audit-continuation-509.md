# Target OSS no-LLM dogfooding audit — continuation 509 (batch 510)

Run: 2026-07-23T07:21:21.647291+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/test/cgo_stubs_ppc64x_internal_linking_test.go` | verified |  |
| go | `src/cmd/compile/internal/loopvar/loopvar_test.go` | verified |  |
| go | `src/cmd/compile/internal/test/memcombine_test.go` | verified |  |
| go | `src/cmd/internal/obj/s390x/rotate_test.go` | verified |  |
| go | `src/cmd/link/internal/sym/reloc.go` | verified |  |
| go | `src/crypto/tls/handshake_client_tls13.go` | verified |  |
| go | `src/flag/example_test.go` | verified |  |
| go | `src/go/printer/comment.go` | verified |  |
| go | `src/html/template/examplefiles_test.go` | verified |  |
| go | `src/internal/chacha8rand/chacha8_generic.go` | verified |  |
| go | `src/internal/goexperiment/exp_runtimesecret_on.go` | verified |  |
| go | `src/math/cmplx/asin.go` | verified |  |
| go | `src/net/cgo_resold.go` | verified |  |
| go | `src/net/sock_linux_test.go` | verified |  |
| go | `src/reflect/visiblefields_test.go` | verified |  |
| go | `src/runtime/pprof/pprof_windows.go` | verified |  |
| go | `src/runtime/security_nonunix.go` | verified |  |
| go | `test/abi/bad_select_crash.go` | verified |  |
| go | `test/fixedbugs/gcc67968.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue15722.go` | verified |  |
| go | `test/fixedbugs/issue32187.go` | verified |  |
| go | `test/fixedbugs/issue4590.dir/pkg2.go` | verified |  |
| go | `test/fixedbugs/issue6866.go` | verified |  |
| go | `test/mallocfin.go` | verified |  |
| go | `test/struct0.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v0alpha1/snapshot_schema_gen.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v25.go` | verified |  |
| grafana | `apps/dashvalidator/pkg/validator/prometheus/fetcher.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/applyconfiguration/provisioning/v0alpha1/testjoboptions.go` | verified |  |
| grafana | `pkg/plugins/backendplugin/chunked/chunked.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/refs.go` | verified |  |
| grafana | `pkg/registry/apps/alerting/rules/register.go` | verified |  |
| grafana | `pkg/services/ngalert/models/errors.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/legacy_storage/config_test.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/tag_mig.go` | verified |  |
| grafana | `pkg/storage/unified/testing/search_and_storage.go` | verified |  |
| grafana | `pkg/tsdb/azuremonitor/azmoncredentials/builder_test.go` | verified |  |
| grafana | `public/app/core/navigation/patch/interceptLinkClicks.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/extensions/ConfirmationNavigationModal.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/notificaton-preview/NotificationPreview.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/edit-pane/dashboard/variablesDragEndHandler.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/saving/DetectChangesWorker.ts` | verified |  |
| grafana | `public/app/features/dashboard/components/DashNav/DashNavTimeControls.tsx` | verified |  |
| grafana | `public/app/features/dashboard/dashgrid/DashboardLibrary/utils/assistantHelpers.ts` | verified |  |
| grafana | `public/app/features/dimensions/editors/ValueMappingsEditor/ValueMappingsEditor.tsx` | verified |  |
| grafana | `public/app/features/manage-dashboards/import/components/ImportOverviewV2.tsx` | verified |  |
| grafana | `public/app/features/plugins/admin/components/PluginDetailsBody.tsx` | verified |  |
| grafana | `public/app/features/query/components/QueryLibraryEditingContainer.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/webpack.config.ts` | verified |  |
| grafana | `public/app/plugins/panel/nodeGraph/createLayoutWorker.ts` | verified |  |
