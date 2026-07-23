# Target OSS no-LLM dogfooding audit — continuation 451 (batch 452)

Run: 2026-07-23T03:19:48.299592+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/abi/abiutils.go` | verified |  |
| go | `src/crypto/x509/pkcs8_test.go` | verified |  |
| go | `src/go/ast/filter_test.go` | verified |  |
| go | `src/internal/strconv/atof_test.go` | verified |  |
| go | `src/math/rand/normal.go` | verified |  |
| go | `src/net/mac_test.go` | verified |  |
| go | `src/runtime/align_test.go` | verified |  |
| go | `src/runtime/mpagecache.go` | verified |  |
| go | `src/runtime/os_linux_be64.go` | verified |  |
| go | `test/fixedbugs/bug058.go` | verified |  |
| go | `test/fixedbugs/bug475.go` | verified |  |
| go | `test/fixedbugs/issue10135.go` | verified |  |
| go | `test/fixedbugs/issue12525.go` | verified |  |
| go | `test/fixedbugs/issue26248.go` | verified |  |
| go | `test/fixedbugs/issue47201.go` | verified |  |
| go | `test/fixedbugs/issue8060.dir/a.go` | verified |  |
| go | `test/typeparam/issue49667.dir/main.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v2beta1/variable_codec_gen.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v2_test.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v37_test.go` | verified |  |
| grafana | `packages/grafana-o11y-ds-frontend/src/mocks/traceResponse.ts` | verified |  |
| grafana | `packages/grafana-sql/src/components/configuration/NumberInput.tsx` | verified |  |
| grafana | `pkg/api/frontend_logging_test.go` | verified |  |
| grafana | `pkg/apiserver/endpoints/filters/tracing_log.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/fixfoldermetadata/worker.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/resources/id_test.go` | verified |  |
| grafana | `pkg/services/accesscontrol/permreg/permreg.go` | verified |  |
| grafana | `pkg/services/authz/zanzana/server/server_mutate_teambindings_test.go` | verified |  |
| grafana | `pkg/services/folder/folderimpl/conversions.go` | verified |  |
| grafana | `pkg/services/ngalert/accesscontrol/models.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/legacy_storage/templates.go` | verified |  |
| grafana | `pkg/services/ngalert/prom/models.go` | verified |  |
| grafana | `pkg/tsdb/loki/kinds/dataquery/types_dataquery_gen.go` | verified |  |
| grafana | `public/app/core/utils/debugLog.ts` | verified |  |
| grafana | `public/app/features/admin/UserSessions.tsx` | verified |  |
| grafana | `public/app/features/admin/ldap/LdapSyncInfo.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/contact-points/ContactPoint.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/import-to-gma/Wizard/PreviousButton.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/notification-policies/timingOptions.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/state/AlertingQueryRunner.ts` | verified |  |
| grafana | `public/app/features/browse-dashboards/components/BrowseActions/SelectedMixResourcesMsgModal.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/inspect/InspectDataTab.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelDataPane/NewAlertRuleButton.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/Body/QueryEditorBody.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/sharing/ShareButton/share-externally/EmailShare/ConfigEmailSharing/EmailListConfiguration.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/sharing/ShareButton/share-snapshot/UpsertSnapshot.tsx` | verified |  |
| grafana | `public/app/features/provisioning/Wizard/BootstrapStep.tsx` | verified |  |
| grafana | `public/app/features/variables/inspect/types.ts` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/azure_monitor/url_builder.ts` | verified |  |
| grafana | `public/app/plugins/panel/nodeGraph/Marker.tsx` | verified |  |
