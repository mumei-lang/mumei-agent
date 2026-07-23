# Target OSS no-LLM dogfooding audit — continuation 460 (batch 461)

Run: 2026-07-23T04:02:16.635686+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ssa/_gen/MIPS64Ops.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/_gen/multiscanner.go` | verified |  |
| go | `src/crypto/internal/fips140cache/cache_test.go` | verified |  |
| go | `src/crypto/internal/sysrand/rand_test.go` | verified |  |
| go | `src/debug/dwarf/class_string.go` | verified |  |
| go | `src/image/gif/reader_test.go` | verified |  |
| go | `src/math/cmplx/tan.go` | verified |  |
| go | `src/net/http/internal/http2/errors.go` | verified |  |
| go | `src/net/http/internal/http2/writesched_test.go` | verified |  |
| go | `src/net/smtp/auth.go` | verified |  |
| go | `src/os/dirent_aix.go` | verified |  |
| go | `src/syscall/mmap_unix_test.go` | verified |  |
| go | `src/time/zoneinfo_abbrs_windows.go` | verified |  |
| go | `src/time/zoneinfo_wasip1.go` | verified |  |
| go | `test/convert2.go` | verified |  |
| go | `test/fixedbugs/bug015.go` | verified |  |
| go | `test/fixedbugs/bug255.go` | verified |  |
| go | `test/fixedbugs/bug419.go` | verified |  |
| go | `test/fixedbugs/issue52279.go` | verified |  |
| go | `test/fixedbugs/issue54307.go` | verified |  |
| go | `test/linkx.go` | verified |  |
| go | `test/typeparam/issue48306.dir/a.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/conversion/v1.go` | verified |  |
| grafana | `apps/dashvalidator/pkg/generated/dashboardcompatibilityscore/v1alpha1/dashboardcompatibilityscore_codec_gen.go` | verified |  |
| grafana | `apps/example/pkg/apis/example/v1alpha1/example_getfoo_response_body_types_gen.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/serviceaccount_listserviceaccounttokens_request_params_object_gen.go` | verified |  |
| grafana | `apps/logsdrilldown/plugin/src/generated/logsdrilldowndefaultcolumns/v1beta1/logsdrilldowndefaultcolumns_object_gen.ts` | verified |  |
| grafana | `apps/plugins/pkg/app/metrics/metrics.go` | verified |  |
| grafana | `apps/provisioning/pkg/connection/tester_test.go` | verified |  |
| grafana | `packages/grafana-runtime/src/services/templateSrv.ts` | verified |  |
| grafana | `pkg/api/dashboard_snapshot.go` | verified |  |
| grafana | `pkg/cmd/grafana-cli/commands/log_last_migration.go` | verified |  |
| grafana | `pkg/infra/serverlock/serverlock_test.go` | verified |  |
| grafana | `pkg/registry/apis/iam/globalrole/inmemory/api_installer_test.go` | verified |  |
| grafana | `pkg/registry/apis/iam/noopstorage/rest.go` | verified |  |
| grafana | `pkg/registry/apis/preferences/migration_registrar.go` | verified |  |
| grafana | `pkg/registry/apis/secret/service/secure_value_test.go` | verified |  |
| grafana | `pkg/services/search/service.go` | verified |  |
| grafana | `pkg/services/ssosettings/validation/oauth_validators.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/foldermetadata/full_sync_invalid_folder_metadata_test.go` | verified |  |
| grafana | `public/app/features/admin/AdminEditOrgPage.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/receivers/form/fields/KeyValueMapInput.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rules/NoRulesCTA.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/hooks/abilities/alertmanager/useContactPointAbility.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/insights/mimir/Silences.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/new-toolbar/actions/DiscardPanelButton.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/types/LayoutRegistryItem.ts` | verified |  |
| grafana | `public/app/features/migrate-to-cloud/onprem/EmptyState/CallToAction/CallToAction.tsx` | verified |  |
| grafana | `public/app/features/plugins/admin/components/PluginDetailsPanel.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/loki/querybuilder/operationUtils.ts` | verified |  |
