# Target OSS no-LLM dogfooding audit — continuation 389 (batch 390)

Run: 2026-07-23T00:05:42.451376+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/go/internal/fsys/fsys.go` | verified |  |
| go | `src/cmd/internal/objabi/path.go` | verified |  |
| go | `src/crypto/internal/fips140/mldsa/field_test.go` | verified |  |
| go | `src/crypto/internal/fips140test/nistec_ordinv_fips140v1.28_test.go` | verified |  |
| go | `src/debug/buildinfo/search_test.go` | verified |  |
| go | `src/encoding/gob/decoder.go` | verified |  |
| go | `src/net/http/async_test.go` | verified |  |
| go | `src/net/http/internal/http2/transport_test.go` | verified |  |
| go | `src/net/textproto/header.go` | verified |  |
| go | `src/os/exec/lp_unix.go` | verified |  |
| go | `src/runtime/secret/stubs_noasm.go` | verified |  |
| go | `src/syscall/syscall_unix_test.go` | verified |  |
| go | `src/testing/iotest/reader_test.go` | verified |  |
| go | `test/chan/goroutines.go` | verified |  |
| go | `test/fixedbugs/gcc89321.go` | verified |  |
| go | `test/fixedbugs/issue10219.go` | verified |  |
| go | `test/typeparam/issue50109.go` | verified |  |
| grafana | `apps/advisor/pkg/app/checks/datasourcecheck/health_check_step.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v0alpha1/config_client_gen.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v2alpha1/dashboard_spec_gen.go` | verified |  |
| grafana | `apps/example/plugin/src/generated/example/v1alpha1/types.metadata.gen.ts` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/notifications.alerting/v1beta1/baseAPI.ts` | verified |  |
| grafana | `packages/grafana-data/src/utils/selectUtils.ts` | verified |  |
| grafana | `packages/grafana-i18n/src/eslint/index.d.ts` | verified |  |
| grafana | `packages/grafana-schema/src/schema/dashboard/v1beta1/types.metadata.gen.ts` | verified |  |
| grafana | `pkg/registry/apis/datasource/openapi.go` | verified |  |
| grafana | `pkg/registry/apis/iam/authorizer/team_binding_authorizer_test.go` | verified |  |
| grafana | `pkg/registry/apis/iam/display/keys_test.go` | verified |  |
| grafana | `pkg/registry/apis/secret/encryption/cipher/provider/cipher_aesgcm_test.go` | verified |  |
| grafana | `pkg/services/authz/zanzana/server/server_read.go` | verified |  |
| grafana | `pkg/services/dashboardimport/utils/dash_template_evaluator.go` | verified |  |
| grafana | `pkg/services/extsvcauth/registry/service.go` | verified |  |
| grafana | `pkg/services/ngalert/api/forking_ruler.go` | verified |  |
| grafana | `pkg/services/ngalert/api/generated_base_api_alertmanager.go` | verified |  |
| grafana | `pkg/services/ngalert/store/admin_configuration_store_mock.go` | verified |  |
| grafana | `pkg/services/ngalert/tests/fakes/provisioning.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/common.go` | verified |  |
| grafana | `pkg/storage/unified/resource/selectable_fields.go` | verified |  |
| grafana | `public/app/core/components/NavLandingPage/NavLandingPageCard.tsx` | verified |  |
| grafana | `public/app/core/components/ThemeSelector/ThemeCard.tsx` | verified |  |
| grafana | `public/app/features/admin/EnterpriseAuthFeaturesCard.tsx` | verified |  |
| grafana | `public/app/features/browse-dashboards/components/BrowseFilters.tsx` | verified |  |
| grafana | `public/app/features/plugins/importer/pluginImporter.ts` | verified |  |
| grafana | `public/app/features/provisioning/components/Folders/FolderReadmePanel.tsx` | verified |  |
| grafana | `public/app/features/search/service/searcher.ts` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/ConfigEditor/CurrentUserFallbackCredentials.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/LogsQueryEditor/syntax.ts` | verified |  |
| grafana | `public/app/plugins/panel/barchart/presets.ts` | verified |  |
| grafana | `public/app/plugins/panel/canvas/components/connections/Connections.tsx` | verified |  |
| grafana | `public/app/plugins/panel/gauge/presets.ts` | verified |  |
